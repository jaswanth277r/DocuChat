from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
from bson import ObjectId
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from .. import db, jobs
from ..config import get_settings
from ..models import DocumentPatch
from ..retrieval.index import invalidate
from ..security import CurrentUser, audit, check_rate_limit, get_current_user
from ..storage import PdfValidationError, clear_page_cache, delete_file, page_cache_dir, save_upload, upload_path

router = APIRouter(prefix="/documents", tags=["documents"])

CATEGORIES = {
    "research_paper",
    "lecture_notes",
    "textbook",
    "technical_manual",
    "legal",
    "business_report",
    "other",
    "unknown",
}


def _owned(document_id: str, user: CurrentUser) -> dict:
    document = db.documents().find_one({"_id": db.oid(document_id), "user_id": db.oid(user.id), "deleted": {"$ne": True}})
    if not document:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


def _document_out(document: dict) -> dict:
    out = db.serialize(document) or {}
    out.pop("pdf_metadata", None)
    out["file_available"] = upload_path(str(document["_id"])).exists()
    return out


@router.post("")
def upload_document(
    file: UploadFile = File(...),
    collection_id: str | None = Form(default=None),
    user: CurrentUser = Depends(get_current_user),
):
    settings = get_settings()
    check_rate_limit("upload", user.id, limit=settings.uploads_per_hour)

    original_name = Path(file.filename or "document.pdf").name
    if not original_name.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    if collection_id and not db.collections().find_one(
        {"_id": db.oid(collection_id), "user_id": db.oid(user.id)}
    ):
        raise HTTPException(status_code=404, detail="Collection not found")

    document_id = ObjectId()
    record = {
        "_id": document_id,
        "user_id": db.oid(user.id),
        "original_name": original_name,
        "title": Path(original_name).stem.replace("_", " ").strip(),
        "status": "uploaded",
        "progress": 2,
        "stage_message": "Uploading",
        "size_bytes": 0,
        "page_count": None,
        "chunk_count": 0,
        "category": None,
        "category_confidence": None,
        "category_locked": False,
        "warnings": [],
        "error": None,
        "ingest_version": 0,
        "created_at": db.utcnow(),
        "updated_at": db.utcnow(),
        "deleted": False,
    }
    db.documents().insert_one(record)

    try:
        path, size, digest = save_upload(str(document_id), file)
    except PdfValidationError as exc:
        db.documents().update_one(
            {"_id": document_id},
            {
                "$set": {
                    "status": "failed",
                    "progress": 100,
                    "stage_message": "Upload rejected",
                    "error": {"code": exc.code, "message": exc.message},
                    "updated_at": db.utcnow(),
                }
            },
        )
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message}) from exc

    db.documents().update_one(
        {"_id": document_id},
        {
            "$set": {
                "size_bytes": size,
                "sha256": digest,
                "status": "queued",
                "progress": 8,
                "stage_message": "Queued for processing",
                "updated_at": db.utcnow(),
            }
        },
    )

    if collection_id:
        db.collections().update_one(
            {"_id": db.oid(collection_id)},
            {"$addToSet": {"document_ids": document_id}, "$set": {"updated_at": db.utcnow()}},
        )

    job_id = jobs.create_job(str(document_id), user.id)
    audit("document.upload", user.id, document_id=str(document_id), name=original_name, job_id=job_id)
    record.update({"status": "queued", "size_bytes": size, "progress": 8, "stage_message": "Queued for processing"})
    return {**_document_out(record), "job_id": job_id}


@router.get("")
def list_documents(user: CurrentUser = Depends(get_current_user), q: str | None = None, status_filter: str | None = None):
    query: dict = {"user_id": db.oid(user.id), "deleted": {"$ne": True}}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"original_name": {"$regex": q, "$options": "i"}},
        ]
    if status_filter:
        query["status"] = status_filter
    rows = list(db.documents().find(query).sort("created_at", -1).limit(200))
    return {"documents": [_document_out(row) for row in rows]}


