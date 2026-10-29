from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

from .. import db
from ..retrieval.embeddings import get_embedder
from ..retrieval.index import invalidate
from ..storage import PdfValidationError, upload_path
from .chunker import chunk_document
from .pdf import parse_pdf, quick_validate

log = logging.getLogger("docuchat.ingestion")


class PipelineError(Exception):
    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


def ingest_document(document_id: str, user_id: str, progress) -> dict:
    document = db.documents().find_one({"_id": db.oid(document_id)})
    if not document:
        raise PipelineError("document_missing", "The document record no longer exists")
    path = upload_path(document_id)

    progress("validating", 12, "Validating PDF")
    if not path.exists():
        raise PipelineError("file_missing", "The uploaded file is missing from storage")
    try:
        check = quick_validate(path)
    except Exception as exc:
        raise PipelineError("unreadable_pdf", f"The PDF could not be opened: {exc}") from exc
    if not check.get("ok"):
        raise PipelineError(check.get("code", "invalid_pdf"), check.get("message", "Invalid PDF"))

    progress("extracting", 30, "Extracting text, structure and tables")
    try:
        parsed = parse_pdf(path)
    except ValueError as exc:
        code = str(exc)
        if code == "password_protected":
            raise PipelineError(code, "This PDF is password protected. Remove the password and upload again.") from exc
        if code.startswith("too_many_pages"):
            raise PipelineError("too_many_pages", "This PDF exceeds the page limit") from exc
        raise PipelineError("unreadable_pdf", f"Could not parse this PDF: {exc}") from exc
    except Exception as exc:
        raise PipelineError("parse_failed", f"PDF parsing failed: {exc}", retryable=True) from exc

    scanned = [p["page_number"] for p in parsed["pages"] if p["scanned"]]
    progress("ocr_check", 45, "Checking OCR coverage" if scanned else "Text layer looks good")

    db.documents().update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "page_count": parsed["page_count"],
                "title": document.get("title") if document.get("title_locked") else parsed["title"],
                "authors": parsed["authors"],
                "language": parsed["language"],
                "keywords": parsed["keywords"],
                "outline": parsed["outline"][:300],
                "warnings": parsed["warnings"],
                "scanned_pages": scanned,
                "category": document.get("category") if document.get("category_locked") else parsed["category"],
                "category_confidence": parsed["category_confidence"],
                "pdf_metadata": parsed["metadata"],
                "updated_at": db.utcnow(),
            }
        },
    )

    progress("chunking", 55, "Building structure-aware chunks")
    chunks = chunk_document(parsed)
    if not chunks:
        if parsed["warnings"]:
            raise PipelineError(
                "no_text",
                "No extractable text was found. The document may be a scanned PDF without OCR support.",
            )
        raise PipelineError("no_chunks", "No content chunks could be produced from this PDF")

    progress("embedding", 70, f"Embedding {len(chunks)} chunks")
    try:
        embedder = get_embedder()
        texts = [chunk["embedding_text"] for chunk in chunks]
        vectors = embedder.embed(texts)
    except Exception as exc:
        raise PipelineError("embedding_failed", f"Embedding failed: {exc}", retryable=True) from exc
    if vectors.shape[0] != len(chunks):
        raise PipelineError("embedding_failed", "Embedding provider returned an unexpected shape", retryable=True)

    progress("indexing", 88, "Writing chunks and vectors")
    db.chunks().delete_many({"document_id": document["_id"]})
    db.pages().delete_many({"document_id": document["_id"]})

    page_rows = []
    for page in parsed["pages"]:
        page_rows.append(
            {
                "document_id": document["_id"],
                "page_number": page["page_number"],
                "text": page["text"],
                "char_count": page["char_count"],
                "headings": page["headings"],
                "tables": page["tables"],
                "ocr_used": page["ocr_used"],
                "scanned": page["scanned"],
                "warnings": page["warnings"],
            }
        )
    if page_rows:
        db.pages().insert_many(page_rows)

    rows = []
    for chunk, vector in zip(chunks, vectors):
        rows.append(
            {
                "document_id": document["_id"],
                "user_id": document["user_id"],
                "index": chunk["index"],
                "page_number": chunk["page_number"],
                "section_path": chunk["section_path"],
                "heading": chunk["heading"],
                "text": chunk["text"],
                "embedding_text": chunk["embedding_text"],
                "embedding": [round(float(v), 6) for v in np.asarray(vector)],
                "char_count": chunk["char_count"],
                "token_estimate": chunk["token_estimate"],
                "extraction_method": chunk["extraction_method"],
                "confidence": chunk["confidence"],
                "table": chunk["table"],
                "ocr_used": chunk["ocr_used"],
                "created_at": db.utcnow(),
            }
        )
    if rows:
        db.chunks().insert_many(rows)

    db.documents().update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "status": "ready",
                "progress": 100,
                "stage_message": "Ready",
                "error": None,
                "chunk_count": len(rows),
                "embedder": embedder.status(),
                "processed_at": db.utcnow(),
                "updated_at": db.utcnow(),
            },
            "$inc": {"ingest_version": 1},
        },
    )
    invalidate(document_id)
    return {"chunks": len(rows), "pages": len(page_rows), "warnings": len(parsed["warnings"])}


def handle_upload_failure(document_id: str, error: PdfValidationError) -> None:
    db.documents().update_one(
        {"_id": db.oid(document_id)},
        {
            "$set": {
                "status": "failed",
                "progress": 100,
                "stage_message": "Upload rejected",
                "error": {"code": error.code, "message": error.message},
                "updated_at": db.utcnow(),
            }
        },
    )
