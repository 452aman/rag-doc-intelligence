import os
import tempfile
import time

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["EMBEDDING_BACKEND"] = "hash"
os.environ["RERANKER"] = "none"
os.environ["GROQ_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import llm as llm_mod  # noqa: E402
from app.db import Base, engine  # noqa: E402
from app.ingest.extractor import ExtractedEntity, ExtractedRelation, Extraction  # noqa: E402
from app.main import app  # noqa: E402
from app.retrieval.index import index  # noqa: E402


class FakeLLM:
    available = True

    async def structured(self, schema, system, user):
        return Extraction(entities=[ExtractedEntity(name="Acme Robotics Inc", type="PARTY"), ExtractedEntity(name="Globex Analytics Ltd", type="PARTY")],
                          relations=[ExtractedRelation(src="Acme Robotics Inc", label="shares information with", dst="Globex Analytics Ltd")])

    async def complete(self, system, user):
        return "confidentiality period after termination"

    async def stream(self, system, user):
        for t in ["Confidentiality lasts ", "five (5) years [1]", " and cites [9]."]:
            yield t


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    llm_mod.set_llm(llm_mod.NullLLM())
    with TestClient(app) as c:
        index.rebuild(__import__("app.db", fromlist=["SessionLocal"]).SessionLocal())
        yield c


@pytest.fixture()
def loaded(client):
    client.post("/api/v1/documents/load-samples")
    end = time.time() + 30
    while time.time() < end:
        docs = client.get("/api/v1/documents").json()
        if len(docs) == 3 and all(d["status"] in ("ready", "failed") for d in docs):
            break
        time.sleep(0.1)
    assert all(d["status"] == "ready" for d in docs), docs
    return client
