from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from .. import db
from ..config import get_settings
from .bm25 import BM25
from .embeddings import get_embedder
from .textutil import clamp, content_terms, jaccard, term_presence, tokenize

log = logging.getLogger("docuchat.retrieval")

SUMMARY_INTENT = re.compile(
    r"\b(summar(?:y|ise|ize)|overview|what is this (?:document|paper|pdf|report) about|"
    r"main points|key points|tl;?dr|abstract)\b",
    re.IGNORECASE,
)
SECTION_REF = re.compile(r"\b(?:section|chapter|appendix)\s+([0-9]+(?:\.[0-9]+)*)", re.I)
TABLE_INTENT = re.compile(r"\b(table|row|column|percent|percentage|how many|how much|total|average|mean)\b", re.I)

INJECTION_PATTERNS = [
    re.compile(
        r"(?:ignore|disregard|forget|override)\s+(?:all\s+)?(?:of\s+)?(?:the\s+)?(?:previous|prior|above|earlier)\s+"
        r"(?:instructions?|prompts?|messages?|rules?)[^.!?]*[.!?]?",
        re.I,
    ),
    re.compile(
        r"(?:reveal|show|print|repeat|output|leak)\s+(?:me\s+)?(?:your\s+)?(?:system\s+)?(?:prompt|instructions|rules)"
        r"[^.!?]*[.!?]?",
        re.I,
    ),
    re.compile(r"you\s+are\s+now\s+(?:a|an|the)\s+[^.!?]*[.!?]?", re.I),
]


def sanitize_question(question: str) -> tuple[str, bool]:
    """Strip instruction-like clauses from a query.

    Document content and user questions are untrusted. Removing injection phrases
    before retrieval prevents them from dominating the query embedding and gives the
    actual question a fair chance, without silently hiding the injection from the UI.
    """
    cleaned = question
    for pattern in INJECTION_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = " ".join(cleaned.split())
    if len(cleaned) < 3:
        return question, False
    return cleaned, cleaned != question


@dataclass
class DocIndex:
    doc_id: str
    version: int
    chunks: list[dict]
    matrix: np.ndarray
    bm25: BM25
    doc: dict
    loaded_at: float = field(default_factory=time.time)


_cache: dict[str, DocIndex] = {}
_cache_lock = threading.Lock()


def invalidate(doc_id: str) -> None:
    with _cache_lock:
        _cache.pop(doc_id, None)


def _load_index(document: dict) -> DocIndex | None:
    doc_id = str(document["_id"])
    version = int(document.get("ingest_version") or 0)
    with _cache_lock:
        cached = _cache.get(doc_id)
        if cached and cached.version == version:
            return cached

    rows = list(
        db.chunks()
        .find({"document_id": document["_id"]}, {"embedding": 1, "text": 1, "embedding_text": 1, "page_number": 1,
                                                 "section_path": 1, "heading": 1, "index": 1,
                                                 "extraction_method": 1, "confidence": 1, "table": 1})
        .sort("index", 1)
    )
    if not rows:
        return None
    matrix = np.array([row.get("embedding") or [] for row in rows], dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] == 0:
        return None
    bm25 = BM25([row.get("embedding_text") or row.get("text", "") for row in rows])
    index = DocIndex(doc_id=doc_id, version=version, chunks=rows, matrix=matrix, bm25=bm25, doc=document)
    with _cache_lock:
        _cache[doc_id] = index
    return index


def _documents_in_scope(user_id: str, document_ids: list[str]) -> list[dict]:
    oids = [oid for oid in (db.oid(d) for d in document_ids) if oid is not None]
    if not oids:
        return []
    return list(
        db.documents().find(
            {
                "_id": {"$in": oids},
                "user_id": db.oid(user_id),
                "deleted": {"$ne": True},
                "status": "ready",
            }
        )
    )


def _rrf_contribution(rank: int, k: int) -> float:
    return 1.0 / (k + rank + 1)


