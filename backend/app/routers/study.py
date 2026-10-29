from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..config import get_settings
from ..generation.study import generate_flashcards, generate_guide, generate_quiz, grade_quiz
from ..models import QuizSubmit, StudyRequest
from ..security import CurrentUser, check_rate_limit, get_current_user

router = APIRouter(tags=["study"])


def _owned_document(document_id: str, user: CurrentUser) -> dict:
    document = db.documents().find_one(
        {"_id": db.oid(document_id), "user_id": db.oid(user.id), "deleted": {"$ne": True}}
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    if document.get("status") != "ready":
        raise HTTPException(status_code=409, detail="This document is not ready yet")
    return document


def _owned_quiz(quiz_id: str, user: CurrentUser) -> dict:
    quiz = db.quizzes().find_one({"_id": db.oid(quiz_id), "user_id": db.oid(user.id)})
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return quiz


def _public_quiz(quiz: dict, include_answers: bool = True) -> dict:
    out = db.serialize(quiz) or {}
    out.pop("user_id", None)
    if not include_answers:
        out["questions"] = [
            {key: value for key, value in question.items() if key not in {"answer", "explanation"}}
            for question in out.get("questions") or []
        ]
    return out


@router.post("/documents/{document_id}/study-guides")
async def create_study_guide(
    document_id: str, payload: StudyRequest | None = None, user: CurrentUser = Depends(get_current_user)
):
    check_rate_limit("study", user.id, limit=40)
    document = _owned_document(document_id, user)
    try:
        return await generate_guide(document, user, payload.focus if payload else None)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/documents/{document_id}/study-guides")
def get_study_guide(document_id: str, user: CurrentUser = Depends(get_current_user)):
    _owned_document(document_id, user)
    guide = db.study_guides().find_one(
        {"document_id": db.oid(document_id), "user_id": db.oid(user.id)}, sort=[("created_at", -1)]
    )
    if not guide:
        raise HTTPException(status_code=404, detail="No study guide yet")
    out = db.serialize(guide) or {}
    out.pop("user_id", None)
    return out


@router.post("/documents/{document_id}/flashcards")
async def create_flashcards(
    document_id: str, payload: StudyRequest | None = None, user: CurrentUser = Depends(get_current_user)
):
    check_rate_limit("study", user.id, limit=40)
    document = _owned_document(document_id, user)
    count = payload.count if payload else 12
    focus = payload.focus if payload else None
    try:
        return {"flashcards": await generate_flashcards(document, user, focus, count)}
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/documents/{document_id}/flashcards")
def list_flashcards(document_id: str, user: CurrentUser = Depends(get_current_user)):
    _owned_document(document_id, user)
    rows = list(
        db.flashcards()
        .find({"document_id": db.oid(document_id), "user_id": db.oid(user.id)})
        .sort("created_at", 1)
    )
    out = []
    for row in rows:
        item = db.serialize(row) or {}
        item.pop("user_id", None)
        out.append(item)
    return {"flashcards": out}


@router.patch("/flashcards/{card_id}")
def update_flashcard(card_id: str, payload: dict, user: CurrentUser = Depends(get_current_user)):
    card = db.flashcards().find_one({"_id": db.oid(card_id), "user_id": db.oid(user.id)})
    if not card:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    update = {}
    for field in ("front", "back", "status"):
        if payload.get(field) is not None:
            update[field] = str(payload[field])[:1200]
    if update.get("status") not in {None, "new", "known", "difficult"}:
        raise HTTPException(status_code=422, detail="Invalid status")
    if update:
        db.flashcards().update_one({"_id": card["_id"]}, {"$set": update})
    updated = db.flashcards().find_one({"_id": card["_id"]})
    out = db.serialize(updated) or {}
    out.pop("user_id", None)
    return out


@router.delete("/flashcards/{card_id}")
def delete_flashcard(card_id: str, user: CurrentUser = Depends(get_current_user)):
    result = db.flashcards().delete_one({"_id": db.oid(card_id), "user_id": db.oid(user.id)})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Flashcard not found")
    return {"ok": True}


@router.post("/documents/{document_id}/quizzes")
async def create_quiz(
    document_id: str, payload: StudyRequest | None = None, user: CurrentUser = Depends(get_current_user)
):
    check_rate_limit("study", user.id, limit=40)
    document = _owned_document(document_id, user)
    count = payload.count if payload else 8
    difficulty = payload.difficulty if payload else "intermediate"
    if difficulty not in {"beginner", "intermediate", "advanced", "exam"}:
        raise HTTPException(status_code=422, detail="Difficulty must be beginner, intermediate, advanced, or exam")
    try:
        return await generate_quiz(document, user, count, difficulty)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/documents/{document_id}/quizzes")
def list_quizzes(document_id: str, user: CurrentUser = Depends(get_current_user)):
    _owned_document(document_id, user)
    rows = list(
        db.quizzes().find({"document_id": db.oid(document_id), "user_id": db.oid(user.id)}).sort("created_at", -1)
    )
    return {"quizzes": [_public_quiz(row, include_answers=False) for row in rows]}


@router.get("/quizzes/{quiz_id}")
def get_quiz(quiz_id: str, user: CurrentUser = Depends(get_current_user)):
    return _public_quiz(_owned_quiz(quiz_id, user))


@router.post("/quizzes/{quiz_id}/attempts")
def submit_attempt(quiz_id: str, payload: QuizSubmit, user: CurrentUser = Depends(get_current_user)):
    quiz = _owned_quiz(quiz_id, user)
    result = grade_quiz(quiz, payload.answers)
    attempt = {
        "quiz_id": quiz["_id"],
        "user_id": db.oid(user.id),
        "document_id": quiz.get("document_id"),
        "answers": payload.answers,
        "result": result,
        "created_at": db.utcnow(),
    }
    attempt_id = db.quiz_attempts().insert_one(attempt).inserted_id
    db.quizzes().update_one(
        {"_id": quiz["_id"]},
        {"$set": {"last_attempt_at": db.utcnow()}, "$inc": {"attempt_count": 1}},
    )
    db.usage().insert_one(
        {
            "user_id": db.oid(user.id),
            "kind": "quiz_attempt",
            "completion_tokens": 0,
            "prompt_tokens": 0,
            "latency_ms": 0,
            "created_at": db.utcnow(),
        }
    )
    return {"attempt_id": str(attempt_id), "quiz_id": quiz_id, **result}


@router.get("/quizzes/{quiz_id}/attempts")
def list_attempts(quiz_id: str, user: CurrentUser = Depends(get_current_user)):
    quiz = _owned_quiz(quiz_id, user)
    rows = list(
        db.quiz_attempts()
        .find({"quiz_id": quiz["_id"], "user_id": db.oid(user.id)})
        .sort("created_at", -1)
        .limit(20)
    )
    return {"attempts": [db.serialize(row) for row in rows]}


@router.get("/study/progress")
def study_progress(user: CurrentUser = Depends(get_current_user)):
    settings = get_settings()
    flashcards = list(db.flashcards().find({"user_id": db.oid(user.id)}))
    attempts = list(db.quiz_attempts().find({"user_id": db.oid(user.id)}).sort("created_at", -1).limit(50))
    known = sum(1 for card in flashcards if card.get("status") == "known")
    difficult = sum(1 for card in flashcards if card.get("status") == "difficult")
    scores = [attempt["result"]["score"] for attempt in attempts if attempt.get("result")]
    return {
        "flashcards": len(flashcards),
        "known": known,
        "difficult": difficult,
        "quiz_attempts": len(attempts),
        "average_score": round(sum(scores) / len(scores), 3) if scores else None,
        "recent_attempts": [db.serialize(attempt) for attempt in attempts[:5]],
        "retention_days": settings.retention_days,
    }
