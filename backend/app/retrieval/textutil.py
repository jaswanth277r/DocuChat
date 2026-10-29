from __future__ import annotations

import re

STOPWORDS = set(
    """a an about above according after again against all am an and any are as at be because been before
    being below between both but by can could did do does doing down during each few for from further had
    has have having he her here hers herself him himself his how i if in into is it its itself just me more
    most my myself no nor not now of off on once only or other our ours ourselves out over own same say says
    she should so some such than that the their theirs them themselves then there these they this those
    through to too under until up very was we were what when where which while who whom why will with would
    you your yours yourself describe explain give mention mentioned tell document page chapter section figure
    table using used also within across per""".split()
)

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[.\-][a-z0-9]+)*")
SENTENCE_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


def stem(token: str) -> str:
    if token.isdigit() or any(ch.isdigit() for ch in token):
        return token
    for suffix in ("ations", "ation", "ingly", "ing", "ies", "ied", "est", "ed", "es", "s", "ly"):
        if len(token) - len(suffix) >= 4 and token.endswith(suffix):
            base = token[: -len(suffix)]
            if suffix in {"ies", "ied"}:
                base += "y"
            return base
    return token


def tokenize(text: str) -> list[str]:
    tokens = TOKEN_RE.findall(text.lower())
    return [stem(t) for t in tokens if t not in STOPWORDS and (len(t) > 1 or t.isdigit())]


def content_terms(text: str) -> set[str]:
    return set(tokenize(text))


def split_sentences(text: str) -> list[str]:
    text = " ".join((text or "").split())
    parts = SENTENCE_RE.split(text)
    return [p.strip() for p in parts if len(p.strip()) > 3]


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def term_presence(terms: set[str], texts: list[str]) -> float:
    if not terms:
        return 0.0
    vocab: set[str] = set()
    for text in texts:
        vocab.update(tokenize(text))
    return len(terms & vocab) / len(terms)