def _rerank(query: str, candidates: list[dict]) -> None:
    settings = get_settings()
    if not candidates:
        return
    max_rrf = max(c["rrf_score"] for c in candidates) or 1.0
    vec_scores = [c["vector_score"] for c in candidates]
    vmin, vmax = min(vec_scores), max(vec_scores)
    span = (vmax - vmin) or 1.0
    section_match = SECTION_REF.search(query)
    quoted = re.findall(r"\"([^\"]{3,})\"", query)
    q_terms = content_terms(query)
    table_question = bool(TABLE_INTENT.search(query))
    lowered_query = " ".join(query.lower().split())

    for candidate in candidates:
        text_lower = candidate["text"].lower()
        coverage = candidate.get("coverage", 0.0)
        norm_rrf = candidate["rrf_score"] / max_rrf
        norm_vec = (candidate["vector_score"] - vmin) / span
        bonus = 0.0
        if section_match and section_match.group(1) in (candidate["text"] + " " + candidate["section_path"]):
            bonus += 0.08
        if quoted and any(phrase.lower() in text_lower for phrase in quoted):
            bonus += 0.08
        if lowered_query and lowered_query in text_lower:
            bonus += 0.04
        if table_question and candidate.get("chunk_kind") == "table":
            bonus += 0.05
        if q_terms and len(q_terms & set(tokenize(candidate["text"]))) == len(q_terms) and len(q_terms) >= 3:
            bonus += 0.03
        candidate["rerank_score"] = round(
            min(1.0, 0.55 * norm_rrf + 0.25 * coverage + 0.20 * norm_vec + bonus), 4
        )

    candidates.sort(key=lambda c: (-c["rerank_score"], -c["vector_score"]))


def _select_context(
    query: str,
    candidates: list[dict],
    doc_count: int,
    limit: int,
    token_budget: int,
) -> list[dict]:
    selected: list[dict] = []
    seen: list[set[str]] = []
    per_page: dict[tuple[str, int], int] = {}
    per_doc: dict[str, int] = {}
    tokens = 0

    for candidate in candidates:
        if len(selected) >= limit:
            break
        terms = set(tokenize(candidate["text"]))
        if any(jaccard(terms, other) > 0.82 for other in seen):
            continue
        page_key = (candidate["document_id"], candidate["page_number"])
        if per_page.get(page_key, 0) >= 2:
            continue
        if doc_count > 1 and len(selected) >= doc_count and per_doc.get(candidate["document_id"], 0) == 0:
            continue
        if tokens + candidate["token_estimate"] > token_budget and selected:
            continue
        selected.append(candidate)
        seen.append(terms)
        per_page[page_key] = per_page.get(page_key, 0) + 1
        per_doc[candidate["document_id"]] = per_doc.get(candidate["document_id"], 0) + 1
        tokens += candidate["token_estimate"]

    if not selected and candidates:
        selected = candidates[:1]
    return selected


