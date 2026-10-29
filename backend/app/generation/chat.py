from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncIterator

from .. import db
from ..config import get_settings
from ..retrieval.index import search
from ..security import CurrentUser
from .answer import extractive_answer
from .citations import ABSTAIN_PREFIX, build_citations, coverage_summary, verify_support
from .prompts import build_answer_messages
from .providers import ProviderError, get_provider, provider_status

log = logging.getLogger("docuchat.chat")

ABSTAIN_TEXT = (
    "I couldn't find enough information in the uploaded document to answer that reliably.\n\n"
    "Try a narrower question, or confirm that the relevant document is selected."
)


def _excerpt(text: str, limit: int = 340) -> str:
    clean = " ".join((text or "").split())
    return clean if len(clean) <= limit else clean[: limit - 1].rstrip() + "…"


def sources_payload(result: dict) -> list[dict]:
    sources = []
    for index, passage in enumerate(result.get("selected") or [], start=1):
        sources.append(
            {
                "label": passage.get("citation_label") or f"S{index}",
                "document_id": passage["document_id"],
                "document_title": passage["document_title"],
                "page_number": passage["page_number"],
                "page_count": passage.get("page_count"),
                "section_path": passage.get("section_path") or "",
                "heading": passage.get("heading") or "",
                "chunk_id": passage.get("chunk_id"),
                "excerpt": _excerpt(passage.get("text", "")),
                "text": passage.get("text", "")[:2000],
                "extraction_method": passage.get("extraction_method"),
                "chunk_kind": passage.get("chunk_kind"),
                "score": passage.get("rerank_score"),
                "confidence": passage.get("confidence"),
            }
        )
    return sources


def _history(session_id, exclude_message_id=None) -> list[dict]:
    query = {"session_id": db.oid(session_id), "role": {"$in": ["user", "assistant"]}, "is_current": {"$ne": False}}
    if exclude_message_id:
        query["_id"] = {"$ne": exclude_message_id}
    rows = list(db.messages().find(query).sort("created_at", -1).limit(8))
    rows.reverse()
    return [{"role": row["role"], "content": row.get("content", "")} for row in rows if row.get("content")]


def _chunk_text(text: str, size: int = 28) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


def _set_title(session: dict, question: str) -> None:
    if session.get("title_generated"):
        return
    title = " ".join(question.split())[:70].strip()
    if not title:
        return
    db.sessions().update_one(
        {"_id": session["_id"]},
        {"$set": {"title": title, "title_generated": True, "updated_at": db.utcnow()}},
    )
    session["title"] = title
    session["title_generated"] = True


def _analyze(
    answer: str,
    selected: list[dict],
    authorized_doc_ids: list[str],
) -> tuple[list[dict], list[dict], dict]:
    citations, claims = build_citations(answer, selected, authorized_doc_ids)
    return citations, claims, coverage_summary(citations, claims)


