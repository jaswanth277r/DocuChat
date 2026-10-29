from __future__ import annotations

import asyncio
import statistics
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..config import get_settings
from ..evaluation.metrics import percentile
from ..evaluation.run import run_evaluation
from ..generation.providers import provider_status
from ..retrieval.embeddings import embedder_status
from ..security import CurrentUser, audit, require_admin

router = APIRouter(prefix="/admin", tags=["admin"])


def _redis_length(key: str) -> int | None:
    try:
        import redis

        client = redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5, socket_timeout=1)
        return int(client.llen(key))
    except Exception:
        return None


@router.get("/metrics")
def metrics(admin: CurrentUser = Depends(require_admin)):
    since = db.utcnow() - timedelta(days=7)
    documents = db.documents()
    total_documents = documents.count_documents({"deleted": {"$ne": True}})
    ready = documents.count_documents({"status": "ready", "deleted": {"$ne": True}})
    failed = documents.count_documents({"status": "failed", "deleted": {"$ne": True}})
    processing = documents.count_documents(
        {"status": {"$nin": ["ready", "failed", "deleted"]}, "deleted": {"$ne": True}}
    )
    processed_total = ready + failed
    ingest_seconds = []
    for job in db.jobs().find(
        {"type": "ingest", "status": "succeeded", "started_at": {"$ne": None}, "finished_at": {"$ne": None}}
    ).sort("created_at", -1).limit(100):
        ingest_seconds.append((job["finished_at"] - job["started_at"]).total_seconds())

    assistant_messages = list(
        db.messages()
        .find({"role": "assistant", "status": {"$in": ["complete", "abstained", "incomplete"]}})
        .limit(1000)
    )
    chat_latencies = [message.get("latency_ms") for message in assistant_messages if message.get("latency_ms")]
    abstained = sum(1 for message in assistant_messages if message.get("abstained"))
    citations_total = 0
    citations_invalid = 0
    for message in assistant_messages:
        for citation in message.get("citations") or []:
            citations_total += 1
            if citation.get("status") == "invalid":
                citations_invalid += 1

    usage_rows = list(db.usage().find({"created_at": {"$gte": since}}).limit(5000))
    tokens = sum(int(row.get("completion_tokens") or 0) + int(row.get("prompt_tokens") or 0) for row in usage_rows)

    jobs = list(db.jobs().find().sort("created_at", -1).limit(10))
    latest_eval = db.evaluation_runs().find_one({}, sort=[("created_at", -1)])

    return {
        "users": db.users().count_documents({}),
        "documents": {
            "total": total_documents,
            "ready": ready,
            "processing": processing,
            "failed": failed,
            "success_rate": round(ready / processed_total, 3) if processed_total else None,
            "avg_ingest_seconds": round(statistics.median(ingest_seconds), 2) if ingest_seconds else None,
        },
        "chunks": db.chunks().count_documents({}),
        "storage_bytes": sum(int(doc.get("size_bytes") or 0) for doc in documents.find({"deleted": {"$ne": True}}, {"size_bytes": 1})),
        "chat": {
            "sessions": db.sessions().count_documents({}),
            "messages": db.messages().count_documents({}),
            "latency_p50_ms": round(percentile([float(v) for v in chat_latencies], 0.5) or 0, 1),
            "latency_p95_ms": round(percentile([float(v) for v in chat_latencies], 0.95) or 0, 1),
            "abstention_rate": round(abstained / len(assistant_messages), 3) if assistant_messages else None,
            "citation_validity_rate": round(1 - citations_invalid / citations_total, 3) if citations_total else None,
            "tokens_last_7_days": tokens,
        },
        "queue_depth": _redis_length("docuchat:jobs"),
        "dead_letters": _redis_length("docuchat:jobs:dlq"),
        "jobs": [db.serialize(job) for job in jobs],
        "embedder": embedder_status(),
        "provider": provider_status(),
        "latest_evaluation": {
            "id": str(latest_eval["_id"]),
            "dataset": latest_eval.get("dataset"),
            "summary": latest_eval.get("summary"),
            "created_at": latest_eval.get("created_at").isoformat() if latest_eval.get("created_at") else None,
        }
        if latest_eval
        else None,
    }


@router.get("/jobs")
def list_jobs(admin: CurrentUser = Depends(require_admin), status_filter: str | None = None):
    query = {"status": status_filter} if status_filter else {}
    rows = list(db.jobs().find(query).sort("created_at", -1).limit(100))
    return {"jobs": [db.serialize(row) for row in rows]}


@router.get("/audit-logs")
def list_audit_logs(admin: CurrentUser = Depends(require_admin), limit: int = 100):
    rows = list(db.audit_logs().find().sort("created_at", -1).limit(min(limit, 500)))
    return {"audit_logs": [db.serialize(row) for row in rows]}


@router.get("/evaluations")
def list_evaluations(admin: CurrentUser = Depends(require_admin)):
    rows = list(db.evaluation_runs().find({}, {"records": 0}).sort("created_at", -1).limit(30))
    return {"evaluations": [db.serialize(row) for row in rows]}


@router.get("/evaluations/{run_id}")
def get_evaluation(run_id: str, admin: CurrentUser = Depends(require_admin)):
    run = db.evaluation_runs().find_one({"_id": db.oid(run_id)})
    if not run:
        raise HTTPException(status_code=404, detail="Evaluation run not found")
    return db.serialize(run)


@router.post("/evaluations/run")
async def trigger_evaluation(admin: CurrentUser = Depends(require_admin), dataset: str = "default"):
    audit("evaluation.run", admin.id, dataset=dataset)
    try:
        report = await asyncio.to_thread(run_evaluation, dataset)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    report["records"] = report.get("records", [])[:50]
    return report
