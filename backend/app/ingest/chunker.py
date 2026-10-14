"""Clause-aware chunking.

Legal text has structure (numbered clauses, ARTICLE/Section headings). Splitting on those
boundaries keeps each clause intact, which matters far more for retrieval quality than
fixed-size windows. Oversized clauses are split at sentence boundaries with overlap.
"""
import re
from dataclasses import dataclass

from app.core.config import get_settings

_HEADING = re.compile(
    r"^\s*(?:(?:ARTICLE|Article|SECTION|Section|CLAUSE|Clause)\s+[\dIVXLC]+[.:\-\s]*.*"
    r"|\d{1,2}\.\s+[A-Z][A-Z &,\-/]{3,}$"   # "1. DEFINITIONS"
    r"|\d{1,2}\.\d{1,2}\s+.*)$"              # "4.2 Either Party may..."
)
_TOP_HEADING = re.compile(r"^\s*(?:(?:ARTICLE|Article|SECTION|Section|CLAUSE|Clause)\s+[\dIVXLC]+.*|\d{1,2}\.\s+[A-Z][A-Z &,\-/]{3,})$")
_SENT = re.compile(r"(?<=[.;])\s+(?=[A-Z(\"])")


@dataclass
class ChunkDraft:
    text: str
    section: str
    page: int


def _split_long(text: str, target: int, overlap: int) -> list[str]:
    if len(text) <= target:
        return [text]
    sentences = _SENT.split(text)
    out, cur = [], ""
    for s in sentences:
        if cur and len(cur) + len(s) + 1 > target:
            out.append(cur.strip())
            cur = cur[-overlap:] + " " + s if overlap else s
        else:
            cur = f"{cur} {s}".strip()
    if cur.strip():
        out.append(cur.strip())
    return out


def chunk_pages(pages: list[tuple[int, str]]) -> list[ChunkDraft]:
    s = get_settings()
    # 1. walk lines, grouping into clause blocks that carry their parent section heading
    blocks: list[tuple[str, int, list[str]]] = []  # (section, page, lines)
    section = "Preamble"
    for page, text in pages:
        for line in text.splitlines():
            if not line.strip():
                continue
            if _TOP_HEADING.match(line):
                section = line.strip()[:120]
                blocks.append((section, page, [line.strip()]))
            elif _HEADING.match(line) and re.match(r"^\s*\d{1,2}\.\d{1,2}\s", line):
                blocks.append((section, page, [line.strip()]))   # a numbered sub-clause starts a new block
            else:
                if blocks and blocks[-1][0] == section:
                    blocks[-1][2].append(line.strip())
                else:
                    blocks.append((section, page, [line.strip()]))
    # 2. merge tiny neighbours (same section) so chunks aren't a handful of words, split huge ones
    drafts: list[ChunkDraft] = []
    buf, buf_sec, buf_page = "", "", 1
    for sec, page, lines in blocks:
        body = " ".join(lines)
        if buf and (sec != buf_sec or len(buf) + len(body) > s.chunk_target_chars):
            drafts.append(ChunkDraft(buf.strip(), buf_sec, buf_page))
            buf = ""
        if not buf:
            buf_sec, buf_page = sec, page
        buf = f"{buf}\n{body}".strip() if buf else body
        if len(buf) > s.chunk_target_chars * 1.5:
            parts = _split_long(buf, s.chunk_target_chars, s.chunk_overlap_chars)
            drafts.extend(ChunkDraft(p, buf_sec, buf_page) for p in parts[:-1])
            buf = parts[-1]
    if buf.strip():
        drafts.append(ChunkDraft(buf.strip(), buf_sec, buf_page))
    return [d for d in drafts if len(d.text) > 20]
