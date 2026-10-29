from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from .. import db
from ..generation.chat import run_turn
from ..models import FeedbackIn, MessageIn, SessionCreate, SessionPatch
from ..security import CurrentUser, audit, check_rate_limit, get_current_user
from ..config import get_settings

router = APIRouter(tags=["chat"])

SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def _owned_session(session_id: str, user: CurrentUser) -> dict:
    session = db.sessions().find_one({"_id": db.oid(session_id), "user_id": db.oid(user.id)})
    if not session:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return session


def _owned_message(message_id: str, user: CurrentUser) -> tuple[dict, dict]:
    message = db.messages().find_one({"_id": db.oid(message_id)})
    if not message:
        raise HTTPException(status_code=404, detail="Message not found")
    session = db.sessions().find_one({"_id": message["session_id"], "user_id": db.oid(user.id)})
    if not session:
        raise HTTPException(status_code=404, detail="Message not found")
    return message, session


def _session_out(session: dict) -> dict:
    out = db.serialize(session) or {}
    out["document_ids"] = [str(doc_id) for doc_id in session.get("document_ids") or []]
    count = db.messages().count_documents({"session_id": session["_id"], "is_current": {"$ne": False}})
    out["message_count"] = count
    return out


def _resolve_scope(payload: SessionCreate | SessionPatch, user: CurrentUser) -> list:
    doc_ids: list[str] = list(payload.document_ids or [])
    if getattr(payload, "collection_id", None):
        collection = db.collections().find_one(
            {"_id": db.oid(payload.collection_id), "user_id": db.oid(user.id)}
        )
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        doc_ids.extend(str(doc_id) for doc_id in collection.get("document_ids") or [])

    unique = []
    seen = set()
    for doc_id in doc_ids:
        if doc_id and doc_id not in seen:
            seen.add(doc_id)
            unique.append(doc_id)
    if not unique:
        raise HTTPException(status_code=422, detail="Select at least one document")

    oids = [db.oid(doc_id) for doc_id in unique]
    documents = list(db.documents().find({"_id": {"$in": oids}, "user_id": db.oid(user.id), "deleted": {"$ne": True}}))
    by_id = {str(doc["_id"]): doc for doc in documents}
    missing = [doc_id for doc_id in unique if doc_id not in by_id]
    if missing:
        raise HTTPException(status_code=404, detail="One or more documents were not found")
    not_ready = [by_id[doc_id].get("title") for doc_id in unique if by_id[doc_id].get("status") != "ready"]
    if not_ready:
        raise HTTPException(
            status_code=409,
            detail=f"Still processing: {', '.join(not_ready)}. Wait until the documents are ready.",
        )
    return [by_id[doc_id]["_id"] for doc_id in unique]


@router.post("/chat/sessions")
def create_session(payload: SessionCreate, user: CurrentUser = Depends(get_current_user)):
    scoped = _resolve_scope(payload, user)
    session = {
        "user_id": db.oid(user.id),
        "document_ids": scoped,
        "title": payload.title or "New chat",
        "title_generated": bool(payload.title),
        "created_at": db.utcnow(),
        "updated_at": db.utcnow(),
    }
    session_id = db.sessions().insert_one(session).inserted_id
    session["_id"] = session_id
    audit("chat.create", user.id, session_id=str(session_id), documents=len(scoped))
    return _session_out(session)


@router.get("/chat/sessions")
def list_sessions(user: CurrentUser = Depends(get_current_user), q: str | None = None):
    query: dict = {"user_id": db.oid(user.id)}
    if q:
        matching_ids = [
            message["session_id"]
            for message in db.messages()
            .find({"content": {"$regex": q, "$options": "i"}}, {"session_id": 1})
            .limit(300)
        ]
        query["$or"] = [{"title": {"$regex": q, "$options": "i"}}, {"_id": {"$in": matching_ids}}]
    rows = list(db.sessions().find(query).sort("updated_at", -1).limit(100))
    return {"sessions": [_session_out(row) for row in rows]}


@router.get("/chat/sessions/{session_id}")
def get_session(session_id: str, user: CurrentUser = Depends(get_current_user)):
    session = _owned_session(session_id, user)
    messages = list(
        db.messages()
        .find({"session_id": session["_id"], "is_current": {"$ne": False}})
        .sort("created_at", 1)
    )
    documents = list(
        db.documents().find({"_id": {"$in": session.get("document_ids") or []}})
    )
    return {
        "session": _session_out(session),
        "messages": [db.serialize(message) for message in messages],
        "documents": [
            {
                "id": str(doc["_id"]),
                "title": doc.get("title"),
                "page_count": doc.get("page_count"),
                "status": doc.get("status"),
            }
            for doc in documents
        ],
    }


