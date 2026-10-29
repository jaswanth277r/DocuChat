from __future__ import annotations

import logging
import queue
import threading
import time
import traceback

from . import db
from .config import get_settings

log = logging.getLogger("docuchat.jobs")
QUEUE_KEY = "docuchat:jobs"
DLQ_KEY = "docuchat:jobs:dlq"

_stop = threading.Event()
_memory_queue: queue.Queue[str] = queue.Queue()
_started = False
_lock = threading.Lock()


def _redis():
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=1, socket_timeout=2)
        client.ping()
        return client
    except Exception:
        return None


def enqueue(job_id: str) -> None:
    client = _redis()
    if client is not None:
        client.lpush(QUEUE_KEY, job_id)
        return
    _memory_queue.put(job_id)


def create_job(document_id: str, user_id: str, job_type: str = "ingest") -> str:
    result = db.jobs().insert_one(
        {
            "type": job_type,
            "document_id": db.oid(document_id),
            "user_id": db.oid(user_id),
            "status": "queued",
            "attempts": 0,
            "max_attempts": 3,
            "progress": 0,
            "message": "Queued",
            "error": None,
            "created_at": db.utcnow(),
            "started_at": None,
            "finished_at": None,
        }
    )
    job_id = str(result.inserted_id)
    enqueue(job_id)
    return job_id


def _claim_job(job_id: str) -> dict | None:
    return db.jobs().find_one_and_update(
        {"_id": db.oid(job_id), "status": {"$in": ["queued", "retrying"]}},
        {"$set": {"status": "processing", "started_at": db.utcnow()}},
        return_document=True,
    )


def _set_document_stage(document_id, status: str, progress: int, message: str) -> None:
    db.documents().update_one(
        {"_id": document_id},
        {"$set": {"status": status, "progress": progress, "stage_message": message, "updated_at": db.utcnow()}},
    )


def _run_job(job_id: str) -> None:
    job = _claim_job(job_id)
    if not job:
        return
    document_id = job["document_id"]
    attempts = int(job.get("attempts") or 0) + 1

    db.jobs().update_one({"_id": job["_id"]}, {"$set": {"attempts": attempts}})

    def progress(status: str, percent: int, message: str) -> None:
        _set_document_stage(document_id, status, percent, message)
        db.jobs().update_one({"_id": job["_id"]}, {"$set": {"progress": percent, "message": message}})

    try:
        from .ingestion.pipeline import ingest_document

        summary = ingest_document(str(document_id), str(job["user_id"]), progress)
        db.jobs().update_one(
            {"_id": job["_id"]},
            {"$set": {"status": "succeeded", "progress": 100, "message": "Ready", "finished_at": db.utcnow()}},
        )
        log.info("ingested document %s (%s chunks)", document_id, summary.get("chunks"))
    except Exception as exc:
        log.exception("ingestion failed for %s", document_id)
        code = getattr(exc, "code", "processing_failed")
        retryable = getattr(exc, "retryable", False)
        message = getattr(exc, "message", None) or str(exc) or "Processing failed"
        if retryable and attempts < int(job.get("max_attempts") or 3):
            db.jobs().update_one(
                {"_id": job["_id"]},
                {
                    "$set": {
                        "status": "retrying",
                        "message": f"Retrying after error: {message}",
                        "error": {"code": code, "message": message, "trace": traceback.format_exc(limit=3)},
                        "next_attempt_at": db.utcnow(),
                    }
                },
            )
            _set_document_stage(document_id, "queued", 10, f"Retrying ({attempts}/3)")
            time.sleep(min(2 ** attempts, 8))
            enqueue(str(job["_id"]))
            return

        db.jobs().update_one(
            {"_id": job["_id"]},
            {
                "$set": {
                    "status": "failed",
                    "error": {"code": code, "message": message, "trace": traceback.format_exc(limit=5)},
                    "finished_at": db.utcnow(),
                }
            },
        )
        db.documents().update_one(
            {"_id": document_id},
            {
                "$set": {
                    "status": "failed",
                    "progress": 100,
                    "stage_message": "Processing failed",
                    "error": {"code": code, "message": message},
                    "updated_at": db.utcnow(),
                }
            },
        )
        client = _redis()
        if client is not None:
            client.lpush(DLQ_KEY, str(job["_id"]))


def _recover_stuck_jobs() -> None:
    cutoff = db.utcnow().timestamp() - 600
    for job in db.jobs().find({"status": "processing"}):
        started = job.get("started_at")
        if started and started.timestamp() < cutoff:
            db.jobs().update_one({"_id": job["_id"]}, {"$set": {"status": "queued", "message": "Recovered after restart"}})
            enqueue(str(job["_id"]))


def cleanup_expired_documents() -> int:
    settings = get_settings()
    if settings.retention_days <= 0:
        return 0
    from .storage import clear_page_cache, delete_file

    removed = 0
    from datetime import timedelta

    cutoff = db.utcnow() - timedelta(days=settings.retention_days)
    for document in db.documents().find({"created_at": {"$lt": cutoff}, "deleted": {"$ne": True}}):
        doc_id = str(document["_id"])
        db.chunks().delete_many({"document_id": document["_id"]})
        db.pages().delete_many({"document_id": document["_id"]})
        delete_file(doc_id)
        clear_page_cache(doc_id)
        db.documents().update_one(
            {"_id": document["_id"]},
            {"$set": {"deleted": True, "status": "deleted", "deleted_at": db.utcnow()}},
        )
        try:
            from .retrieval.index import invalidate

            invalidate(doc_id)
        except Exception:
            pass
        removed += 1
    return removed


def _loop() -> None:
    last_cleanup = 0.0
    while not _stop.is_set():
        try:
            job_id = None
            client = _redis()
            if client is not None:
                item = client.brpop(QUEUE_KEY, timeout=1)
                if item:
                    job_id = item[1].decode("utf-8")
            else:
                try:
                    job_id = _memory_queue.get(timeout=1)
                except queue.Empty:
                    job_id = None
            if job_id:
                _run_job(job_id)
            if time.time() - last_cleanup > 3600:
                last_cleanup = time.time()
                removed = cleanup_expired_documents()
                if removed:
                    log.info("retention cleanup removed %s documents", removed)
        except Exception:
            log.exception("job worker loop error")
            time.sleep(1)


def start_worker() -> None:
    global _started
    with _lock:
        if _started:
            return
        _started = True
    _recover_stuck_jobs()
    thread = threading.Thread(target=_loop, name="docuchat-worker", daemon=True)
    thread.start()
    log.info("job worker started")


def stop_worker() -> None:
    _stop.set()
