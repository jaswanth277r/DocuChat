from __future__ import annotations

import re
import statistics
import shutil
from collections import Counter
from pathlib import Path

import fitz  # PyMuPDF

from ..config import get_settings
from ..retrieval.textutil import STOPWORDS

CATEGORY_RULES = {
    "research_paper": ["abstract", "references", "doi", "et al", "methodology", "experiment", "conclusion", "hypothesis"],
    "lecture_notes": ["lecture", "week", "tutorial", "professor", "assignment", "semester", "slides"],
    "textbook": ["chapter", "exercise", "contents", "learning objectives", "summary", "review questions"],
    "technical_manual": ["installation", "configuration", "troubleshooting", "api", "command", "setup", "requirements"],
    "legal": ["agreement", "party", "clause", "liability", "jurisdiction", "whereas", "termination", "hereby"],
    "business_report": ["revenue", "quarter", "fiscal", "stakeholder", "executive summary", "market", "growth"],
}

NUMBERED_HEADING = re.compile(r"^(\d+(?:\.\d+){0,3})[.)]?\s+([A-Z].{0,120})$")
NAMED_HEADING = re.compile(
    r"^(abstract|introduction|background|related work|methodology|methods|results|discussion|"
    r"conclusion|conclusions|references|appendix|executive summary|recommendations|limitations)$",
    re.IGNORECASE,
)


def _clean(text: str) -> str:
    text = text.replace("\u00ad", "")
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t\u00a0]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _span_profile(line: dict) -> tuple[float, float, str]:
    sizes = []
    chars = []
    bold = 0
    total = 0
    for span in line.get("spans", []):
        t = span.get("text", "")
        n = len(t.strip())
        if not n:
            continue
        size = round(span.get("size", 10), 1)
        sizes.append(size)
        chars.append(n)
        total += n
        if int(span.get("flags", 0)) & 16:
            bold += n
    if not total:
        return 10.0, 0.0, ""
    size = max(sizes) if sizes else 10.0
    return size, bold / total, " ".join(s.get("text", "") for s in line.get("spans", [])).strip()


def _is_heading(text: str, size: float, body: float, bold_ratio: float) -> tuple[bool, int, str | None]:
    clean = " ".join(text.split())
    if not clean or len(clean) > 160 or len(clean.split()) > 18:
        return False, 0, None

    numbered = NUMBERED_HEADING.match(clean)
    if numbered:
        level = min(numbered.group(1).count(".") + 1, 3)
        return True, level, numbered.group(1)

    if NAMED_HEADING.match(clean):
        return True, 1 if size >= body * 1.2 else 2, None

    if size >= body * 1.45:
        return True, 1, None
    if size >= body * 1.18:
        return True, 2, None
    if bold_ratio > 0.75 and size >= body * 0.98 and not clean.endswith((".", ",", ";", ":")):
        return True, 3, None
    return False, 0, None


def _page_tables(page: fitz.Page, page_number: int) -> tuple[list[dict], list[fitz.Rect]]:
    tables: list[dict] = []
    boxes: list[fitz.Rect] = []
    try:
        found = page.find_tables()
    except Exception:
        return tables, boxes

    for index, table in enumerate(found.tables):
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows or len(rows) < 2:
            continue
        cleaned_rows = [[_clean(str(cell)) if cell is not None else "" for cell in row] for row in rows]
        widths = Counter(len(row) for row in cleaned_rows)
        width = widths.most_common(1)[0][0]
        cleaned_rows = [(row + [""] * width)[:width] for row in cleaned_rows]
        header = cleaned_rows[0]
        body_rows = cleaned_rows[1:]
        markdown = "| " + " | ".join(header) + " |\n| " + " | ".join(["---"] * width) + " |\n"
        markdown += "\n".join("| " + " | ".join(row) + " |" for row in body_rows)
        tables.append(
            {
                "index": index,
                "title": f"Table {index + 1} on page {page_number}",
                "headers": header,
                "rows": body_rows,
                "markdown": markdown,
                "bbox": list(table.bbox),
                "extraction_confidence": 0.62,
            }
        )
        boxes.append(fitz.Rect(table.bbox))
    return tables, boxes


