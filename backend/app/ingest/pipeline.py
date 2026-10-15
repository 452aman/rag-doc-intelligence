"""Background ingestion: parse → chunk → embed → extract graph → analyse → index."""
import asyncio
import logging
import re
from pathlib import Path

import numpy as np
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.guard import is_suspicious

from app.db import Chunk, Document, Entity, Mention, Relation, SessionLocal, est_tokens
from app.embeddings import get_embedder, normalize
from app.ingest.analysis import analyze_risks, guess_kind, key_facts
from app.ingest.chunker import chunk_pages
from app.ingest.extractor import Extraction, ExtractedEntity, entity_key, llm_extract, norm, regex_extract
from app.ingest.parsers import parse
from app.llm import get_llm
from app.retrieval.index import index

log = logging.getLogger(__name__)
_tasks: set[asyncio.Task] = set()


def set_stage(doc_id: int, stage: str, progress: int, **fields) -> None:
    with SessionLocal() as db:
        d = db.get(Document, doc_id)
        d.stage, d.progress = stage, progress
        d.status = "processing"
        for k, v in fields.items():
            setattr(d, k, v)
        db.commit()


def start(doc_id: int, name: str, data: bytes) -> None:
    t = asyncio.create_task(_run(doc_id, name, data))
    _tasks.add(t)
    t.add_done_callback(_tasks.discard)


def _get_or_create_entity(db, cache: dict, name: str, type_: str) -> Entity:
    key = entity_key(name, type_)
    ent = cache.get(key) or db.scalar(select(Entity).where(Entity.key == key))
    if ent is None:
        ent = Entity(key=key, name=norm(name), type=type_)
        db.add(ent)
        db.flush()
    cache[key] = ent
    return ent


def _store_graph(db, doc_id: int, chunk_ids: list[int], chunk_meta: dict[int, tuple[str, str]], llm_out: dict[int, Extraction]) -> int:
    cache: dict[str, Entity] = {}
    seen: set[int] = set()
    for cid in chunk_ids:
        section, text = chunk_meta[cid]
        ex = regex_extract(text, section)
        extra = llm_out.get(cid)
        entities: dict[str, ExtractedEntity] = {entity_key(e.name, e.type): e for e in ex.entities}
        relations = list(ex.relations)
        if extra:
            for e in extra.entities:
                entities.setdefault(entity_key(e.name, e.type), e)
            relations += extra.relations
        by_name: dict[str, Entity] = {}
        for e in entities.values():
            ent = _get_or_create_entity(db, cache, e.name, e.type)
            by_name[e.name.lower()] = ent
            seen.add(ent.id)
            db.add(Mention(entity_id=ent.id, chunk_id=cid, doc_id=doc_id))
        for r in relations:
            src, dst = by_name.get(norm(r.src).lower()), by_name.get(norm(r.dst).lower())
            if src is None or dst is None:  # LLM relation endpoints that aren't in the entity list: create as TERM
                for nm, slot in ((r.src, "s"), (r.dst, "d")):
                    # only keep endpoints that literally appear in the clause: guards against hallucinated entities
                    if by_name.get(norm(nm).lower()) is None and 1 < len(norm(nm)) < 80 and norm(nm).lower() in text.lower():
                        ent = _get_or_create_entity(db, cache, nm, "TERM")
                        by_name[norm(nm).lower()] = ent
                        seen.add(ent.id)
                        db.add(Mention(entity_id=ent.id, chunk_id=cid, doc_id=doc_id))
                src, dst = by_name.get(norm(r.src).lower()), by_name.get(norm(r.dst).lower())
            if src and dst and src.id != dst.id:
                db.add(Relation(src_id=src.id, dst_id=dst.id, label=norm(r.label)[:120], chunk_id=cid, doc_id=doc_id))
    db.flush()
    return len(seen)


