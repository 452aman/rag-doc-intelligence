"""Hybrid retrieval over all ready documents.

   dense (FAISS) ─┐
   lexical (BM25) ┼─► reciprocal-rank fusion ─► cross-encoder rerank ─► top-k
   graph expansion┘
        ▲
   entity linking: query → knowledge-graph entities → their chunks + 1-hop neighbours' chunks

Every stage can be switched off (`mode`), which is how the evaluation harness measures what each
one contributes.
"""
import logging
import re
import threading
from dataclasses import dataclass, field

import faiss
import networkx as nx
import numpy as np
from rank_bm25 import BM25Okapi
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db import Chunk, Document, Entity, Mention, Relation
from app.embeddings import get_embedder, normalize

log = logging.getLogger(__name__)
MODES = ("dense", "bm25", "hybrid", "hybrid+graph", "full")  # full = hybrid + graph + rerank
_STOP = {"the", "a", "an", "of", "to", "and", "or", "in", "on", "for", "is", "are", "be", "by", "what", "which", "who", "how",
         "does", "do", "any", "this", "that", "with", "under", "from", "can", "may", "shall", "must", "if", "there", "it", "its", "as", "at", "about"}
RRF_K = 60
WEIGHT = {"dense": 1.0, "bm25": 1.0, "graph": 0.5}  # the graph is a supporting signal, not a primary retriever


_SUFFIXES = ("ations", "ation", "ments", "ment", "ings", "ing", "ions", "ion", "ness", "ies", "ed", "es", "al", "ly", "e", "s")
# Words so common in contracts that linking a query to them would drag in half the corpus.
GENERIC = {"agreement", "party", "parties", "service", "services", "provider", "customer", "recipient", "discloser", "employer",
           "employee", "section", "article", "clause", "contract", "document", "term", "terms", "general", "preamble", "definitions",
           "either", "third", "other", "each", "both", "another", "counterparty", "company", "person", "licensor", "licensee"}


def stem(w: str) -> str:
    """Light suffix stripping so renew/renewing/renewal and terminate/termination share a stem."""
    for suf in _SUFFIXES:
        if w.endswith(suf) and len(w) - len(suf) >= 4:
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    return [stem(w) for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _STOP]


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    doc_name: str
    section: str
    page: int
    text: str
    score: float = 0.0
    via: list[str] = field(default_factory=list)


@dataclass
class SearchResult:
    hits: list[Hit]
    entities: list[str]           # graph entities the query was linked to
    graph_facts: list[str]        # compact relation lines for the prompt
    candidates: int = 0


