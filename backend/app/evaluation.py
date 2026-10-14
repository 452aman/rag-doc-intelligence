"""Retrieval + efficiency benchmark over the bundled sample contracts.

Each question has gold keywords; a retrieved chunk is a hit when it contains all of them. We run every
retrieval mode on the same questions so the contribution of each stage (BM25, fusion, graph, reranker)
is measured instead of assumed.
"""
import json
import time
from pathlib import Path

from app.db import est_tokens
from app.qa import build_context
from app.retrieval.index import MODES, index

SAMPLES = next((p for p in (Path(__file__).resolve().parents[2] / "samples", Path("/samples")) if p.exists()), Path("samples"))


def load_set() -> list[dict]:
    return json.loads((SAMPLES / "eval_set.json").read_text())


def run_retrieval_eval(k: int = 5) -> dict:
    questions = load_set()
    doc_for = {}
    for h in index.chunks.values():
        for q in questions:
            if q["doc"] in h.doc_name.lower():
                doc_for[q["doc"]] = h.doc_id
    corpus_tokens = sum(est_tokens(h.text) for h in index.chunks.values())
    results = {}
    for mode in MODES:
        ranks, lat, ctx_tokens = [], [], []
        for q in questions:
            t0 = time.perf_counter()
            res = index.search(q["q"], k=10, mode=mode)  # global search: documents are NOT pre-selected
            lat.append((time.perf_counter() - t0) * 1000)
            rank = next((i for i, h in enumerate(res.hits, 1) if all(g in h.text.lower() for g in q["gold"])), None)
            ranks.append(rank)
            top = index.search(q["q"], k=k, mode=mode) if mode != "full" else res
            top.hits = top.hits[:k]
            ctx_tokens.append(est_tokens(build_context(top)))
        n = len(questions)
        results[mode] = {
            "hit@1": round(sum(1 for r in ranks if r == 1) / n, 3),
            "hit@3": round(sum(1 for r in ranks if r and r <= 3) / n, 3),
            "hit@5": round(sum(1 for r in ranks if r and r <= 5) / n, 3),
            "mrr": round(sum(1 / r for r in ranks if r) / n, 3),
            "avg_latency_ms": round(sum(lat) / n, 1),
            "avg_context_tokens": round(sum(ctx_tokens) / n),
            "failed": [q["q"] for q, r in zip(questions, ranks) if r is None],
        }
    avg_ctx = results["full"]["avg_context_tokens"]
    return {"questions": len(questions), "k": k, "corpus_tokens": corpus_tokens, "modes": results,
            "token_reduction_vs_full_corpus": round(1 - avg_ctx / corpus_tokens, 3) if corpus_tokens else None}
