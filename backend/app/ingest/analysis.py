"""Document-level intelligence: key facts and clause-risk flags. Deterministic and explainable."""
import re
from dataclasses import dataclass

from app.ingest.extractor import RX, norm

KIND_HINTS = [("nda", r"non-disclosure|confidentiality agreement"), ("msa", r"master services agreement|services agreement"),
              ("employment", r"employment agreement|offer of employment"), ("lease", r"lease agreement|tenancy"),
              ("sale", r"sale agreement|purchase agreement")]


def guess_kind(text: str) -> str:
    head = text[:600].lower()
    return next((k for k, rx in KIND_HINTS if re.search(rx, head)), "other")


@dataclass(frozen=True)
class RiskRule:
    topic: str
    pattern: re.Pattern
    severity: str   # high | medium | low | info
    why: str


def rr(topic, pat, sev, why):
    return RiskRule(topic, re.compile(pat, re.I), sev, why)


RISK_RULES = [
    rr("Auto-renewal", r"automatically renew|renew(?:s|ing)? automatically", "medium", "The contract rolls over unless you give notice in time. Diary the non-renewal deadline."),
    rr("Non-compete", r"shall not (?:work|engage|be employed)[^.]*(?:competitor|competing)|non-?compet", "medium", "Restricts future work. Enforceability varies by jurisdiction and scope."),
    rr("Non-solicitation", r"shall not solicit", "low", "Restricts hiring or approaching staff or customers after the relationship ends."),
    rr("Unilateral price increase", r"(?:may|can) increase fees", "medium", "The counterparty can raise prices during the term."),
    rr("Late-payment interest", r"late (?:amounts|payments?)[^.]*interest|accrue interest", "low", "Overdue amounts attract interest; check the rate is acceptable."),
    rr("Sole remedy limitation", r"sole (?:and exclusive )?remedy", "medium", "A named remedy (e.g. service credits) may be your only recourse."),
    rr("Exclusive jurisdiction", r"exclusive jurisdiction", "low", "Disputes must be brought in one named forum, which may be inconvenient or costly."),
    rr("Termination for convenience", r"terminate[^.]*for convenience|terminate[^.]*(?:thirty|sixty|ninety|fifteen|\d+)[^.]*notice", "info", "Either side can exit on notice. Check the notice period suits you."),
    rr("IP assignment", r"assigns? all rights|owned exclusively by the", "medium", "Work product ownership transfers entirely to the other party."),
    rr("Indemnity", r"shall indemnify", "medium", "You may have to cover the other side's third-party claim costs. Check scope and caps."),
    rr("Liability exclusion", r"not liable for (?:indirect|consequential)|exclude[sd]? .*liability", "info", "Consequential or indirect losses are excluded."),
    rr("Assignment restriction", r"may not assign|shall not assign|without the prior written consent", "info", "Rights cannot be transferred without consent."),
    rr("Probation termination", r"probation", "info", "Shorter notice applies during probation."),
]
CAP_PATTERN = re.compile(r"(?:aggregate|total) liability[^.]*(?:shall (?:not )?exceed|is limited to|capped)|shall (?:not )?exceed (?:USD|INR|GBP|EUR|\$)", re.I)


def analyze_risks(chunks: list[tuple[int, str, str]]) -> list[dict]:
    """chunks: (chunk_id, section, text) -> list of risk flags with the quoted clause."""
    risks: list[dict] = []
    for cid, section, text in chunks:
        for rule in RISK_RULES:
            m = rule.pattern.search(text)
            if m:
                s = max(0, text.rfind(".", 0, m.start()) + 1)
                e = text.find(".", m.end())
                quote = norm(text[s : (e + 1 if e != -1 else len(text))])[:320]
                risks.append({"topic": rule.topic, "severity": rule.severity, "why": rule.why, "section": section, "chunk_id": cid, "quote": quote})
    full = " ".join(t for _, _, t in chunks)
    if re.search(r"liab", full, re.I) and not CAP_PATTERN.search(full):
        risks.insert(0, {"topic": "No liability cap found", "severity": "high", "section": "(whole document)", "chunk_id": None,
                         "why": "Nothing in the text limits aggregate liability, so exposure may be unlimited.", "quote": ""})
    order = {"high": 0, "medium": 1, "low": 2, "info": 3}
    return sorted(risks, key=lambda r: order[r["severity"]])


def key_facts(chunks: list[tuple[int, str, str]]) -> dict:
    text = "\n".join(t for _, _, t in chunks)
    uniq = lambda xs: list(dict.fromkeys(norm(x) for x in xs if x))[:8]  # noqa: E731
    parties = uniq(m.group(0) for m in RX["PARTY"].finditer(text))
    parties = [re.sub(r"^(?:and|between|by|the)\s+", "", p, flags=re.I) for p in parties]
    juris = uniq(next(g for g in m.groups() if g) for m in RX["JURISDICTION"].finditer(text))
    return {
        "parties": list(dict.fromkeys(parties)),
        "dates": uniq(m.group(0) for m in RX["DATE"].finditer(text)),
        "amounts": uniq(m.group(0) for m in RX["AMOUNT"].finditer(text)),
        "durations": uniq(m.group(0) for m in RX["DURATION"].finditer(text)),
        "jurisdictions": juris,
    }
