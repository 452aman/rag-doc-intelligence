# Legal Document Intelligence

A RAG platform for contracts. Upload PDFs/DOCX, then ask questions in plain English and get answers that cite the exact clauses they came from. Includes a clause-risk screen, a knowledge-graph explorer, and a built-in benchmark that measures what each retrieval stage actually contributes.

**Stack:** FastAPI · LangChain (Groq) · FAISS · BM25 · cross-encoder reranker · NetworkX · SQLAlchemy · JWT · SSE streaming · React 19 · TypeScript · TanStack Query · Tailwind · Recharts · Docker · GitHub Actions

## How it works

```
upload ─► parse (PDF/DOCX/TXT) ─► clause-aware chunking ─► embed (bge-small) ─► SQLite
                                         │
                                         ├─► entity + relation extraction (regex + LLM, grounded) ─► knowledge graph
                                         └─► key facts + clause-risk screen

question ─► condense follow-ups (LLM) ─► ┌ dense (FAISS)   ┐
                                         ├ lexical (BM25)  ├─► reciprocal-rank fusion ─► graph boost ─► cross-encoder rerank ─► top-5
                                         └ entity linking ─┘
         ─► grounded prompt ─► streamed answer ─► citation validation ─► sources panel
```

| Piece | Details |
|---|---|
| **Clause-aware chunking** | Splits on ARTICLE / numbered-clause boundaries instead of fixed windows, keeping each clause intact and labelled with its section and page. Oversized clauses fall back to sentence splitting with overlap. |
| **Hybrid retrieval** | FAISS dense search + BM25 (with suffix stemming so *renew* matches *renewing*), fused with reciprocal-rank fusion, then reranked by a cross-encoder (`ms-marco-MiniLM`). |
| **Knowledge graph** | Typed entities (parties, people, dates, amounts, periods, jurisdictions, defined terms) and LLM-extracted relations, merged across documents. LLM output is grounded: entities that don't literally appear in the clause are discarded. Links only *named* entities at query time and uses them to boost already-retrieved chunks and route questions to the right contract. |
| **Grounded answers** | The model sees numbered excerpts and must cite them. Citations are validated server-side (out-of-range numbers dropped, uncited answers flagged in the UI). Works without an API key in an extractive mode. |
| **Follow-up questions** | A condense step rewrites "and can they raise the price?" into a standalone query using the conversation. |
| **Risk screen** | 13 explainable rules (auto-renewal, non-compete, no liability cap, sole-remedy, IP assignment, indemnity…) quote the triggering clause and say why it matters. Not legal advice. |
| **Streaming UI** | Token streaming over SSE, clickable citation chips, per-answer latency and token accounting. |

## Production features

| Feature | What it does |
|---|---|
| **Accounts and private workspaces** | JWT auth (short-lived access token, rotating refresh token, rate-limited login). Every document, conversation, search, graph and benchmark is scoped to its owner. Other users' documents return 404, and an account with no documents searches nothing instead of everything. |
| **Contract comparison** | Pick two contracts and a topic. Retrieval runs separately inside each contract, the clauses are shown side by side, and a streamed summary cites them as `[A1]` / `[B2]`. |
| **Prompt-injection guard** | Clauses containing instruction-like text ("ignore previous instructions...") are flagged at ingestion and shown with the offending phrases. At query time every excerpt is fenced as untrusted data and the model is told never to obey it. |
| **Answer feedback** | Thumbs up/down on each answer (stored per user), exportable as a JSONL evaluation set: question, answer, cited sources, rating, comment. |
| **Resumable ingestion** | The uploaded original is stored. After a crash or restart, interrupted documents are re-run automatically; failed ones have a Retry button. Identical re-uploads are detected by content hash and not duplicated. |
| **Observability** | `X-Request-ID` on every response (propagated if supplied), structured JSON logs, `/metrics` in Prometheus text format, `/ready` readiness probe, security headers. |
| **CI** | GitHub Actions runs the backend tests (offline), type-checks and builds the frontend, and builds both Docker images. |

