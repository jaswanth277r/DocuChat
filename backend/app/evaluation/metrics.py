from __future__ import annotations

import statistics


def recall_at_k(relevant: list[int], ranked: list[int], k: int = 5) -> float:
    if not relevant:
        return 1.0
    retrieved = set(ranked[:k])
    return len(retrieved & set(relevant)) / len(set(relevant))


def reciprocal_rank(relevant: list[int], ranked: list[int]) -> float:
    if not relevant:
        return 0.0
    relevant_set = set(relevant)
    for index, page in enumerate(ranked):
        if page in relevant_set:
            return 1.0 / (index + 1)
    return 0.0


def ndcg_at_k(relevant: list[int], ranked: list[int], k: int = 5) -> float:
    relevant_set = set(relevant)
    dcg = 0.0
    for index, page in enumerate(ranked[:k]):
        if page in relevant_set:
            dcg += 1.0 / __import__("math").log2(index + 2)
    ideal = sum(1.0 / __import__("math").log2(i + 2) for i in range(min(len(relevant_set), k)))
    return dcg / ideal if ideal else 0.0


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * p
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def aggregate(records: list[dict]) -> dict:
    answerable = [r for r in records if not r.get("expected_abstain")]
    unanswerable = [r for r in records if r.get("expected_abstain")]
    answerable_answered = [r for r in answerable if not r.get("abstained")]

    citation_total = sum(r["citations_total"] for r in records)
    citation_invalid = sum(r["citations_invalid"] for r in records)
    citation_supported = sum(r["citations_supported"] for r in records)

    latencies = [r["latency_ms"] for r in records]
    recalls = [r["recall_at_5"] for r in records]
    rrs = [r["rr"] for r in records]
    ndcgs = [r["ndcg_at_5"] for r in records]

    return {
        "questions": len(records),
        "answerable": len(answerable),
        "unanswerable": len(unanswerable),
        "recall_at_5": round(statistics.fmean(recalls), 3) if recalls else None,
        "mrr": round(statistics.fmean(rrs), 3) if rrs else None,
        "ndcg_at_5": round(statistics.fmean(ndcgs), 3) if ndcgs else None,
        "answer_accuracy": round(
            sum(1 for r in answerable_answered if r["answer_hit"]) / len(answerable), 3
        ) if answerable else None,
        "answer_hit_rate_answered": round(
            sum(1 for r in answerable_answered if r["answer_hit"]) / len(answerable_answered), 3
        ) if answerable_answered else None,
        "correct_abstention_rate": round(
            sum(1 for r in unanswerable if r.get("abstained")) / len(unanswerable), 3
        ) if unanswerable else None,
        "false_abstention_rate": round(
            sum(1 for r in answerable if r.get("abstained")) / len(answerable), 3
        ) if answerable else None,
        "citation_validity_rate": round(1 - citation_invalid / citation_total, 3) if citation_total else None,
        "citation_support_rate": round(citation_supported / citation_total, 3) if citation_total else None,
        "citations": citation_total,
        "invalid_citations": citation_invalid,
        "latency_p50_ms": round(percentile(latencies, 0.5) or 0, 1),
        "latency_p95_ms": round(percentile(latencies, 0.95) or 0, 1),
    }
