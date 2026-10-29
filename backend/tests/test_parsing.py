from __future__ import annotations

from pathlib import Path

from app.ingestion.chunker import MAX_CHARS, chunk_document
from app.ingestion.pdf import parse_pdf

FIXTURES = Path(__file__).resolve().parents[2] / "evaluation" / "fixtures"


def test_parser_finds_structure():
    parsed = parse_pdf(FIXTURES / "transformer_notes.pdf")
    assert parsed["page_count"] == 4
    assert parsed["category"] == "lecture_notes"
    assert parsed["title"].startswith("Transformer Architectures")
    page_headings = {page["page_number"]: [h["text"] for h in page["headings"]] for page in parsed["pages"]}
    assert "Section 4.2 Scaling Factors" in page_headings[2]
    assert parsed["pages"][2]["tables"], "expected the BLEU table on page 3"
    assert "Baseline" in parsed["pages"][2]["tables"][0]["markdown"]


def test_chunks_keep_page_metadata():
    parsed = parse_pdf(FIXTURES / "transformer_notes.pdf")
    chunks = chunk_document(parsed)
    assert chunks
    assert all(1 <= chunk["page_number"] <= 4 for chunk in chunks)
    assert all(chunk["text"] for chunk in chunks)
    assert all(len(chunk["text"]) <= MAX_CHARS + 50 for chunk in chunks)
    assert all(chunk["embedding_text"] for chunk in chunks)
    table_chunks = [chunk for chunk in chunks if chunk["extraction_method"] == "table"]
    assert table_chunks and table_chunks[0]["page_number"] == 3


def test_no_chunk_crosses_pages():
    parsed = parse_pdf(FIXTURES / "retrieval_report.pdf")
    chunks = chunk_document(parsed)
    for chunk in chunks:
        page = parsed["pages"][chunk["page_number"] - 1]
        assert chunk["text"][:40].strip() in page["text"] or chunk["extraction_method"] == "table"


def test_quick_validate_rejects_non_pdf(tmp_path):
    from app.ingestion.pdf import quick_validate

    fake = tmp_path / "not.pdf"
    fake.write_text("this is not a pdf")
    try:
        quick_validate(fake)
    except Exception as exc:
        assert exc is not None
    else:
        raise AssertionError("quick_validate should fail for a non-PDF")
