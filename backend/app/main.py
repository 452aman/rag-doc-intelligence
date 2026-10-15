import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy import text

from app import auth, observability
from app.api.routes import router
from app.core.config import get_settings
from app.db import Base, SessionLocal, engine, ensure_schema
from app.embeddings import get_embedder
from app.ingest import pipeline
from app.llm import get_llm
from app.retrieval.index import index

log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    ensure_schema()                                 # upgrade databases created before accounts / dedup / flags existed
    await asyncio.to_thread(get_embedder)           # load the embedding model once
    with SessionLocal() as db:                      # rebuild FAISS / BM25 / graph from the database
        await asyncio.to_thread(index.rebuild, db)
    result = pipeline.recover_stuck()               # resume documents a crash or restart interrupted
    if result["resumed"] or result["failed"]:
        log.info("recovered interrupted ingestions", extra={"extra_fields": result})
    yield


app = FastAPI(title="Legal Document Intelligence API", version="3.0.0", lifespan=lifespan)
app.state.limiter = auth.limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Request-ID"])
observability.install(app)
app.include_router(auth.router, prefix="/api/v1")
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "llm": get_llm().available}


@app.get("/ready")
def ready():
    """Readiness: the database answers and the retrieval index is loaded. Used by orchestrators before routing traffic."""
    from fastapi import HTTPException
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        raise HTTPException(503, "database unavailable")
    return {"status": "ready", "chunks_indexed": len(index.chunks)}
