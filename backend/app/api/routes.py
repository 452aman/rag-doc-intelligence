import asyncio
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app import evaluation, qa
from app.auth import current_user
from app.core.config import get_settings
from app.db import (Chunk, Conversation, Document, Entity, Feedback, Mention, Message, Relation, SessionLocal, User, get_db)
from app.guard import injection_hits
from app.ingest import pipeline
from app.llm import get_llm
from app.observability import metrics
from app.retrieval.index import MODES, index

router = APIRouter()
SAMPLES = next((p for p in (Path(__file__).resolve().parents[3] / "samples", Path("/samples")) if p.exists()), Path("samples"))


# ------------------------------------------------------------------ helpers (ownership is enforced here, once)
def owned_doc(db: Session, user: User, doc_id: int) -> Document:
    d = db.get(Document, doc_id)
    if not d or d.owner_id != user.id:
        raise HTTPException(404, "Document not found")   # 404, not 403: don't reveal that another user's document exists
    return d


def my_ready_ids(db: Session, uid: int) -> list[int]:
    return list(db.scalars(select(Document.id).where(Document.owner_id == uid, Document.status == "ready")))


def scope_ids(db: Session, uid: int, requested: list[int] | None) -> list[int]:
    """The documents a request may touch: the user's ready documents, narrowed by any ids the client asked for."""
    mine = my_ready_ids(db, uid)
    return mine if not requested else [i for i in requested if i in set(mine)]


def doc_dict(d: Document, detail: bool = False) -> dict:
    out = {"id": d.id, "name": d.name, "kind": d.kind, "status": d.status, "stage": d.stage, "progress": d.progress, "pages": d.pages,
           "chunk_count": d.chunk_count, "entity_count": d.entity_count, "est_tokens": d.est_tokens, "error": d.error,
           "suspicious_chunks": d.suspicious_chunks, "created_at": d.created_at.isoformat(),
           "risk_counts": {s: sum(1 for r in d.risks if r["severity"] == s) for s in ("high", "medium", "low", "info")}}
    if detail:
        out.update(key_facts=d.key_facts, risks=d.risks)
    return out


def _create_and_start(db: Session, user: User, name: str, data: bytes) -> tuple[Document, bool]:
    digest = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(Document).where(Document.owner_id == user.id, Document.content_hash == digest, Document.status != "failed"))
    if dup:
        return dup, True
    doc = Document(name=name, owner_id=user.id, content_hash=digest)
    db.add(doc)
    db.commit()
    doc.file_path = pipeline.save_original(doc.id, name, data)
    db.commit()
    pipeline.start(doc.id, name, data)
    metrics.inc("documents_uploaded_total")
    return doc, False


# ------------------------------------------------------------------ documents
@router.post("/documents", status_code=202)
async def upload(response: Response, file: UploadFile = File(...), db: Session = Depends(get_db), user: User = Depends(current_user)):
    data = await file.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File larger than {get_settings().max_upload_mb}MB")
    if not (file.filename or "").lower().endswith((".pdf", ".docx", ".txt", ".md")):
        raise HTTPException(400, "Upload a PDF, DOCX, TXT or MD file")
    doc, duplicate = _create_and_start(db, user, file.filename, data)
    out = doc_dict(doc)
    out["duplicate"] = duplicate
    if duplicate:
        response.status_code = 200
    return out


@router.post("/documents/load-samples", status_code=202)
async def load_samples(db: Session = Depends(get_db), user: User = Depends(current_user)):
    existing = set(db.scalars(select(Document.name).where(Document.owner_id == user.id)))
    started = []
    for p in sorted(SAMPLES.glob("*.txt")):
        if p.name in existing:
            continue
        _create_and_start(db, user, p.name, p.read_bytes())
        started.append(p.name)
    return {"started": started}


@router.get("/documents")
def list_documents(db: Session = Depends(get_db), user: User = Depends(current_user)):
    return [doc_dict(d) for d in db.scalars(select(Document).where(Document.owner_id == user.id).order_by(Document.created_at.desc()))]


