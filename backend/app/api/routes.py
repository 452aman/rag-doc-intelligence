import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import evaluation, qa
from app.core.config import get_settings
from app.db import Chunk, Conversation, Document, Entity, Mention, Message, Relation, SessionLocal, get_db
from app.ingest import pipeline
from app.llm import get_llm
from app.retrieval.index import MODES, index

router = APIRouter()
SAMPLES = next((p for p in (Path(__file__).resolve().parents[3] / "samples", Path("/samples")) if p.exists()), Path("samples"))


def doc_dict(d: Document, detail: bool = False) -> dict:
    out = {"id": d.id, "name": d.name, "kind": d.kind, "status": d.status, "stage": d.stage, "progress": d.progress, "pages": d.pages,
           "chunk_count": d.chunk_count, "entity_count": d.entity_count, "est_tokens": d.est_tokens, "error": d.error,
           "created_at": d.created_at.isoformat(), "risk_counts": {s: sum(1 for r in d.risks if r["severity"] == s) for s in ("high", "medium", "low", "info")}}
    if detail:
        out.update(key_facts=d.key_facts, risks=d.risks)
    return out


@router.post("/documents", status_code=202)
async def upload(file: UploadFile = File(...), db: Session = Depends(get_db)):
    data = await file.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {get_settings().max_upload_mb}MB")
    if not (file.filename or "").lower().endswith((".pdf", ".docx", ".txt", ".md")):
        raise HTTPException(400, "Upload a PDF, DOCX, TXT or MD file")
    doc = Document(name=file.filename)
    db.add(doc)
    db.commit()
    pipeline.start(doc.id, file.filename, data)
    return doc_dict(doc)


@router.post("/documents/load-samples", status_code=202)
async def load_samples(db: Session = Depends(get_db)):
    existing = set(db.scalars(select(Document.name)))
    started = []
    for p in sorted(SAMPLES.glob("*.txt")):
        if p.name in existing:
            continue
        doc = Document(name=p.name)
        db.add(doc)
        db.commit()
        pipeline.start(doc.id, p.name, p.read_bytes())
        started.append(p.name)
    return {"started": started}


@router.get("/documents")
def list_documents(db: Session = Depends(get_db)):
    return [doc_dict(d) for d in db.scalars(select(Document).order_by(Document.created_at.desc()))]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    out = doc_dict(d, detail=True)
    out["chunks"] = [{"id": c.id, "idx": c.idx, "section": c.section, "page": c.page, "text": c.text} for c in d.chunks]
    return out


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: Session = Depends(get_db)):
    d = db.get(Document, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    for model in (Relation, Mention):
        db.execute(delete(model).where(model.doc_id == doc_id))
    db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    db.delete(d)
    # drop entities no document mentions any more
    orphan = select(Mention.entity_id)
    db.execute(delete(Entity).where(Entity.id.not_in(orphan)))
    db.commit()
    await asyncio.to_thread(index.rebuild, db)


@router.get("/graph")
def graph(doc_id: int | None = None, max_nodes: int = Query(120, le=300)):
    return index.graph_json(doc_id, max_nodes)


@router.get("/search")
async def search(q: str = Query(min_length=2), mode: str = "full", k: int = Query(5, le=20)):
    if mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")
    res = await asyncio.to_thread(index.search, q, k, mode)
    return {"entities": res.entities, "graph_facts": res.graph_facts, "hits": [qa.hit_to_dict(i, h) for i, h in enumerate(res.hits, 1)]}


# ------------------------------------------------------------------ chat
class ChatIn(BaseModel):
    question: str = Field(min_length=2, max_length=1000)
    conversation_id: int | None = None
    doc_ids: list[int] | None = None
    mode: str = "full"


def _sse(ev: dict) -> str:
    return f"data: {json.dumps(ev)}\n\n"


@router.post("/chat")
async def chat(body: ChatIn):
    if body.mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")

    with SessionLocal() as db:
        conv = db.get(Conversation, body.conversation_id) if body.conversation_id else None
        if body.conversation_id and not conv:
            raise HTTPException(404, "Conversation not found")
        if not conv:
            conv = Conversation(title=body.question[:60])
            db.add(conv)
            db.flush()
        history = [{"role": m.role, "content": m.content} for m in conv.messages]
        db.add(Message(conversation_id=conv.id, role="user", content=body.question))
        db.commit()
        conv_id = conv.id

    async def gen():
        yield _sse({"type": "conversation", "id": conv_id})
        retrieval: dict = {}
        async for ev in qa.answer_stream(get_llm(), body.question, history, body.doc_ids, body.mode):
            if ev["type"] == "retrieval":
                retrieval = ev
            if ev["type"] == "done":
                with SessionLocal() as db:
                    db.add(Message(conversation_id=conv_id, role="assistant", content=ev["answer"], citations=retrieval.get("citations", []),
                                   meta={**ev["meta"], "cited": ev["cited"], "entities": retrieval.get("entities", []),
                                         "graph_facts": retrieval.get("graph_facts", []), "query": retrieval.get("query")}))
                    db.commit()
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/conversations")
def conversations(db: Session = Depends(get_db)):
    rows = db.scalars(select(Conversation).order_by(Conversation.id.desc()).limit(40))
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    return {"id": c.id, "title": c.title, "messages": [{"id": m.id, "role": m.role, "content": m.content, "citations": m.citations, "meta": m.meta} for m in c.messages]}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversation not found")
    db.delete(c)
    db.commit()


@router.post("/evaluation/run")
async def run_eval(k: int = Query(5, ge=1, le=10)):
    if not index.chunks:
        raise HTTPException(409, "Load the sample documents first")
    return await asyncio.to_thread(evaluation.run_retrieval_eval, k)


@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    return {"documents": db.scalar(select(func.count()).select_from(Document).where(Document.status == "ready")) or 0,
            "chunks": len(index.chunks), "entities": index.graph.number_of_nodes(), "relations": index.graph.number_of_edges(),
            "llm": get_llm().available}