def _summary_selection(indexes: list[DocIndex], limit: int, token_budget: int) -> list[dict]:
    """Spread selection across the document(s) instead of relying on query similarity."""
    selected: list[dict] = []
    tokens = 0
    per_doc = max(1, limit // max(len(indexes), 1))
    for index in indexes:
        rows = index.chunks
        if not rows:
            continue
        stride = max(1, len(rows) // per_doc)
        for position in range(0, len(rows), stride):
            if len(selected) >= limit:
                break
            row = rows[position]
            candidate = _candidate_dict(index, row, 0.0, 0.0, 0.0, 0.0, 0.0)
            candidate["rerank_score"] = round(1.0 - (position / max(len(rows), 1)), 4)
            if tokens + candidate["token_estimate"] > token_budget and selected:
                continue
            selected.append(candidate)
            tokens += candidate["token_estimate"]
            if len([c for c in selected if c["document_id"] == index.doc_id]) >= per_doc:
                break
    selected.sort(key=lambda c: (c["document_id"], c["page_number"], c["chunk_index"]))
    return selected[:limit]


def _candidate_dict(
    index: DocIndex,
    row: dict,
    vector_score: float,
    bm25_score: float,
    rrf: float,
    coverage: float,
    rank: float,
) -> dict:
    table = row.get("table") or {}
    return {
        "chunk_id": f"{index.doc_id}:{row['index']}",
        "document_id": index.doc_id,
        "document_title": index.doc.get("title") or "Untitled",
        "chunk_index": int(row["index"]),
        "page_number": int(row.get("page_number") or 1),
        "page_count": int(index.doc.get("page_count") or 1),
        "section_path": row.get("section_path") or "",
        "heading": row.get("heading") or "",
        "text": row.get("text") or "",
        "embedding_text": row.get("embedding_text") or "",
        "extraction_method": row.get("extraction_method") or "text",
        "confidence": float(row.get("confidence") or 0.8),
        "chunk_kind": "table" if row.get("extraction_method") == "table" else "text",
        "table": table or None,
        "vector_score": round(float(vector_score), 4),
        "bm25_score": round(float(bm25_score), 4),
        "rrf_score": round(float(rrf), 4),
        "coverage": round(float(coverage), 4),
        "rerank_score": round(float(rank), 4),
        "token_estimate": max(1, len(row.get("text") or "") // 4),
        "citation_label": None,
    }


def search(
    query: str,
    document_ids: list[str],
    user_id: str,
    top_k: int | None = None,
    rerank_top_n: int | None = None,
) -> dict:
    settings = get_settings()
    started = time.perf_counter()
    query = (query or "").strip()
    if not query:
        return {
            "query": query,
            "mode": "empty",
            "selected": [],
            "candidates": [],
            "confidence": 0.0,
            "sufficient": False,
            "diagnostics": {"reason": "empty_query"},
        }
    query, sanitized = sanitize_question(query)

    documents = _documents_in_scope(user_id, document_ids)
    indexes: list[DocIndex] = []
    for document in documents:
        index = _load_index(document)
        if index:
            indexes.append(index)

    if not indexes:
        return {
            "query": query,
            "mode": "hybrid",
            "selected": [],
            "candidates": [],
            "confidence": 0.0,
            "sufficient": False,
            "diagnostics": {"reason": "no_indexed_documents", "scope_size": len(document_ids)},
        }

    summary_intent = bool(SUMMARY_INTENT.search(query))
    top_k = top_k or settings.retrieval_top_k
    limit = rerank_top_n or settings.rerank_top_n

    if summary_intent:
        selected = _summary_selection(indexes, max(limit, 6), settings.max_context_tokens)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        return {
            "query": query,
            "mode": "summary",
            "selected": selected,
            "candidates": selected,
            "confidence": 0.72,
            "sufficient": True,
            "diagnostics": {
                "strategy": "coverage_spread",
                "documents": len(indexes),
                "elapsed_ms": elapsed,
                "component": "hybrid",
                "sanitized": sanitized,
            },
        }

    embedder = get_embedder()
    query_vector = embedder.embed_query(query)
    fused: dict[tuple[str, int], dict] = {}

    for index in indexes:
        vector_scores = index.matrix @ query_vector
        bm25_scores = index.bm25.scores(query)

        vector_order = np.argsort(-vector_scores)[:top_k]
        bm25_order = [int(i) for i in np.argsort(-np.asarray(bm25_scores))[:top_k] if bm25_scores[int(i)] > 0]

        for rank, row_index in enumerate(vector_order):
            key = (index.doc_id, int(row_index))
            entry = fused.setdefault(
                key,
                {
                    "index": index,
                    "row_index": int(row_index),
                    "vector": float(vector_scores[row_index]),
                    "bm25": 0.0,
                    "rrf": 0.0,
                    "coverage": 0.0,
                },
            )
            entry["rrf"] += settings.vector_weight * _rrf_contribution(rank, settings.rrf_k)

        for rank, row_index in enumerate(bm25_order):
            key = (index.doc_id, int(row_index))
            entry = fused.setdefault(
                key,
                {
                    "index": index,
                    "row_index": int(row_index),
                    "vector": float(vector_scores[row_index]),
                    "bm25": 0.0,
                    "rrf": 0.0,
                    "coverage": 0.0,
                },
            )
            entry["rrf"] += settings.bm25_weight * _rrf_contribution(rank, settings.rrf_k)
            entry["bm25"] = float(bm25_scores[row_index])
            entry["coverage"] = index.bm25.term_coverage(query, int(row_index))

    candidates: list[dict] = []
    for entry in fused.values():
        index: DocIndex = entry["index"]
        row = index.chunks[entry["row_index"]]
        candidates.append(
            _candidate_dict(
                index,
                row,
                entry["vector"],
                entry["bm25"],
                entry["rrf"],
                entry["coverage"],
                0.0,
            )
        )

    started_rerank = time.perf_counter()
    if settings.enable_rerank:
        _rerank(query, candidates)
    else:
        candidates.sort(key=lambda c: -c["rrf_score"])
        for candidate in candidates:
            candidate["rerank_score"] = candidate["rrf_score"]
    rerank_ms = round((time.perf_counter() - started_rerank) * 1000, 1)

    selected = _select_context(
        query,
        candidates,
        doc_count=len(indexes),
        limit=limit,
        token_budget=settings.max_context_tokens,
    )
    for position, candidate in enumerate(selected, start=1):
        candidate["citation_label"] = f"S{position}"

    top_vector = max((c["vector_score"] for c in candidates), default=0.0)
    if embedder.name == "hashing":
        semantic = clamp(top_vector * 1.7)
    elif embedder.name == "openai":
        semantic = clamp((top_vector - 0.2) / 0.6)
    else:
        semantic = clamp((top_vector - 0.28) / 0.55)
    coverage_top = max((c["coverage"] for c in selected), default=0.0)
    question_terms = content_terms(query)
    presence = term_presence(
        question_terms, [c["embedding_text"] for c in candidates[:8]]
    )
    reranks = sorted((c["rerank_score"] for c in candidates), reverse=True)
    margin = (reranks[0] - reranks[1]) if len(reranks) > 1 else reranks[0] if reranks else 0.0
    confidence = round(
        clamp(0.45 * semantic + 0.25 * coverage_top + 0.30 * presence + 0.05 * clamp(margin * 2.0)), 3
    )
    # A semantic match can rescue a paraphrase, but a topic whose key terms never
    # appear in the corpus should abstain even if a chunk scores moderately well.
    sufficient = bool(selected) and (presence >= 0.5 or semantic >= 0.78) and confidence >= settings.min_retrieval_confidence

    elapsed = round((time.perf_counter() - started) * 1000, 1)
    return {
        "query": query,
        "mode": "hybrid",
        "selected": selected,
        "candidates": candidates[: max(limit * 3, 10)],
        "confidence": confidence,
        "sufficient": sufficient,
        "diagnostics": {
            "strategy": "hybrid_rrf_rerank" if settings.enable_rerank else "hybrid_rrf",
            "documents": len(indexes),
            "candidates": len(candidates),
            "vector_weight": settings.vector_weight,
            "bm25_weight": settings.bm25_weight,
            "rrf_k": settings.rrf_k,
            "semantic": round(semantic, 3),
            "coverage_top": round(coverage_top, 3),
            "term_presence": round(presence, 3),
            "margin": round(margin, 3),
            "embedder": embedder.name,
            "sanitized": sanitized,
            "rerank_ms": rerank_ms,
            "elapsed_ms": elapsed,
        },
    }