@router.get("/documents/{doc_id}")
def get_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = owned_doc(db, user, doc_id)
    out = doc_dict(d, detail=True)
    out["chunks"] = [{"id": c.id, "idx": c.idx, "section": c.section, "page": c.page, "text": c.text, "suspicious": c.suspicious,
                      "injection_phrases": injection_hits(c.text) if c.suspicious else []} for c in d.chunks]
    return out


@router.post("/documents/{doc_id}/retry", status_code=202)
async def retry_document(   # async: background ingestion must be scheduled on the running event loop, not a worker thread
   doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = owned_doc(db, user, doc_id)
    if d.status not in ("failed",):
        raise HTTPException(409, f"Only failed documents can be retried (this one is {d.status})")
    if not pipeline.restart(d.id):
        raise HTTPException(410, "The original file is no longer stored. Please upload it again.")
    return {"restarted": d.id}


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(doc_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = owned_doc(db, user, doc_id)
    path = d.file_path
    for model in (Relation, Mention):
        db.execute(delete(model).where(model.doc_id == doc_id))
    db.execute(delete(Chunk).where(Chunk.doc_id == doc_id))
    db.delete(d)
    db.execute(delete(Entity).where(Entity.id.not_in(select(Mention.entity_id))))   # entities no document mentions any more
    db.commit()
    if path:
        Path(path).unlink(missing_ok=True)
    await asyncio.to_thread(index.rebuild, db)


@router.get("/graph")
def graph(doc_id: int | None = None, max_nodes: int = Query(120, le=300), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if doc_id is not None:
        owned_doc(db, user, doc_id)
    return index.graph_json(doc_id, max_nodes, allowed_docs=set(my_ready_ids(db, user.id)))


@router.get("/search")
async def search(q: str = Query(min_length=2), mode: str = "full", k: int = Query(5, le=20), db: Session = Depends(get_db), user: User = Depends(current_user)):
    if mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")
    res = await asyncio.to_thread(index.search, q, k, mode, my_ready_ids(db, user.id))
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
async def chat(body: ChatIn, user: User = Depends(current_user)):
    if body.mode not in MODES:
        raise HTTPException(422, f"mode must be one of {MODES}")
    uid = user.id
    with SessionLocal() as db:
        conv = db.get(Conversation, body.conversation_id) if body.conversation_id else None
        if body.conversation_id and (not conv or conv.owner_id != uid):
            raise HTTPException(404, "Conversation not found")
        if not conv:
            conv = Conversation(title=body.question[:60], owner_id=uid)
            db.add(conv)
            db.flush()
        history = [{"role": m.role, "content": m.content} for m in conv.messages]
        db.add(Message(conversation_id=conv.id, role="user", content=body.question))
        db.commit()
        conv_id = conv.id
        allowed = scope_ids(db, uid, body.doc_ids)   # only the caller's ready documents can ever reach retrieval

    async def gen():
        yield _sse({"type": "conversation", "id": conv_id})
        retrieval: dict = {}
        async for ev in qa.answer_stream(get_llm(), body.question, history, allowed, body.mode):
            if ev["type"] == "retrieval":
                retrieval = ev
            if ev["type"] == "done":
                with SessionLocal() as db:
                    m = Message(conversation_id=conv_id, role="assistant", content=ev["answer"], citations=retrieval.get("citations", []),
                                meta={**ev["meta"], "cited": ev["cited"], "entities": retrieval.get("entities", []),
                                      "graph_facts": retrieval.get("graph_facts", []), "query": retrieval.get("query")})
                    db.add(m)
                    db.commit()
                    ev["message_id"] = m.id
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _own_conv(db: Session, user: User, cid: int) -> Conversation:
    c = db.get(Conversation, cid)
    if not c or c.owner_id != user.id:
        raise HTTPException(404, "Conversation not found")
    return c


@router.get("/conversations")
def conversations(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Conversation).where(Conversation.owner_id == user.id).order_by(Conversation.id.desc()).limit(40))
    return [{"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()} for c in rows]


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    c = _own_conv(db, user, cid)
    fb = {f.message_id: f.rating for f in db.scalars(select(Feedback).where(Feedback.owner_id == user.id))}
    return {"id": c.id, "title": c.title, "messages": [{"id": m.id, "role": m.role, "content": m.content, "citations": m.citations,
                                                        "meta": m.meta, "rating": fb.get(m.id)} for m in c.messages]}


@router.delete("/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    db.delete(_own_conv(db, user, cid))
    db.commit()


# ------------------------------------------------------------------ feedback (becomes an evaluation dataset)
class FeedbackIn(BaseModel):
    rating: int = Field(description="+1 helpful, -1 not helpful")
    comment: str = Field(default="", max_length=500)


@router.post("/messages/{message_id}/feedback")
def give_feedback(message_id: int, body: FeedbackIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.rating not in (-1, 1):
        raise HTTPException(422, "rating must be 1 or -1")
    m = db.get(Message, message_id)
    if not m or m.role != "assistant" or m.conversation.owner_id != user.id:
        raise HTTPException(404, "Message not found")
    fb = db.scalar(select(Feedback).where(Feedback.message_id == message_id))
    if fb:
        fb.rating, fb.comment = body.rating, body.comment
    else:
        db.add(Feedback(owner_id=user.id, message_id=message_id, rating=body.rating, comment=body.comment))
    db.commit()
    return {"message_id": message_id, "rating": body.rating}


@router.get("/feedback/summary")
def feedback_summary(db: Session = Depends(get_db), user: User = Depends(current_user)):
    rows = db.scalars(select(Feedback).where(Feedback.owner_id == user.id)).all()
    return {"total": len(rows), "up": sum(1 for r in rows if r.rating > 0), "down": sum(1 for r in rows if r.rating < 0)}


@router.get("/feedback/export.jsonl")
def feedback_export(db: Session = Depends(get_db), user: User = Depends(current_user)):
    """One JSON object per rated answer: question, answer, cited sources, rating, comment. Ready to use as an eval set."""
    lines = []
    for fb in db.scalars(select(Feedback).where(Feedback.owner_id == user.id).order_by(Feedback.id)):
        m = db.get(Message, fb.message_id)
        prior = [x for x in m.conversation.messages if x.id < m.id and x.role == "user"]
        lines.append(json.dumps({"question": prior[-1].content if prior else None, "answer": m.content, "rating": fb.rating, "comment": fb.comment,
                                 "sources": [{"doc": c["doc_name"], "section": c["section"]} for c in m.citations], "mode": m.meta.get("mode")}))
    return Response("\n".join(lines) + ("\n" if lines else ""), media_type="application/x-ndjson",
                    headers={"Content-Disposition": "attachment; filename=feedback.jsonl"})


# ------------------------------------------------------------------ contract comparison
class CompareIn(BaseModel):
    doc_a: int
    doc_b: int
    topic: str = Field(min_length=3, max_length=200)


@router.post("/compare")
async def compare(body: CompareIn, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if body.doc_a == body.doc_b:
        raise HTTPException(422, "Pick two different contracts")
    a, b = owned_doc(db, user, body.doc_a), owned_doc(db, user, body.doc_b)
    if a.status != "ready" or b.status != "ready":
        raise HTTPException(409, "Both contracts must finish processing first")

    async def gen():
        async for ev in qa.compare_stream(get_llm(), (a.id, a.name), (b.id, b.name), body.topic):
            yield _sse(ev)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ evaluation + stats
@router.post("/evaluation/run")
async def run_eval(k: int = Query(5, ge=1, le=10), db: Session = Depends(get_db), user: User = Depends(current_user)):
    mine = my_ready_ids(db, user.id)
    names = set(db.scalars(select(Document.name).where(Document.id.in_(mine))))
    if not {p.name for p in SAMPLES.glob("*.txt")} <= names:
        raise HTTPException(409, "Load the sample documents first")
    return await asyncio.to_thread(evaluation.run_retrieval_eval, k, mine)


@router.get("/stats")
def stats(db: Session = Depends(get_db), user: User = Depends(current_user)):
    docs = db.scalars(select(Document).where(Document.owner_id == user.id, Document.status == "ready")).all()
    ids = {d.id for d in docs}
    return {"documents": len(docs), "chunks": sum(1 for h in index.chunks.values() if h.doc_id in ids),
            "entities": sum(d.entity_count for d in docs), "llm": get_llm().available}