def _overlaps(bbox: tuple, boxes: list[fitz.Rect]) -> bool:
    rect = fitz.Rect(bbox)
    area = max(rect.get_area(), 1)
    for box in boxes:
        try:
            inter = rect & box
            if inter.get_area() / area > 0.5:
                return True
        except Exception:
            continue
    return False


def _ocr_page(page: fitz.Page) -> tuple[str | None, str | None]:
    if not shutil.which("tesseract"):
        return None, "tesseract binary is not installed on the server"
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore

        pix = page.get_pixmap(dpi=200)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        text = pytesseract.image_to_string(image)
        if len(text.strip()) < 20:
            return None, "OCR produced too little text"
        return _clean(text), None
    except Exception as exc:  # pragma: no cover - depends on optional tooling
        return None, f"OCR failed: {exc}"


def _guess_category(full_text: str) -> tuple[str, float]:
    lowered = full_text.lower()
    scores = {name: sum(lowered.count(term) for term in terms) for name, terms in CATEGORY_RULES.items()}
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_name, top_score = ranked[0]
    total = sum(scores.values()) or 0
    if top_score == 0:
        return "other", 0.2
    confidence = min(0.95, 0.45 + 0.5 * (top_score / max(total, 1)))
    return top_name, round(confidence, 2)


def _keywords(text: str, limit: int = 10) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z\-]{3,}", text.lower())
    counts = Counter(w for w in words if w not in STOPWORDS)
    return [word for word, _ in counts.most_common(limit)]


