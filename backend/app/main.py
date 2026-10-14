import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.db import Base, SessionLocal, engine
from app.embeddings import get_embedder
from app.llm import get_llm
from app.retrieval.index import index


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    await asyncio.to_thread(get_embedder)           # load the embedding model once
    with SessionLocal() as db:                      # rebuild FAISS / BM25 / graph from the database
        await asyncio.to_thread(index.rebuild, db)
    yield


app = FastAPI(title="Legal Document Intelligence API", version="2.0.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"], allow_headers=["*"])
app.include_router(router, prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "llm": get_llm().available}