async def _run(doc_id: int, name: str, data: bytes) -> None:
    try:
        set_stage(doc_id, "parsing", 5)
        pages = await asyncio.to_thread(parse, name, data)
        set_stage(doc_id, "chunking", 15, pages=len(pages))
        drafts = chunk_pages(pages)
        if not drafts:
            raise ValueError("Document produced no chunks")

        set_stage(doc_id, "embedding", 30)
        vecs = normalize(await asyncio.to_thread(get_embedder().embed, [f"{d.section}\n{d.text}" for d in drafts]))
        with SessionLocal() as db:
            rows = [Chunk(doc_id=doc_id, idx=i, section=d.section, page=d.page, text=d.text, suspicious=is_suspicious(d.text),
                    embedding=vecs[i].astype(np.float32).tobytes())
                    for i, d in enumerate(drafts)]
            db.add_all(rows)
            db.commit()
            chunk_ids = [r.id for r in rows]
        meta = {cid: (d.section, d.text) for cid, d in zip(chunk_ids, drafts)}

        llm = get_llm()
        llm_out: dict[int, Extraction] = {}
        if llm.available:
            set_stage(doc_id, "extracting graph (LLM)", 50)
            llm_out = await llm_extract(llm, [(cid, s, t) for cid, (s, t) in meta.items()])
        set_stage(doc_id, "building graph", 80)
        triples = [(cid, s, t) for cid, (s, t) in meta.items()]
        with SessionLocal() as db:
            n_entities = _store_graph(db, doc_id, chunk_ids, meta, llm_out)
            db.commit()

        set_stage(doc_id, "analysing", 90)
        full = "\n".join(d.text for d in drafts)
        with SessionLocal() as db:
            doc = db.get(Document, doc_id)
            doc.kind = guess_kind(full)
            doc.key_facts = key_facts(triples)
            doc.risks = analyze_risks(triples)
            doc.chunk_count, doc.entity_count, doc.est_tokens = len(drafts), n_entities, est_tokens(full)
            doc.suspicious_chunks = sum(1 for d in drafts if is_suspicious(d.text))
            doc.status, doc.stage, doc.progress = "ready", "ready", 100
            db.commit()
            await asyncio.to_thread(index.rebuild, db)
    except Exception as e:
        log.exception("ingestion failed for %s", name)
        with SessionLocal() as db:
            d = db.get(Document, doc_id)
            d.status, d.stage, d.error = "failed", "failed", str(e)[:400]
            db.commit()


# ------------------------------------------------------------------ persistence, recovery, retry
def save_original(doc_id: int, name: str, data: bytes) -> str:
    """Keep the uploaded bytes on disk so a crash or restart never loses a document mid-ingestion."""
    folder = Path(get_settings().data_dir) / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120]
    path = folder / f"{doc_id}_{safe}"
    path.write_bytes(data)
    return str(path)


def purge_derived(db, doc_id: int) -> None:
    """Remove everything ingestion produced for a document (chunks, graph rows) so it can be re-run cleanly."""
    for model in (Relation, Mention):
        db.execute(delete(model).where(model.doc_id == doc_id))
    db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    db.execute(delete(Entity).where(Entity.id.not_in(select(Mention.entity_id))))


def restart(doc_id: int) -> bool:
    """Re-run ingestion from the stored original. Returns False if the file is gone."""
    with SessionLocal() as db:
        doc = db.get(Document, doc_id)
        if not doc or not doc.file_path or not Path(doc.file_path).exists():
            return False
        purge_derived(db, doc_id)
        doc.status, doc.stage, doc.progress, doc.error = "queued", "queued", 0, None
        name, path = doc.name, doc.file_path
        db.commit()
    start(doc_id, name, Path(path).read_bytes())
    return True


def recover_stuck() -> dict:
    """Called at startup: documents left queued/processing by a crash are resumed, or failed with a clear reason."""
    resumed = failed = 0
    with SessionLocal() as db:
        stuck = db.scalars(select(Document).where(Document.status.in_(["queued", "processing"]))).all()
        ids = [d.id for d in stuck]
    for doc_id in ids:
        if restart(doc_id):
            resumed += 1
        else:
            with SessionLocal() as db:
                d = db.get(Document, doc_id)
                d.status, d.stage, d.error = "failed", "failed", "Interrupted by a restart and the original file was not saved. Please re-upload."
                db.commit()
            failed += 1
    return {"resumed": resumed, "failed": failed}
