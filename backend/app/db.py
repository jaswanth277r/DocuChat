from __future__ import annotations

import logging
from datetime import datetime, timezone

from bson import ObjectId
from bson.errors import InvalidId
from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

from .config import get_settings

log = logging.getLogger("docuchat.db")

_client: MongoClient | None = None


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def client() -> MongoClient:
    global _client
    if _client is None:
        settings = get_settings()
        _client = MongoClient(settings.mongo_url, serverSelectionTimeoutMS=5000, tz_aware=True)
    return _client


def db() -> Database:
    return client()[get_settings().mongo_db]


def users() -> Collection:
    return db()["users"]


def documents() -> Collection:
    return db()["documents"]


def chunks() -> Collection:
    return db()["document_chunks"]


def pages() -> Collection:
    return db()["document_pages"]


def collections() -> Collection:
    return db()["collections"]


def sessions() -> Collection:
    return db()["chat_sessions"]


def messages() -> Collection:
    return db()["messages"]


def jobs() -> Collection:
    return db()["processing_jobs"]


def study_guides() -> Collection:
    return db()["study_guides"]


def flashcards() -> Collection:
    return db()["flashcards"]


def quizzes() -> Collection:
    return db()["quizzes"]


def quiz_attempts() -> Collection:
    return db()["quiz_attempts"]


def reviews() -> Collection:
    return db()["reviews"]


def audit_logs() -> Collection:
    return db()["audit_logs"]


def usage() -> Collection:
    return db()["usage_records"]


def evaluation_runs() -> Collection:
    return db()["evaluation_runs"]


def oid(value: str | ObjectId | None) -> ObjectId | None:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return value
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        return None


def ensure_indexes() -> None:
    users().create_index("email", unique=True)
    documents().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    documents().create_index("status")
    documents().create_index("fixture_key")
    chunks().create_index([("document_id", ASCENDING), ("index", ASCENDING)], unique=True)
    chunks().create_index([("document_id", ASCENDING), ("page_number", ASCENDING)])
    pages().create_index([("document_id", ASCENDING), ("page_number", ASCENDING)], unique=True)
    collections().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    sessions().create_index([("user_id", ASCENDING), ("updated_at", DESCENDING)])
    messages().create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
    jobs().create_index([("status", ASCENDING), ("created_at", ASCENDING)])
    study_guides().create_index([("document_id", ASCENDING), ("user_id", ASCENDING)])
    flashcards().create_index([("document_id", ASCENDING), ("user_id", ASCENDING)])
    quizzes().create_index([("document_id", ASCENDING), ("user_id", ASCENDING)])
    quiz_attempts().create_index([("quiz_id", ASCENDING), ("created_at", DESCENDING)])
    audit_logs().create_index([("created_at", DESCENDING)])
    usage().create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
    evaluation_runs().create_index([("created_at", DESCENDING)])


def serialize(doc: dict | None) -> dict | None:
    if doc is None:
        return None
    out = {}
    for key, value in doc.items():
        if key == "_id":
            out["id"] = str(value)
        elif isinstance(value, ObjectId):
            out[key] = str(value)
        elif isinstance(value, datetime):
            out[key] = value.isoformat()
        elif isinstance(value, list):
            out[key] = [serialize(v) if isinstance(v, dict) else (str(v) if isinstance(v, ObjectId) else v) for v in value]
        elif isinstance(value, dict):
            out[key] = serialize(value)
        else:
            out[key] = value
    return out


