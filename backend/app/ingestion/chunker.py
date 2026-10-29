from __future__ import annotations

import re

TARGET_CHARS = 900
MIN_CHARS = 180
MAX_CHARS = 1600
OVERLAP_CHARS = 120


def _sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", text)
    return [p.strip() for p in parts if p.strip()]


def _merge_paragraphs(paragraphs: list[str]) -> list[str]:
    """PDF layout blocks split sentences mid-line; rejoin obvious continuations."""
    merged: list[str] = []
    for paragraph in paragraphs:
        text = paragraph.strip()
        if not text:
            continue
        if merged and not merged[-1].endswith((".", "!", "?", ":", ";", "|")) and text[:1].islower():
            merged[-1] = f"{merged[-1].rstrip()} {text}"
        else:
            merged.append(text)
    return merged


def _pack(paragraphs: list[str], target: int = TARGET_CHARS) -> list[str]:
    """Pack paragraphs into chunks, splitting oversized paragraphs on sentence boundaries."""
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
        if len(candidate) <= target or not current:
            if len(candidate) > MAX_CHARS:
                chunks.extend(_split_oversized(candidate, target))
                current = ""
            else:
                current = candidate
            continue
        chunks.append(current)
        current = paragraph
        if len(current) > MAX_CHARS:
            chunks.extend(_split_oversized(current, target))
            current = ""
    if current:
        if chunks and len(current) < MIN_CHARS and len(chunks[-1]) + len(current) <= MAX_CHARS:
            chunks[-1] = f"{chunks[-1]}\n\n{current}"
        else:
            chunks.append(current)
    return [c.strip() for c in chunks if c.strip()]


def _split_oversized(text: str, target: int) -> list[str]:
    sentences = _sentence_split(text) or [text]
    out: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= target:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                out.append(current)
            current = sentence
    if current:
        out.append(current)
    return out


def chunk_document(parsed: dict) -> list[dict]:
    """Structure-aware chunking.

    Chunks never cross page boundaries so that every citation maps to exactly one
    original page. Section metadata is carried by each chunk, and headings are
    prepended to the embedded text for retrieval context.
    """
    chunks: list[dict] = []
    index = 0
    for page in parsed["pages"]:
        blocks = page.get("blocks", [])
        if not blocks:
            continue

        # Group consecutive blocks by section so heading changes start new chunks.
        groups: list[tuple[str, list[dict]]] = []
        for block in blocks:
            section = block.get("section_path") or ""
            if groups and groups[-1][0] == section and block.get("kind") != "table":
                groups[-1][1].append(block)
            else:
                groups.append((section, [block]))

        for section, section_blocks in groups:
            paragraphs = _merge_paragraphs(
                [b["text"] for b in section_blocks if b.get("kind") == "paragraph"]
            )
            tables = [b for b in section_blocks if b.get("kind") == "table"]

            packed: list[tuple[str, dict]] = []
            for text in _pack(paragraphs):
                packed.append((text, {"extraction_method": "text", "confidence": 0.9}))

            for table in tables:
                packed.append(
                    (
                        table["text"],
                        {
                            "extraction_method": "table",
                            "confidence": table.get("confidence", 0.62),
                            "table": table.get("table"),
                        },
                    )
                )

            for text, meta in packed:
                index += 1
                heading = section.split(" > ")[-1] if section else ""
                embedding_text = f"{section}\n{text}".strip() if section else text
                chunks.append(
                    {
                        "index": index,
                        "page_number": page["page_number"],
                        "section_path": section,
                        "heading": heading,
                        "text": text,
                        "embedding_text": embedding_text,
                        "char_count": len(text),
                        "token_estimate": max(1, len(text) // 4),
                        "extraction_method": meta["extraction_method"],
                        "confidence": meta["confidence"],
                        "table": meta.get("table"),
                        "ocr_used": page.get("ocr_used", False),
                    }
                )
    return chunks


def chunk_text_for_embedding(chunks: list[dict]) -> list[str]:
    return [c["embedding_text"] for c in chunks]