def parse_pdf(path: Path) -> dict:
    settings = get_settings()
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            raise ValueError("password_protected")
        if doc.page_count == 0:
            raise ValueError("empty_document")
        if doc.page_count > settings.max_pages:
            raise ValueError(f"too_many_pages:{doc.page_count}")

        metadata = doc.metadata or {}
        toc = doc.get_toc(simple=True) or []

        pages: list[dict] = []
        warnings: list[dict] = []
        section_stack: list[tuple[int, str]] = []
        heading_outline: list[dict] = []
        all_text_parts: list[str] = []
        total_chars = 0
        body_sizes: list[tuple[float, int]] = []

        for page_index, page in enumerate(doc, start=1):
            page_number = page_index
            raw_blocks: list[dict] = []
            dict_data = page.get_text("dict")
            for block in dict_data.get("blocks", []):
                if block.get("type") != 0:
                    continue
                lines = []
                for line in block.get("lines", []):
                    size, bold_ratio, text = _span_profile(line)
                    if text:
                        lines.append({"text": text, "size": size, "bold": bold_ratio, "bbox": line.get("bbox")})
                        body_sizes.append((size, max(len(text), 1)))
                if not lines:
                    continue
                raw_blocks.append(
                    {
                        "kind": "text",
                        "bbox": block.get("bbox", (0, 0, 0, 0)),
                        "lines": lines,
                        "text": _clean(" ".join(line["text"] for line in lines)),
                    }
                )

            body_size = 10.0
            if body_sizes:
                weights = [w for _, w in body_sizes]
                sizes = [s for s, _ in body_sizes]
                try:
                    body_size = statistics.median(
                        sorted(sizes)[max(0, len(sizes) // 4) : max(1, len(sizes) * 3 // 4)] or sizes
                    )
                except statistics.StatisticsError:
                    body_size = 10.0
                if not 6 <= body_size <= 30:
                    body_size = 10.0
                del weights

            tables, table_boxes = _page_tables(page, page_number)
            blocks: list[dict] = []

            for raw in sorted(raw_blocks, key=lambda b: (round(b["bbox"][1], 1), b["bbox"][0])):
                if _overlaps(raw["bbox"], table_boxes):
                    continue
                text = raw["text"]
                if not text:
                    continue
                first_line = raw["lines"][0]
                heading, level, number = _is_heading(
                    first_line["text"], first_line["size"], body_size, first_line["bold"]
                )
                if heading:
                    while section_stack and section_stack[-1][0] >= level:
                        section_stack.pop()
                    section_stack.append((level, text))
                    heading_outline.append(
                        {"text": text, "level": level, "page_number": page_number, "number": number}
                    )
                    continue
                blocks.append(
                    {
                        "kind": "paragraph",
                        "text": text,
                        "bbox": list(raw["bbox"]),
                        "section_path": " > ".join(item[1] for item in section_stack),
                        "extraction_method": "text",
                        "confidence": 0.9,
                        "page_number": page_number,
                    }
                )

            for table in tables:
                blocks.append(
                    {
                        "kind": "table",
                        "text": table["markdown"],
                        "bbox": table["bbox"],
                        "section_path": " > ".join(item[1] for item in section_stack),
                        "table": table,
                        "extraction_method": "table",
                        "confidence": table["extraction_confidence"],
                        "page_number": page_number,
                    }
                )

            text = _clean(page.get_text("text"))
            char_count = len(re.sub(r"\s", "", text))
            image_count = len(page.get_images(full=True))
            scanned = char_count < 60 and image_count > 0
            ocr_used = False
            page_warnings: list[str] = []

            if scanned:
                ocr_text, ocr_error = _ocr_page(page)
                if ocr_text:
                    text = ocr_text
                    blocks = [
                        {
                            "kind": "paragraph",
                            "text": ocr_text,
                            "bbox": [0, 0, page.rect.width, page.rect.height],
                            "section_path": " > ".join(item[1] for item in section_stack),
                            "extraction_method": "ocr",
                            "confidence": 0.55,
                            "page_number": page_number,
                        }
                    ]
                    ocr_used = True
                    char_count = len(re.sub(r"\s", "", text))
                    page_warnings.append("ocr_applied")
                else:
                    page_warnings.append("ocr_unavailable")
                    warnings.append(
                        {
                            "page_number": page_number,
                            "code": "ocr_unavailable",
                            "message": f"Page {page_number} looks scanned; OCR was not available ({ocr_error}).",
                        }
                    )
            elif char_count < 120 and image_count > 0:
                page_warnings.append("low_text")

            headings = [item for item in heading_outline if item["page_number"] == page_number]
            pages.append(
                {
                    "page_number": page_number,
                    "text": text,
                    "char_count": char_count,
                    "image_count": image_count,
                    "blocks": blocks,
                    "headings": headings,
                    "tables": tables,
                    "ocr_used": ocr_used,
                    "scanned": scanned,
                    "warnings": page_warnings,
                }
            )
            total_chars += char_count
            all_text_parts.append(text)

        full_text = "\n".join(all_text_parts)
        if total_chars < 200:
            warnings.append(
                {
                    "page_number": None,
                    "code": "no_text_layer",
                    "message": "This PDF has almost no extractable text. It may be a scanned document.",
                }
            )

        title = (metadata.get("title") or "").strip()
        if not title or title.lower() in {"untitled", "none"}:
            title = ""
            for page in pages[:2]:
                for heading in page["headings"]:
                    if heading["level"] <= 2:
                        title = heading["text"]
                        break
                if title:
                    break
            if not title:
                title = path.stem.replace("_", " ").replace("-", " ").strip().title()

        category, category_confidence = _guess_category(full_text[:20000])
        lower = full_text.lower()
        language = "en" if lower.count(" the ") + lower.count(" and ") > 4 else "unknown"

        return {
            "title": title[:300],
            "authors": [a.strip() for a in re.split(r"[;,]", metadata.get("author") or "") if a.strip()],
            "language": language,
            "page_count": doc.page_count,
            "metadata": {k: v for k, v in metadata.items() if v},
            "toc": [{"level": lvl, "title": t, "page_number": pg} for lvl, t, pg in toc],
            "outline": toc and [{"level": lvl, "text": t, "page_number": pg} for lvl, t, pg in toc] or heading_outline,
            "category": category,
            "category_confidence": category_confidence,
            "keywords": _keywords(full_text),
            "warnings": warnings,
            "pages": pages,
            "full_text": full_text,
        }
    finally:
        doc.close()


def quick_validate(path: Path) -> dict:
    settings = get_settings()
    doc = fitz.open(path)
    try:
        if doc.needs_pass:
            return {"ok": False, "code": "password_protected", "message": "This PDF is password protected."}
        if doc.page_count == 0:
            return {"ok": False, "code": "empty_document", "message": "This PDF has no pages."}
        if doc.page_count > settings.max_pages:
            return {
                "ok": False,
                "code": "too_many_pages",
                "message": f"This PDF has {doc.page_count} pages; the limit is {settings.max_pages}.",
            }
        return {"ok": True, "page_count": doc.page_count}
    finally:
        doc.close()
