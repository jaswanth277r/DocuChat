from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from bson import ObjectId  # noqa: E402

from app import db  # noqa: E402
from app.ingestion.pipeline import ingest_document  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.storage import upload_path  # noqa: E402

EMAIL = "demo@docuchat.local"
PASSWORD = "docuchat-demo"
FIXTURES = ROOT / "evaluation" / "fixtures"
DOCUMENTS = {
    "notes": "transformer_notes.pdf",
    "report": "retrieval_report.pdf",
}


def ensure_user() -> ObjectId:
    existing = db.users().find_one({"email": EMAIL})
    if existing:
        db.users().update_one({"_id": existing["_id"]}, {"$set": {"role": "admin", "disabled": False}})
        return existing["_id"]
    user_id = db.users().insert_one(
        {
            "email": EMAIL,
            "name": "Demo Student",
            "password_hash": hash_password(PASSWORD),
            "role": "admin",
            "disabled": False,
            "created_at": db.utcnow(),
        }
    ).inserted_id
    print(f"Created demo user {EMAIL}")
    return user_id


def ensure_document(user_id: ObjectId, key: str, filename: str) -> ObjectId:
    source = FIXTURES / filename
    if not source.exists():
        raise SystemExit(f"Missing fixture {source}. Run: .venv/bin/python scripts/make_fixtures.py")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    existing = db.documents().find_one(
        {"user_id": user_id, "fixture_key": key, "deleted": {"$ne": True}}
    )
    if existing and existing.get("status") == "ready" and existing.get("sha256") == digest:
        print(f"Reusing {filename} ({existing.get('page_count')} pages)")
        return existing["_id"]

    document_id = existing["_id"] if existing else ObjectId()
    target = upload_path(str(document_id))
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    record = {
        "user_id": user_id,
        "original_name": filename,
        "title": source.stem.replace("_", " ").title(),
        "status": "queued",
        "progress": 0,
        "stage_message": "Queued for seeding",
        "size_bytes": source.stat().st_size,
        "sha256": digest,
        "fixture_key": key,
        "category_locked": False,
        "warnings": [],
        "error": None,
        "created_at": db.utcnow(),
        "updated_at": db.utcnow(),
        "deleted": False,
        "ingest_version": 0,
    }
    if existing:
        db.documents().update_one({"_id": document_id}, {"$set": record})
    else:
        record["_id"] = document_id
        db.documents().insert_one(record)
    print(f"Ingesting {filename}…")
    ingest_document(str(document_id), str(user_id), lambda *args: None)
    return document_id


def ensure_collection(user_id: ObjectId, document_ids: list[ObjectId]) -> None:
    name = "Course demo"
    collection = db.collections().find_one({"user_id": user_id, "name": name})
    if not collection:
        collection_id = db.collections().insert_one(
            {
                "user_id": user_id,
                "name": name,
                "description": "Two-document demo collection for multi-PDF questions.",
                "document_ids": document_ids,
                "created_at": db.utcnow(),
                "updated_at": db.utcnow(),
            }
        ).inserted_id
        print(f"Created collection '{name}'")
    else:
        collection_id = collection["_id"]
        db.collections().update_one(
            {"_id": collection_id}, {"$addToSet": {"document_ids": {"$each": document_ids}}}
        )
    db.documents().update_many(
        {"_id": {"$in": document_ids}}, {"$set": {"collection_id": collection_id}}
    )


def main() -> None:
    db.ensure_indexes()
    user_id = ensure_user()
    document_ids = [ensure_document(user_id, key, filename) for key, filename in DOCUMENTS.items()]
    ensure_collection(user_id, document_ids)
    print("\nDemo workspace ready")
    print(f"  email:    {EMAIL}")
    print(f"  password: {PASSWORD}")
    print("  documents: transformer_notes.pdf, retrieval_report.pdf")
    print("  Try asking: compare the recall values reported in both documents")


if __name__ == "__main__":
    main()
