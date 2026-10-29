from __future__ import annotations

from fastapi import APIRouter, Depends

from .. import db
from ..config import get_settings
from ..generation.providers import provider_status
from ..retrieval.embeddings import embedder_status
from ..security import CurrentUser, get_current_user

router = APIRouter(prefix="/system", tags=["system"])


def _redis_ok() -> bool:
    try:
        import redis

        return bool(redis.Redis.from_url(get_settings().redis_url, socket_connect_timeout=0.5).ping())
    except Exception:
        return False


@router.get("/status")
def status(user: CurrentUser = Depends(get_current_user)):
    settings = get_settings()
    try:
        mongo_ok = bool(db.client().admin.command("ping"))
    except Exception:
        mongo_ok = False
    return {
        "app": settings.app_name,
        "environment": settings.environment,
        "mongo": mongo_ok,
        "redis": _redis_ok(),
        "embedder": embedder_status(),
        "provider": provider_status(),
        "limits": {
            "max_upload_mb": settings.max_upload_mb,
            "max_pages": settings.max_pages,
            "uploads_per_hour": settings.uploads_per_hour,
            "chats_per_hour": settings.chats_per_hour,
            "retention_days": settings.retention_days,
            "min_retrieval_confidence": settings.min_retrieval_confidence,
        },
        "retrieval": {
            "mode": "hybrid (dense + BM25 + RRF + rerank)" if settings.enable_rerank else "hybrid (dense + BM25 + RRF)",
            "top_k": settings.retrieval_top_k,
            "rerank_top_n": settings.rerank_top_n,
            "vector_weight": settings.vector_weight,
            "bm25_weight": settings.bm25_weight,
            "support_verification": settings.enable_support_verification,
        },
        "user": {"id": user.id, "role": user.role},
    }