**Upgrading an existing database:** the schema is upgraded in place on startup (idempotent). Documents and conversations created before accounts existed are adopted by the **first account that registers**, so register first with the account you want to keep them.

## Measured results

`POST /api/v1/evaluation/run` (Evaluation page in the UI) runs 24 questions over the three bundled **synthetic** sample contracts. A retrieved chunk is a hit when it contains the gold answer text. Documents are *not* pre-selected, so retrieval has to find the right contract itself. Real run with local `bge-small` embeddings:

| Strategy | hit@1 | hit@3 | hit@5 | MRR | avg latency |
|---|---|---|---|---|---|
| Dense (FAISS) | 0.667 | 0.917 | 0.958 | 0.798 | 8 ms |
| BM25 | 0.708 | 0.917 | 1.000 | 0.822 | <1 ms |
| Hybrid (RRF) | 0.708 | 0.958 | 1.000 | 0.835 | 6 ms |
| Hybrid + graph boost | 0.667 | 0.917 | 1.000 | 0.803 | 6 ms |
| **Hybrid + graph + rerank** | **0.750** | 0.958 | 0.958 | **0.846** | 150 ms |

- Hybrid fusion beats either retriever alone on MRR and reaches 100% hit@5; the reranker gives the best top-1 accuracy.
- **The graph did not improve retrieval on this small corpus.** Early versions that injected graph candidates actively hurt (hit@1 fell from 0.71 to 0.48 until entity linking was restricted to named entities and the graph was demoted to a boost). It's kept for explainability, cross-document routing and the facts shown in the UI, not as a claimed accuracy win.
- **Context efficiency:** sending the top-5 clauses uses about **77% fewer prompt tokens** than stuffing the whole corpus (2,418 tokens, estimated at 4 chars/token). The saving grows with corpus size.
- End-to-end answers (retrieve, rerank, stream with `gpt-oss-120b` on Groq) take roughly 1-2 s; retrieval itself is ~150 ms.
- Ingesting the three samples with LLM graph extraction takes ~2.5 minutes on Groq's free tier, which is rate-limited (the pipeline throttles and retries). Without an API key, ingestion is near-instant and uses regex extraction only.

Graph-dependent numbers shift slightly between ingestions (e.g. hybrid + graph MRR 0.80 to 0.81) because the LLM extracts slightly different entities each time; the other rows are deterministic.

Caveat: 24 questions over 3 short documents is a smoke-test-sized benchmark. Differences of one question (~0.04) are noise. It exists to catch regressions and to ground design choices; it is not a leaderboard.

## Run locally

```bash
cd backend
python3 -m venv legal_doc_env && legal_doc_env/bin/python3 -m pip install -r requirements.txt
cp .env.example .env                       # add GROQ_API_KEY (optional; extractive mode without it) and a real SECRET_KEY
legal_doc_env/bin/uvicorn app.main:app --port 8002

cd ../frontend && npm install && npm run dev    # http://localhost:5200
```

Click **Load sample contracts**, then ask: *"If the vendor goes down for a day, what do we get back, and is that our only remedy?"*

Tests (offline: fake LLM, hash embedder, 24 tests including tenant isolation, crash recovery and the injection guard): `cd backend && legal_doc_env/bin/python3 -m pytest`

## Layout

```
backend/app/
  ingest/      parsers, clause chunker, extractor (regex + LLM), risk analysis, background pipeline
  auth.py      accounts, JWT, refresh, first-account adoption
  guard.py     prompt-injection detection and the untrusted-data rule
  observability.py  request IDs, JSON logs, metrics
  retrieval/   FAISS + BM25 + graph + RRF + reranker, with switchable modes
  qa.py        condense, grounded prompt, streaming, citation validation, token accounting
  evaluation.py  benchmark harness
samples/       3 synthetic contracts + eval_set.json
```

*Sample documents are fictional. Nothing here is legal advice.*