@router.patch("/chat/sessions/{session_id}")
def patch_session(session_id: str, payload: SessionPatch, user: CurrentUser = Depends(get_current_user)):
    session = _owned_session(session_id, user)
    update: dict = {"updated_at": db.utcnow()}
    if payload.title is not None:
        update["title"] = payload.title.strip()[:200]
        update["title_generated"] = True
    if payload.document_ids is not None or payload.collection_id:
        update["document_ids"] = _resolve_scope(payload, user)
    db.sessions().update_one({"_id": session["_id"]}, {"$set": update})
    return _session_out(_owned_session(session_id, user))


@router.delete("/chat/sessions/{session_id}")
def delete_session(session_id: str, user: CurrentUser = Depends(get_current_user)):
    session = _owned_session(session_id, user)
    db.messages().delete_many({"session_id": session["_id"]})
    db.sessions().delete_one({"_id": session["_id"]})
    audit("chat.delete", user.id, session_id=session_id)
    return {"ok": True}


async def _sse(events: AsyncIterator[tuple[str, dict]]) -> AsyncIterator[str]:
    try:
        async for event, data in events:
            yield f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # keep the stream well-formed on unexpected failures
        yield f"event: error\ndata: {json.dumps({'message': str(exc)})}\n\n"


@router.post("/chat/sessions/{session_id}/messages")
async def post_message(session_id: str, payload: MessageIn, user: CurrentUser = Depends(get_current_user)):
    settings = get_settings()
    check_rate_limit("chat", user.id, limit=settings.chats_per_hour)
    session = _owned_session(session_id, user)
    if not (session.get("document_ids") or []):
        raise HTTPException(status_code=409, detail="This conversation has no documents in scope")
    generator = run_turn(session, user, payload.content.strip())
    return StreamingResponse(_sse(generator), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat/sessions/{session_id}/messages/{message_id}/regenerate")
async def regenerate_message(session_id: str, message_id: str, user: CurrentUser = Depends(get_current_user)):
    settings = get_settings()
    check_rate_limit("chat", user.id, limit=settings.chats_per_hour)
    session = _owned_session(session_id, user)
    message, _ = _owned_message(message_id, user)
    if str(message["session_id"]) != str(session["_id"]) or message.get("role") != "assistant":
        raise HTTPException(status_code=400, detail="Only assistant messages can be regenerated")
    generator = run_turn(session, user, "", regenerate_of=message_id)
    return StreamingResponse(_sse(generator), media_type="text/event-stream", headers=SSE_HEADERS)


@router.post("/chat/messages/{message_id}/feedback")
def message_feedback(message_id: str, payload: FeedbackIn, user: CurrentUser = Depends(get_current_user)):
    message, _ = _owned_message(message_id, user)
    db.messages().update_one(
        {"_id": message["_id"]},
        {"$set": {"feedback": {"rating": payload.rating, "comment": payload.comment, "at": db.utcnow()}}},
    )
    db.reviews().update_one(
        {"message_id": message["_id"], "user_id": db.oid(user.id)},
        {
            "$set": {
                "rating": payload.rating,
                "comment": payload.comment,
                "updated_at": db.utcnow(),
            },
            "$setOnInsert": {"created_at": db.utcnow()},
        },
        upsert=True,
    )
    return {"ok": True}


@router.get("/messages/{message_id}/citations")
def message_citations(message_id: str, user: CurrentUser = Depends(get_current_user)):
    message, _ = _owned_message(message_id, user)
    return {
        "message_id": message_id,
        "citations": message.get("citations") or [],
        "coverage": message.get("coverage"),
        "claims": message.get("claims") or [],
    }


@router.get("/chat/sessions/{session_id}/export")
def export_session(session_id: str, user: CurrentUser = Depends(get_current_user)):
    session = _owned_session(session_id, user)
    messages = list(
        db.messages().find({"session_id": session["_id"], "is_current": {"$ne": False}}).sort("created_at", 1)
    )
    lines = [f"# {session.get('title', 'DocuChat conversation')}", ""]
    for message in messages:
        role = "You" if message["role"] == "user" else "DocuChat"
        lines.append(f"**{role}**")
        lines.append(message.get("content", ""))
        for citation in message.get("citations") or []:
            title = citation.get("document_title") or "Document"
            page = citation.get("page_number")
            lines.append(f"- Source: {title}, page {page} — \"{citation.get('excerpt', '')}\"")
        lines.append("")
    return StreamingResponse(
        iter(["\n".join(lines)]),
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="docuchat-{session_id}.md"'},
    )