class RetrievalIndex:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.chunks: dict[int, Hit] = {}
        self.order: list[int] = []
        self.faiss: faiss.IndexFlatIP | None = None
        self.bm25: BM25Okapi | None = None
        self.graph = nx.Graph()
        self.entity_by_id: dict[int, dict] = {}
        self.entity_chunks: dict[int, set[int]] = {}
        self.ent_index: faiss.IndexFlatIP | None = None
        self.ent_ids: list[int] = []
        self._reranker = None

    # ---------------------------------------------------------------- build
    def rebuild(self, db: Session) -> None:
        with self._lock:
            rows = db.execute(
                select(Chunk, Document.name).join(Document, Document.id == Chunk.doc_id).where(Document.status == "ready").order_by(Chunk.id)
            ).all()
            self.chunks = {c.id: Hit(c.id, c.doc_id, name, c.section, c.page, c.text) for c, name in rows}
            self.order = list(self.chunks)
            if rows:
                dim = len(np.frombuffer(rows[0][0].embedding, dtype="float32"))
                mat = np.vstack([np.frombuffer(c.embedding, dtype="float32") for c, _ in rows])
                self.faiss = faiss.IndexFlatIP(dim)
                self.faiss.add(normalize(mat))
                self.bm25 = BM25Okapi([tokenize(c.text + " " + c.section) for c, _ in rows])
            else:
                self.faiss, self.bm25 = None, None
            self._build_graph(db)

    def _build_graph(self, db: Session) -> None:
        g = nx.Graph()
        self.entity_by_id, self.entity_chunks = {}, {}
        valid = set(self.chunks)
        for e in db.scalars(select(Entity)):
            self.entity_by_id[e.id] = {"id": e.id, "name": e.name, "type": e.type, "description": e.description}
        for m in db.scalars(select(Mention)):
            if m.chunk_id in valid:
                self.entity_chunks.setdefault(m.entity_id, set()).add(m.chunk_id)
        live = {eid for eid, cs in self.entity_chunks.items() if cs}
        for eid in live:
            g.add_node(eid, **self.entity_by_id[eid])
        for r in db.scalars(select(Relation)):
            if r.chunk_id in valid and r.src_id in live and r.dst_id in live:
                if g.has_edge(r.src_id, r.dst_id):
                    g[r.src_id][r.dst_id]["labels"].add(r.label)
                    g[r.src_id][r.dst_id]["chunks"].add(r.chunk_id)
                else:
                    g.add_edge(r.src_id, r.dst_id, labels={r.label}, chunks={r.chunk_id})
        self.graph = g
        self.ent_ids = sorted(live)
        if self.ent_ids:
            vecs = normalize(get_embedder().embed([self.entity_by_id[i]["name"] for i in self.ent_ids]))
            self.ent_index = faiss.IndexFlatIP(vecs.shape[1])
            self.ent_index.add(vecs)
        else:
            self.ent_index = None

    # --------------------------------------------------------------- search
    def _dense(self, query: str, n: int, allowed: set[int] | None) -> list[int]:
        if not self.faiss:
            return []
        q = normalize(get_embedder().embed([query]))
        _, idx = self.faiss.search(q, min(len(self.order), n * 3 if allowed else n))
        ids = [self.order[i] for i in idx[0] if i >= 0]
        return [i for i in ids if not allowed or self.chunks[i].doc_id in allowed][:n]

    def _lexical(self, query: str, n: int, allowed: set[int] | None) -> list[int]:
        if not self.bm25:
            return []
        scores = self.bm25.get_scores(tokenize(query))
        ranked = np.argsort(-scores)
        out = [self.order[i] for i in ranked if scores[i] > 0]
        return [i for i in out if not allowed or self.chunks[i].doc_id in allowed][:n]

    def link_entities(self, query: str, allowed: set[int] | None = None) -> list[int]:
        """Link a query to *named* graph entities only.

        Parties, people and jurisdictions match by name or strong token overlap; defined terms need an
        exact multi-word match. Generic concept nodes ("compensation", "third party") are never linked,
        which the benchmark showed adds noise rather than signal.
        """
        q_toks = set(tokenize(query))
        q_low = query.lower()
        generic = {stem(g) for g in GENERIC}
        linked: dict[int, float] = {}
        for eid in self.graph.nodes:
            ent = self.entity_by_id[eid]
            if allowed and not any(self.chunks[c].doc_id in allowed for c in self.entity_chunks.get(eid, ())):
                continue
            name = ent["name"].lower()
            if ent["type"] in ("PARTY", "PERSON", "JURISDICTION"):
                e_toks = {t for t in tokenize(name) if t not in generic}
                if not e_toks:
                    continue  # "the Employee", "either party", "third party": role words, not named entities
                if len(name) >= 4 and name in q_low:
                    linked[eid] = 1.0
                    continue
                overlap = len(e_toks & q_toks) / len(e_toks)
                if overlap >= 0.6:
                    linked[eid] = 0.5 + 0.4 * overlap
            elif ent["type"] == "TERM" and " " in name and name in q_low:
                linked[eid] = 0.9
        return sorted(linked, key=lambda e: -linked[e])[:6]

    def _graph_candidates(self, entity_ids: list[int], allowed: set[int] | None) -> list[int]:
        scored: dict[int, float] = {}
        limit = max(3, int(0.15 * len(self.chunks)))  # an entity in >15% of chunks says little about relevance
        entity_ids = [e for e in entity_ids if len(self.entity_chunks.get(e, ())) <= limit]
        for rank, eid in enumerate(entity_ids):
            for cid in self.entity_chunks.get(eid, ()):
                scored[cid] = max(scored.get(cid, 0), 1.0 - 0.05 * rank)
            for nb in self.graph.neighbors(eid):
                if self.entity_by_id[nb]["type"] == "CLAUSE" or len(self.entity_chunks.get(nb, ())) > limit:
                    continue  # hopping through a clause node would pull in unrelated entities
                for cid in self.entity_chunks.get(nb, ()):
                    scored[cid] = max(scored.get(cid, 0), 0.5 - 0.05 * rank)
        ids = sorted(scored, key=lambda c: -scored[c])
        return [c for c in ids if not allowed or self.chunks[c].doc_id in allowed][:8]

    def _graph_boost(self, entity_ids: list[int], rrf: dict[int, float], via: dict[int, list[str]]) -> None:
        """Re-weight already-retrieved chunks using the knowledge graph (never adds new candidates).

        - a chunk that directly mentions a linked entity gets a strong boost;
        - a chunk from a document that mentions a linked PARTY/PERSON gets a mild boost, which routes
          "what does Globex have to do" style questions to the right contract.
        """
        limit = max(3, int(0.15 * len(self.chunks)))
        direct: set[int] = set()
        routed_docs: set[int] = set()
        for eid in entity_ids:
            cs = self.entity_chunks.get(eid, set())
            if len(cs) > limit:
                continue  # too common to be discriminative
            direct |= cs
            if self.entity_by_id[eid]["type"] in ("PARTY", "PERSON"):
                routed_docs |= {self.chunks[c].doc_id for c in cs}
        for cid in rrf:
            if cid in direct:
                rrf[cid] *= 1.35
                via.setdefault(cid, []).append("graph")
            elif self.chunks[cid].doc_id in routed_docs:
                rrf[cid] *= 1.12
                via.setdefault(cid, []).append("graph")

    def _facts(self, entity_ids: list[int], limit: int = 8) -> list[str]:
        facts: list[str] = []
        for eid in entity_ids:
            for nb in self.graph.neighbors(eid):
                for label in sorted(self.graph[eid][nb]["labels"]):
                    if label == "mentions":
                        continue
                    facts.append(f"{self.entity_by_id[eid]['name']} -[{label}]-> {self.entity_by_id[nb]['name']}")
        return list(dict.fromkeys(facts))[:limit]

    def _rerank(self, query: str, ids: list[int]) -> list[tuple[int, float]]:
        if get_settings().reranker != "cross-encoder" or len(ids) < 2:
            return [(i, 0.0) for i in ids]
        if self._reranker is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._reranker = TextCrossEncoder("Xenova/ms-marco-MiniLM-L-6-v2")
        scores = list(self._reranker.rerank(query, [self.chunks[i].text for i in ids]))
        return sorted(zip(ids, map(float, scores)), key=lambda x: -x[1])

    def search(self, query: str, k: int = 5, mode: str = "full", doc_ids: list[int] | None = None) -> SearchResult:
        with self._lock:
            if not self.chunks:
                return SearchResult([], [], [])
            allowed = set(doc_ids) if doc_ids else None
            lists: dict[str, list[int]] = {}
            entity_ids: list[int] = []
            if mode in ("dense", "hybrid", "hybrid+graph", "full"):
                lists["dense"] = self._dense(query, 20, allowed)
            if mode in ("bm25", "hybrid", "hybrid+graph", "full"):
                lists["bm25"] = self._lexical(query, 20, allowed)
            if mode in ("hybrid+graph", "full"):
                entity_ids = self.link_entities(query, allowed)
            rrf: dict[int, float] = {}
            via: dict[int, list[str]] = {}
            for name, ids in lists.items():
                for rank, cid in enumerate(ids):
                    rrf[cid] = rrf.get(cid, 0) + WEIGHT[name] / (RRF_K + rank + 1)
                    via.setdefault(cid, []).append(name)
            if entity_ids:
                self._graph_boost(entity_ids, rrf, via)
            fused = sorted(rrf, key=lambda c: -rrf[c])
            if mode == "full":
                final = self._rerank(query, fused[:12])
            else:
                final = [(c, rrf[c]) for c in fused]
            hits = []
            for cid, score in final[:k]:
                h = self.chunks[cid]
                hits.append(Hit(h.chunk_id, h.doc_id, h.doc_name, h.section, h.page, h.text, round(score, 4), via.get(cid, [])))
            return SearchResult(hits, [self.entity_by_id[e]["name"] for e in entity_ids], self._facts(entity_ids) if mode in ("hybrid+graph", "full") else [],
                                candidates=len(fused))

    def graph_json(self, doc_id: int | None = None, max_nodes: int = 120) -> dict:
        """Entities + relations for the explorer. Document hub nodes (negative ids) connect each document
        to its named entities, so an entity shared between contracts visibly bridges them."""
        with self._lock:
            nodes, keep = [], set()
            deg = dict(self.graph.degree())
            for eid in sorted(self.graph.nodes, key=lambda e: -deg.get(e, 0)):
                chunks = self.entity_chunks.get(eid, set())
                if doc_id is not None and not any(self.chunks[c].doc_id == doc_id for c in chunks):
                    continue
                if len(keep) >= max_nodes:
                    break
                keep.add(eid)
                e = self.entity_by_id[eid]
                nodes.append({"id": eid, "name": e["name"], "type": e["type"], "degree": deg.get(eid, 0),
                              "docs": sorted({self.chunks[c].doc_id for c in chunks})})
            links = [{"source": a, "target": b, "label": ", ".join(sorted(d["labels"]))[:80]}
                     for a, b, d in self.graph.edges(data=True) if a in keep and b in keep]
            hubs: dict[int, str] = {}
            for n in nodes:
                if n["type"] in ("PARTY", "PERSON", "JURISDICTION", "DATE", "AMOUNT"):
                    for d in n["docs"]:
                        if doc_id is None or d == doc_id:
                            hubs[d] = next(h.doc_name for h in self.chunks.values() if h.doc_id == d)
                            links.append({"source": -d, "target": n["id"], "label": "in"})
            linked = {l["source"] for l in links} | {l["target"] for l in links}
            nodes = [n for n in nodes if n["id"] in linked]  # orphan entities only add clutter to the explorer
            for d, name in hubs.items():
                nodes.append({"id": -d, "name": name.rsplit(".", 1)[0].replace("_", " "), "type": "DOCUMENT", "degree": 10, "docs": [d]})
            return {"nodes": nodes, "links": links}


index = RetrievalIndex()