async def run_turn(
    session: dict,
    user: CurrentUser,
    question: str,
    regenerate_of: str | None = None,
) -> AsyncIterator[tuple[str, dict]]:
    started = time.perf_counter()
    settings = get_settings()
    session_id = session["_id"]
    authorized = [str(doc_id) for doc_id in session.get("document_ids", [])]
    authorized_docs = list(
        db.documents().find(
            {"_id": {"$in": [db.oid(d) for d in authorized]}, "user_id": db.oid(user.id), "deleted": {"$ne": True}}
        )
    )
    authorized = [str(document["_id"]) for document in authorized_docs]
    if not authorized:
        yield "error", {"message": "This conversation has no available documents. Add a document to the scope first."}
        return

    previous_assistant = None
    if regenerate_of:
        previous_assistant = db.messages().find_one(
            {"_id": db.oid(regenerate_of), "session_id": session_id, "role": "assistant"}
        )
        if not previous_assistant:
            yield "error", {"message": "The message to regenerate was not found."}
            return
        source_user = db.messages().find_one({"_id": previous_assistant.get("reply_to")}) if previous_assistant.get("reply_to") else None
        if not source_user:
            yield "error", {"message": "The original question for this answer was not found."}
            return
        question = source_user["content"]
        user_message_id = source_user["_id"]
        db.messages().update_one(
            {"_id": previous_assistant["_id"]},
            {"$set": {"is_current": False, "status": "superseded"}},
        )
    else:
        user_message = {
            "session_id": session_id,
            "user_id": db.oid(user.id),
            "role": "user",
            "content": question,
            "citations": [],
            "is_current": True,
            "created_at": db.utcnow(),
        }
        user_message_id = db.messages().insert_one(user_message).inserted_id
        _set_title(session, question)

    db.sessions().update_one({"_id": session_id}, {"$set": {"updated_at": db.utcnow()}})

    yield "status", {"stage": "retrieving", "message": "Searching documents"}
    try:
        retrieval = await asyncio.to_thread(search, question, authorized, user.id)
    except Exception as exc:
        log.exception("retrieval failed")
        yield "error", {"message": f"Retrieval failed: {exc}"}
        return

    sources = sources_payload(retrieval)
    provider = get_provider()
    extractive = provider is None
    provider_info = provider_status()
    model_name = provider.model if provider else "grounded-extractive-v1"

    yield "retrieval", {
        "sources": sources,
        "confidence": retrieval.get("confidence", 0.0),
        "sufficient": retrieval.get("sufficient", False),
        "mode": retrieval.get("mode"),
        "diagnostics": retrieval.get("diagnostics", {}),
    }

    assistant = {
        "session_id": session_id,
        "user_id": db.oid(user.id),
        "role": "assistant",
        "content": "",
        "citations": [],
        "claims": [],
        "coverage": None,
        "status": "streaming",
        "reply_to": user_message_id,
        "provider": provider_info.get("provider"),
        "model": model_name,
        "retrieval": {
            "sources": sources,
            "confidence": retrieval.get("confidence", 0.0),
            "sufficient": retrieval.get("sufficient", False),
            "mode": retrieval.get("mode"),
            "diagnostics": retrieval.get("diagnostics", {}),
        },
        "is_current": True,
        "created_at": db.utcnow(),
    }
    assistant_id = db.messages().insert_one(assistant).inserted_id

    yield "start", {
        "message_id": str(assistant_id),
        "provider": assistant["provider"],
        "model": model_name,
        "mode": "extractive" if extractive else "generative",
        "sufficient": retrieval.get("sufficient", False),
    }

    collected = ""
    generation_error: str | None = None
    fallback_used = False

    try:
        if extractive:
            answer_text, abstained = await asyncio.to_thread(extractive_answer, question, retrieval)
            for piece in _chunk_text(answer_text):
                collected += piece
                yield "delta", {"text": piece}
                await asyncio.sleep(0)
        elif not retrieval.get("sufficient"):
            for piece in _chunk_text(ABSTAIN_TEXT):
                collected += piece
                yield "delta", {"text": piece}
                await asyncio.sleep(0)
        else:
            history = _history(session_id, exclude_message_id=previous_assistant["_id"] if previous_assistant else None)
            messages = build_answer_messages(question, retrieval["selected"], history)
            try:
                async for token in provider.stream(messages):
                    collected += token
                    yield "delta", {"text": token}
            except ProviderError as exc:
                if collected.strip():
                    generation_error = str(exc)
                else:
                    fallback_used = True
                    generation_error = str(exc)
                    answer_text, _ = await asyncio.to_thread(extractive_answer, question, retrieval)
                    for piece in _chunk_text(answer_text):
                        collected += piece
                        yield "delta", {"text": piece}
                        await asyncio.sleep(0)

        citations, claims, coverage = _analyze(collected, retrieval.get("selected", []), authorized)
        citations = await verify_support(
            citations,
            retrieval.get("selected", []),
            provider if not extractive else None,
            settings.enable_support_verification,
            extractive=extractive,
        )
        coverage = coverage_summary(citations, claims)
        abstained = collected.strip().startswith(ABSTAIN_PREFIX) or (
            retrieval.get("sufficient") is False and not collected.strip()
        )

        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        status_value = "abstained" if abstained else "complete"
        if generation_error and not fallback_used:
            status_value = "incomplete"

        db.messages().update_one(
            {"_id": assistant_id},
            {
                "$set": {
                    "content": collected,
                    "citations": citations,
                    "claims": claims,
                    "coverage": coverage,
                    "status": status_value,
                    "abstained": abstained,
                    "latency_ms": latency_ms,
                    "tokens_estimated": max(1, len(collected) // 4),
                    "provider": "extractive-fallback" if fallback_used else (provider_info.get("provider") if provider else "extractive"),
                    "model": model_name,
                    "generation_error": generation_error,
                    "completed_at": db.utcnow(),
                }
            },
        )
        db.usage().insert_one(
            {
                "user_id": db.oid(user.id),
                "session_id": session_id,
                "kind": "chat",
                "provider": "extractive" if extractive else provider_info.get("provider"),
                "model": model_name,
                "completion_tokens": max(1, len(collected) // 4),
                "prompt_tokens": max(1, sum(len(p.get("text", "")) for p in retrieval.get("selected", [])) // 4),
                "latency_ms": latency_ms,
                "created_at": db.utcnow(),
            }
        )

        yield "citations", {
            "message_id": str(assistant_id),
            "citations": citations,
            "claims": claims,
            "coverage": coverage,
        }
        yield "done", {
            "message_id": str(assistant_id),
            "latency_ms": latency_ms,
            "provider": assistant["provider"],
            "model": model_name,
            "mode": "extractive" if extractive else "generative",
            "abstained": abstained,
            "coverage": coverage,
            "generation_error": generation_error,
            "status": status_value,
        }
    except asyncio.CancelledError:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        citations, claims, coverage = _analyze(collected, retrieval.get("selected", []), authorized)
        db.messages().update_one(
            {"_id": assistant_id},
            {
                "$set": {
                    "content": collected,
                    "citations": citations,
                    "claims": claims,
                    "coverage": coverage,
                    "status": "cancelled",
                    "latency_ms": latency_ms,
                    "completed_at": db.utcnow(),
                }
            },
        )
        raise
    except Exception as exc:
        log.exception("generation failed")
        db.messages().update_one(
            {"_id": assistant_id},
            {
                "$set": {
                    "content": collected,
                    "status": "failed",
                    "generation_error": str(exc),
                    "completed_at": db.utcnow(),
                }
            },
        )
        yield "error", {"message": f"Answer generation failed: {exc}"}
