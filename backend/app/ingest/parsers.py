"""Turn uploaded bytes into (page_number, text) pairs."""
import io
import re

from docx import Document as DocxDocument
from pypdf import PdfReader


class ParseError(Exception):
    pass


def parse(name: str, data: bytes) -> list[tuple[int, str]]:
    lower = name.lower()
    try:
        if lower.endswith(".pdf"):
            reader = PdfReader(io.BytesIO(data))
            pages = [(i + 1, (p.extract_text() or "")) for i, p in enumerate(reader.pages)]
        elif lower.endswith(".docx"):
            doc = DocxDocument(io.BytesIO(data))
            pages = [(1, "\n".join(p.text for p in doc.paragraphs))]
        elif lower.endswith((".txt", ".md")):
            pages = [(1, data.decode("utf-8", errors="replace"))]
        else:
            raise ParseError("Unsupported file type. Upload PDF, DOCX, TXT or MD.")
    except ParseError:
        raise
    except Exception as e:
        raise ParseError(f"Could not read file: {e}") from e
    pages = [(n, re.sub(r"[ \t]+\n", "\n", t).strip()) for n, t in pages]
    if not any(t for _, t in pages):
        raise ParseError("No extractable text (scanned PDF? OCR is not enabled).")
    return pages
