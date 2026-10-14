"""Entity + relation extraction for the knowledge graph.

Two tiers: deterministic regex extraction (always on, works offline) and an LLM pass that adds
semantic relations. Entities are typed so the graph explorer and retrieval can filter on them.
"""
import logging
import re

from pydantic import BaseModel, Field

from app.llm import LLM

log = logging.getLogger(__name__)

ENTITY_TYPES = ["PARTY", "DATE", "AMOUNT", "DURATION", "JURISDICTION", "TERM", "CLAUSE", "OBLIGATION", "PERSON"]

_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
RX = {
    "DATE": re.compile(rf"\b(?:{_MONTHS})\s+\d{{1,2}},\s+\d{{4}}\b"),
    "AMOUNT": re.compile(r"(?:USD|INR|GBP|EUR|Rs\.?|\$|£|€|₹)\s?[\d,]+(?:\.\d+)?|\b\d+(?:\.\d+)?%"),
    "DURATION": re.compile(r"\b(?:[A-Za-z]+(?:-[A-Za-z]+)?\s)?\(\d+\)\s+(?:business\s+)?(?:days?|weeks?|months?|years?|hours?)\b|\b\d+\s+(?:business\s+)?(?:days|weeks|months|years|hours)\b", re.I),
    "JURISDICTION": re.compile(r"\blaws of (?:the (?:State|Commonwealth) of )?([A-Z][A-Za-z]+(?: [A-Z][a-z]+)?)|\bcourts? (?:of|located in) ([A-Z][A-Za-z]+)|\barbitration in ([A-Z][A-Za-z]+)"),
    "TERM": re.compile(r"[\"“]([A-Z][A-Za-z ]{2,40})[\"”]"),
    "PARTY": re.compile(r"\b([A-Z][\w&.'-]*(?: [A-Z][\w&.'-]*){0,4}),? (?:Inc\.?|Ltd\.?|LLC|plc|Pvt\. Ltd\.|Corporation|Corp\.|LLP|GmbH|Limited)(?=[\s,.(]|$)"),
}
_PARTY_SUFFIX = re.compile(r"\b(?:Inc\.?|Ltd\.?|LLC|plc|Pvt\. Ltd\.|Corporation|Corp\.|LLP|GmbH|Limited)(?=[\s,.(]|$)")
_GENERIC_TERMS = {"Agreement", "Party", "Parties", "MSA", "SOW"}


class ExtractedEntity(BaseModel):
    name: str
    type: str


class ExtractedRelation(BaseModel):
    src: str
    label: str = Field(max_length=100)
    dst: str


class Extraction(BaseModel):
    entities: list[ExtractedEntity] = Field(default_factory=list)
    relations: list[ExtractedRelation] = Field(default_factory=list)


def norm(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().strip(".,;:\"'“”")).strip()


def entity_key(name: str, type_: str) -> str:
    n = re.sub(r"[^a-z0-9% ]", "", name.lower())
    n = re.sub(r"\b(inc|ltd|llc|plc|pvt|corp|corporation|limited|llp|the)\b", "", n)
    return f"{type_}:{re.sub(r'\s+', ' ', n).strip()}"


def regex_extract(text: str, section: str) -> Extraction:
    ents: dict[tuple[str, str], ExtractedEntity] = {}

    def add(name: str, type_: str):
        name = norm(name)
        if name and len(name) < 120:
            ents.setdefault((entity_key(name, type_), type_), ExtractedEntity(name=name, type=type_))

    for m in RX["PARTY"].finditer(text):
        full = m.group(0)
        add(re.sub(r"^(?:and|between|by|the)\s+", "", full, flags=re.I), "PARTY")
    for t in ("DATE", "AMOUNT", "DURATION"):
        for m in RX[t].finditer(text):
            add(m.group(0), t)
    for m in RX["JURISDICTION"].finditer(text):
        add(next(g for g in m.groups() if g), "JURISDICTION")
    for m in RX["TERM"].finditer(text):
        if m.group(1) not in _GENERIC_TERMS and not _PARTY_SUFFIX.search(m.group(1)):
            add(m.group(1), "TERM")
    clause = norm(re.sub(r"^(?:ARTICLE|Article|SECTION|Section)?\s*\d+[.\s\-]*", "", section)).title() or "Preamble"
    add(clause, "CLAUSE")
    # structural relations: every entity found in a clause is linked to that clause
    rels = [ExtractedRelation(src=clause, label="mentions", dst=e.name) for e in ents.values() if e.type != "CLAUSE"]
    return Extraction(entities=list(ents.values()), relations=rels)


SYSTEM = (
    "You extract a legal knowledge graph from contract text. Return entities and relations.\n"
    f"Entity types: {', '.join(ENTITY_TYPES)}.\n"
    "Relations are short verb phrases between two extracted entities, e.g. 'pays', 'terminates on notice of', "
    "'governed by', 'indemnifies', 'owns', 'employed by', 'restricted by'. Use the exact names from the text, "
    "extract only what the text states, and keep it compact (max ~12 relations per clause)."
)


async def llm_extract(llm: LLM, chunks: list[tuple[int, str, str]]) -> dict[int, Extraction]:
    """chunks: (chunk_id, section, text). One call per small batch to keep latency and tokens down."""
    result: dict[int, Extraction] = {}
    batch_size = 3
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        user = "\n\n".join(f"[CHUNK {cid}] ({sec})\n{text}" for cid, sec, text in batch)
        try:
            ex = await llm.structured(Extraction, SYSTEM + "\nExtract jointly for all chunks below.", user)
        except Exception as e:
            log.warning("LLM extraction failed for batch: %s", e)
            continue
        # relations aren't tagged per chunk by the model, so attach them to the chunk that mentions both ends
        for r in ex.relations:
            host = next((cid for cid, _, t in batch if r.src.lower() in t.lower() and r.dst.lower() in t.lower()), None) \
                or next((cid for cid, _, t in batch if r.src.lower() in t.lower() or r.dst.lower() in t.lower()), batch[0][0])
            result.setdefault(host, Extraction()).relations.append(r)
        for e in ex.entities:
            if e.type not in ENTITY_TYPES:
                continue
            host = next((cid for cid, _, t in batch if e.name.lower() in t.lower()), None)
            if host is not None:
                result.setdefault(host, Extraction()).entities.append(e)
    return result
