from __future__ import annotations

import re
from collections import OrderedDict

from ..retrieval.textutil import content_terms, jaccard, split_sentences, tokenize

ABSTAIN_TEXT = (
    "I couldn't find enough information in the uploaded document to answer that reliably.\n\n"
    "Try a narrower question, or confirm that the relevant document is selected."
)

TABLE_HINT = re.compile(
    r"\b(table|row|column|which model|how many|how much|highest|lowest|total|average|mean)\b",
    re.IGNORECASE,
)


def _quality_sentence(sentence: str) -> bool:
    text = sentence.strip()
    if len(text) < 45 or len(text) > 600:
        return False
    lower = text.lower()
    if lower.startswith(("figure ", "table ", "references", "doi", "http", "www.")):
        return False
    if text.count("|") > 2:
        return False
    letters = sum(ch.isalpha() for ch in text)
    if letters / max(len(text), 1) < 0.5:
        return False
    return True


def _table_lines(passage: dict, limit: int = 5) -> list[str]:
    table = passage.get("table") or {}
    headers = table.get("headers") or []
    rows = table.get("rows") or []
    if not headers or not rows:
        return []
    label = passage.get("citation_label")
    marker = f" [{label}]" if label else ""
    lines = []
    for row in rows[:limit]:
        row_label = row[0].strip() if row and row[0].strip() else "Row"
        pairs = []
        for index, (header, value) in enumerate(zip(headers, row)):
            if index == 0 or not value or not value.strip():
                continue
            pairs.append(f"{header.strip()} = {value.strip()}")
        if pairs:
            lines.append(f"- {row_label}: " + ", ".join(pairs) + marker)
    if len(rows) > limit:
        lines.append(f"- Table on page {passage['page_number']} continues with {len(rows) - limit} more rows.{marker}")
    return lines


def _pick_sentences(passages: list[dict], query_terms: set[str], per_passage: int = 2) -> list[dict]:
    picked: list[dict] = []
    for passage in passages:
        if passage.get("chunk_kind") == "table":
            continue
        candidates = []
        for position, sentence in enumerate(split_sentences(passage.get("text") or "")):
            if not _quality_sentence(sentence):
                continue
            terms = set(tokenize(sentence))
            overlap = len(query_terms & terms) / len(query_terms) if query_terms else 0.0
            passage_score = float(passage.get("rerank_score") or 0.0)
            position_bonus = 0.08 / (1 + position) if position < 3 else 0.0
            score = 0.55 * passage_score + 0.37 * overlap + position_bonus
            if overlap == 0:
                continue
            candidates.append(
                {
                    "sentence": sentence,
                    "label": passage.get("citation_label"),
                    "passage": passage,
                    "terms": terms,
                    "score": round(score, 4),
                }
            )
        candidates.sort(key=lambda item: -item["score"])
        picked.extend(candidates[:per_passage])

    chosen: list[dict] = []
    for candidate in picked:
        if any(jaccard(candidate["terms"], other["terms"]) > 0.8 for other in chosen):
            continue
        chosen.append(candidate)
    return chosen


def _focus_passages(selected: list[dict], per_document: int = 2) -> list[dict]:
    focus: list[dict] = []
    counts: dict[str, int] = {}
    for passage in selected:
        doc_id = passage["document_id"]
        if counts.get(doc_id, 0) >= per_document:
            continue
        counts[doc_id] = counts.get(doc_id, 0) + 1
        focus.append(passage)
    return focus


def _render(chosen: list[dict], table_lines: list[str], table_first: bool) -> str:
    doc_ids = {item["passage"]["document_id"] for item in chosen}
    blocks: list[str] = []

    if len(doc_ids) > 1:
        grouped: OrderedDict[str, list[dict]] = OrderedDict()
        for candidate in chosen:
            grouped.setdefault(candidate["passage"]["document_title"], []).append(candidate)
        for title, group in grouped.items():
            lines = [f"**{title}**"]
            lines.extend(f"- {candidate['sentence']} [{candidate['label']}]" for candidate in group)
            blocks.append("\n".join(lines))
    elif chosen:
        blocks.append("\n".join(f"- {candidate['sentence']} [{candidate['label']}]" for candidate in chosen))

    table_block = "\n".join(table_lines)
    if table_block:
        blocks.insert(0, table_block) if table_first else blocks.append(table_block)
    return "\n\n".join(block for block in blocks if block).strip()


def extractive_answer(question: str, retrieval: dict) -> tuple[str, bool]:
    selected = retrieval.get("selected") or []
    if not retrieval.get("sufficient") or not selected:
        return ABSTAIN_TEXT, True

    query = retrieval.get("query") or question
    if retrieval.get("mode") == "summary":
        return _summary_answer(selected, query), False

    query_terms = content_terms(query)
    focus = _focus_passages(selected, per_document=2)
    multi_doc = len({passage["document_id"] for passage in focus}) > 1
    chosen = _pick_sentences(focus, query_terms, per_passage=2)
    chosen.sort(key=lambda item: -item["score"])

    best_score = chosen[0]["score"] if chosen else 0.0
    per_doc: dict[str, int] = {}
    capped: list[dict] = []
    for candidate in chosen:
        if candidate["score"] < best_score * 0.55:
            continue
        doc_id = candidate["passage"]["document_id"]
        limit = 3 if multi_doc else 4
        if per_doc.get(doc_id, 0) >= limit:
            continue
        per_doc[doc_id] = per_doc.get(doc_id, 0) + 1
        capped.append(candidate)

    table_passages = [
        passage
        for passage in selected[:3]
        if passage.get("chunk_kind") == "table" and TABLE_HINT.search(query)
    ]
    table_lines: list[str] = []
    for passage in table_passages[:2]:
        table_lines.extend(_table_lines(passage))

    table_first = bool(table_lines) and bool(re.search(r"\btable\b", query, re.IGNORECASE))
    if table_lines:
        return "\n".join(table_lines), False
    body = _render(capped, table_lines, table_first)
    if not body:
        return ABSTAIN_TEXT, True
    return body, False


def _summary_answer(selected: list[dict], query: str) -> str:
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for passage in selected:
        section = passage.get("section_path") or passage.get("heading") or "Document"
        grouped.setdefault(section, []).append(passage)

    blocks: list[str] = []
    for section, passages in list(grouped.items())[:6]:
        lines = [f"**{section}**"]
        for passage in passages[:1]:
            sentences = [s for s in split_sentences(passage.get("text") or "") if _quality_sentence(s)]
            if not sentences:
                continue
            lines.append(f"- {sentences[0]} [{passage.get('citation_label')}]")
        if len(lines) > 1:
            blocks.append("\n".join(lines))

    table_lines: list[str] = []
    for passage in selected:
        if passage.get("chunk_kind") == "table":
            table_lines.extend(_table_lines(passage, limit=4))
    if table_lines:
        blocks.append("\n".join(table_lines))
    return "\n\n".join(blocks).strip() or ABSTAIN_TEXT
