import json

from app.ingest.chunker import chunk_pages
from app.llm import set_llm
from tests.conftest import FakeLLM

NDA = open(__import__("pathlib").Path(__file__).resolve().parents[2] / "samples" / "nda_acme_globex.txt").read()


def test_chunker_keeps_clauses_whole_and_labels_sections():
    chunks = chunk_pages([(1, NDA)])
    assert 6 <= len(chunks) <= 14
    term = next(c for c in chunks if "4.2" in c.text)
    assert term.section.startswith("4.") and "thirty (30) days" in term.text
    assert all(len(c.text) < 1500 for c in chunks)


def test_ingestion_extracts_facts_risks_and_graph(loaded):
    docs = {d["name"]: d for d in loaded.get("/api/v1/documents").json()}
    nda = loaded.get(f"/api/v1/documents/{docs['nda_acme_globex.txt']['id']}").json()
    assert nda["kind"] == "nda" and "Acme Robotics Inc" in nda["key_facts"]["parties"]
    assert any(r["topic"] == "Termination for convenience" for r in nda["risks"])
    assert not any(r["topic"] == "No liability cap found" for r in nda["risks"])  # the NDA does cap liability
    g = loaded.get("/api/v1/graph").json()
    assert {n["type"] for n in g["nodes"]} >= {"PARTY", "DATE", "CLAUSE"} and g["links"]


def test_hybrid_search_finds_the_right_clause(loaded):
    r = loaded.get("/api/v1/search", params={"q": "how fast must a data breach be notified", "mode": "hybrid", "k": 3}).json()
    assert "seventy-two (72) hours" in r["hits"][0]["text"]
    assert r["hits"][0]["doc_name"].startswith("services")


def test_graph_mode_links_entities_and_scopes_documents(loaded):
    r = loaded.get("/api/v1/search", params={"q": "obligations of Globex Analytics", "mode": "hybrid+graph"}).json()
    assert any("Globex" in e for e in r["entities"])
    assert "graph" in {v for h in r["hits"] for v in h["via"]}


def test_chat_streams_validates_citations_and_persists(loaded):
    set_llm(FakeLLM())
    with loaded.stream("POST", "/api/v1/chat", json={"question": "How long does confidentiality last?", "mode": "hybrid"}) as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    types = [e["type"] for e in events]
    assert types[0] == "conversation" and "retrieval" in types and types.count("token") == 3 and types[-1] == "done"
    done = events[-1]
    assert done["cited"] == [1]            # [9] is out of range and must be dropped
    assert done["meta"]["prompt_tokens"] < done["meta"]["corpus_tokens"]
    conv = loaded.get(f"/api/v1/conversations/{events[0]['id']}").json()
    assert [m["role"] for m in conv["messages"]] == ["user", "assistant"] and conv["messages"][1]["citations"]


def test_chat_without_llm_falls_back_to_extractive(loaded):
    with loaded.stream("POST", "/api/v1/chat", json={"question": "what is the monthly fee", "mode": "hybrid"}) as s:
        events = [json.loads(line[6:]) for line in s.iter_lines() if line.startswith("data: ")]
    assert "No LLM key" in events[-1]["answer"]


def test_delete_document_removes_it_from_search_and_graph(loaded):
    docs = loaded.get("/api/v1/documents").json()
    msa = next(d for d in docs if d["name"].startswith("services"))
    assert loaded.delete(f"/api/v1/documents/{msa['id']}").status_code == 204
    r = loaded.get("/api/v1/search", params={"q": "monthly subscription fee", "mode": "hybrid"}).json()
    assert all(not h["doc_name"].startswith("services") for h in r["hits"])
    assert all(n["name"] != "Initech Software LLC" for n in loaded.get("/api/v1/graph").json()["nodes"])


def test_evaluation_reports_every_mode(loaded):
    out = loaded.post("/api/v1/evaluation/run").json()
    assert set(out["modes"]) == {"dense", "bm25", "hybrid", "hybrid+graph", "full"}
    assert out["modes"]["hybrid"]["hit@5"] >= 0.7 and out["token_reduction_vs_full_corpus"] > 0.3


def test_upload_validation(client):
    assert client.post("/api/v1/documents", files={"file": ("x.exe", b"abc")}).status_code == 400
