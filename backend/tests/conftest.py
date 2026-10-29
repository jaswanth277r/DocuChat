from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["MONGO_DB"] = "docuchat_test"
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["LLM_PROVIDER"] = "extractive"
os.environ["EMBED_PROVIDER"] = "fastembed"
os.environ["EMBED_CACHE_DIR"] = str(ROOT / "data" / "models")
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="docuchat-test-")
os.environ["RETENTION_DAYS"] = "30"

import pytest
from bson import ObjectId
from pymongo import MongoClient

from app import db
from app.ingestion.pipeline import ingest_document
from app.security import CurrentUser, hash_password
from app.storage import upload_path

FIXTURES = ROOT / "evaluation" / "fixtures"


@pytest.fixture(scope="session", autouse=True)
def database():
    client = MongoClient("mongodb://127.0.0.1:27017", serverSelectionTimeoutMS=3000)
    client.drop_database("docuchat_test")
    db.ensure_indexes()
    yield
    client.drop_database("docuchat_test")


def _create_user(email: str, name: str) -> ObjectId:
    user_id = db.users().insert_one(
        {
            "email": email,
            "name": name,
            "password_hash": hash_password("test-password-123"),
            "role": "student",
            "created_at": db.utcnow(),
        }
    ).inserted_id
    return user_id


def _ingest(user_id: ObjectId, filename: str, key: str) -> dict:
    source = FIXTURES / filename
    document_id = ObjectId()
    shutil.copyfile(source, upload_path(str(document_id)))
    db.documents().insert_one(
        {
            "_id": document_id,
            "user_id": user_id,
            "original_name": filename,
            "title": source.stem.replace("_", " ").title(),
            "status": "queued",
            "progress": 0,
            "category_locked": False,
            "warnings": [],
            "deleted": False,
            "ingest_version": 0,
            "created_at": db.utcnow(),
            "updated_at": db.utcnow(),
        }
    )
    ingest_document(str(document_id), str(user_id), lambda *args: None)
    record = db.documents().find_one({"_id": document_id})
    record["fixture_key"] = key
    return record


@pytest.fixture(scope="session")
def corpus():
    owner_id = _create_user("owner@test.local", "Owner")
    notes = _ingest(owner_id, "transformer_notes.pdf", "notes")
    report = _ingest(owner_id, "retrieval_report.pdf", "report")
    return {
        "owner_id": str(owner_id),
        "notes": notes,
        "report": report,
        "out": str(owner_id),
    }


@pytest.fixture(scope="session")
def owner(corpus) -> CurrentUser:
    return CurrentUser(id=corpus["owner_id"], email="owner@test.local", name="Owner", role="student")


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)