@router.get("/{document_id}")
def get_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    return _document_out(_owned(document_id, user))


@router.get("/{document_id}/status")
def get_status(document_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    job = db.jobs().find_one({"document_id": document["_id"]}, sort=[("created_at", -1)])
    return {
        "id": str(document["_id"]),
        "status": document.get("status"),
        "progress": document.get("progress", 0),
        "stage_message": document.get("stage_message"),
        "error": document.get("error"),
        "warnings": document.get("warnings", []),
        "chunk_count": document.get("chunk_count", 0),
        "page_count": document.get("page_count"),
        "embedder": document.get("embedder"),
        "job": db.serialize(job) if job else None,
        "updated_at": document.get("updated_at").isoformat() if document.get("updated_at") else None,
    }


@router.get("/{document_id}/file")
def get_file(document_id: str, user: CurrentUser = Depends(get_current_user)):
    _owned(document_id, user)
    path = upload_path(document_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original PDF is unavailable")
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{path.name}"'},
    )


def _highlight_rects(page: fitz.Page, text: str) -> list[fitz.Rect]:
    cleaned = " ".join((text or "").replace("…", " ").split())
    if not cleaned:
        return []
    words = cleaned.split()
    first_sentence = cleaned.split(". ")[0]
    candidates = [
        first_sentence[:180],
        cleaned[:160],
        " ".join(words[:16]),
        " ".join(words[:12]),
        " ".join(words[:8]),
        " ".join(words[:5]),
    ]
    for candidate in candidates:
        if len(candidate) < 6:
            continue
        try:
            rects = page.search_for(candidate)
        except Exception:
            rects = []
        if rects:
            return rects[:10]
    return []


@router.get("/{document_id}/pages/{page_number}/image")
def get_page_image(
    document_id: str,
    page_number: int,
    highlight: str | None = None,
    scale: float = 2.0,
    user: CurrentUser = Depends(get_current_user),
):
    document = _owned(document_id, user)
    page_count = int(document.get("page_count") or 0)
    if page_number < 1 or (page_count and page_number > page_count):
        raise HTTPException(status_code=404, detail="Page out of range")
    path = upload_path(document_id)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Original PDF is unavailable")

    scale = max(1.0, min(3.0, float(scale)))
    version = int(document.get("ingest_version") or 0)
    digest = hashlib.sha1((highlight or "").encode("utf-8")).hexdigest()[:12]
    cache_path = page_cache_dir(document_id) / f"v{version}-p{page_number}-s{scale:.1f}-{digest}.png"
    if not cache_path.exists():
        try:
            pdf = fitz.open(path)
            try:
                page = pdf[page_number - 1]
                for rect in _highlight_rects(page, highlight or ""):
                    annot = page.add_highlight_annot(rect)
                    annot.set_colors(stroke=(1.0, 0.85, 0.25))
                    annot.set_opacity(0.45)
                    annot.update()
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                pixmap.save(cache_path)
            finally:
                pdf.close()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Could not render this page: {exc}") from exc
    return FileResponse(
        cache_path,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=86400"},
    )


@router.get("/{document_id}/pages/{page_number}")
def get_page(document_id: str, page_number: int, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    if page_number < 1 or (document.get("page_count") and page_number > document["page_count"]):
        raise HTTPException(status_code=404, detail="Page out of range")
    page = db.pages().find_one({"document_id": document["_id"], "page_number": page_number})
    if not page:
        raise HTTPException(status_code=404, detail="Page not found")
    return db.serialize(page)


@router.get("/{document_id}/evidence")
def get_evidence(document_id: str, chunk_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    index_value = None
    if ":" in chunk_id:
        prefix, _, suffix = chunk_id.partition(":")
        if prefix != str(document["_id"]):
            raise HTTPException(status_code=400, detail="Chunk does not belong to this document")
        index_value = suffix
    else:
        index_value = chunk_id
    try:
        index_int = int(index_value)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid chunk id") from None
    chunk = db.chunks().find_one({"document_id": document["_id"], "index": index_int})
    if not chunk:
        raise HTTPException(status_code=404, detail="Evidence chunk not found")
    page = db.pages().find_one({"document_id": document["_id"], "page_number": chunk.get("page_number")})
    return {
        "chunk": {
            "id": f"{document['_id']}:{chunk['index']}",
            "index": chunk["index"],
            "page_number": chunk.get("page_number"),
            "section_path": chunk.get("section_path"),
            "text": chunk.get("text"),
            "extraction_method": chunk.get("extraction_method"),
            "confidence": chunk.get("confidence"),
            "table": chunk.get("table"),
        },
        "page": {
            "page_number": page.get("page_number") if page else chunk.get("page_number"),
            "text": page.get("text") if page else None,
            "headings": page.get("headings") if page else [],
            "scanned": page.get("scanned") if page else False,
            "ocr_used": page.get("ocr_used") if page else False,
        },
        "document": {
            "id": str(document["_id"]),
            "title": document.get("title"),
            "page_count": document.get("page_count"),
        },
    }


@router.get("/{document_id}/outline")
def get_outline(document_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    return {
        "outline": document.get("outline") or [],
        "page_count": document.get("page_count"),
        "warnings": document.get("warnings") or [],
    }


@router.patch("/{document_id}")
def patch_document(document_id: str, payload: DocumentPatch, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    update: dict = {"updated_at": db.utcnow()}
    if payload.title is not None:
        update["title"] = payload.title.strip()
        update["title_locked"] = True
    if payload.category is not None:
        if payload.category not in CATEGORIES:
            raise HTTPException(status_code=422, detail="Unknown category")
        update["category"] = payload.category
        update["category_locked"] = True
        update["category_confidence"] = 1.0
    db.documents().update_one({"_id": document["_id"]}, {"$set": update})
    audit("document.patch", user.id, document_id=document_id, fields=list(update.keys()))
    return _document_out(_owned(document_id, user))


@router.post("/{document_id}/retry")
def retry_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    if document.get("status") not in {"failed", "ready"}:
        raise HTTPException(status_code=409, detail="This document is already being processed")
    if not upload_path(document_id).exists():
        raise HTTPException(status_code=409, detail="The original file is unavailable; upload the PDF again")
    db.documents().update_one(
        {"_id": document["_id"]},
        {
            "$set": {
                "status": "queued",
                "progress": 8,
                "stage_message": "Re-queued for processing",
                "error": None,
                "updated_at": db.utcnow(),
            }
        },
    )
    job_id = jobs.create_job(document_id, user.id)
    audit("document.retry", user.id, document_id=document_id, job_id=job_id)
    return {"ok": True, "job_id": job_id}


@router.delete("/{document_id}")
def delete_document(document_id: str, user: CurrentUser = Depends(get_current_user)):
    document = _owned(document_id, user)
    db.chunks().delete_many({"document_id": document["_id"]})
    db.pages().delete_many({"document_id": document["_id"]})
    db.study_guides().delete_many({"document_id": document["_id"], "user_id": db.oid(user.id)})
    db.flashcards().delete_many({"document_id": document["_id"], "user_id": db.oid(user.id)})
    db.quizzes().delete_many({"document_id": document["_id"], "user_id": db.oid(user.id)})
    db.collections().update_many({"user_id": db.oid(user.id)}, {"$pull": {"document_ids": document["_id"]}})
    db.sessions().update_many(
        {"user_id": db.oid(user.id)}, {"$pull": {"document_ids": document["_id"]}, "$set": {"updated_at": db.utcnow()}}
    )
    delete_file(document_id)
    clear_page_cache(document_id)
    invalidate(document_id)
    db.documents().update_one(
        {"_id": document["_id"]},
        {"$set": {"deleted": True, "status": "deleted", "deleted_at": db.utcnow()}},
    )
    audit("document.delete", user.id, document_id=document_id)
    return {"ok": True}
