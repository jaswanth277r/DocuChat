from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from .. import db
from ..models import CollectionDocsIn, CollectionIn
from ..security import CurrentUser, audit, get_current_user

router = APIRouter(prefix="/collections", tags=["collections"])


def _owned(collection_id: str, user: CurrentUser) -> dict:
    collection = db.collections().find_one({"_id": db.oid(collection_id), "user_id": db.oid(user.id)})
    if not collection:
        raise HTTPException(status_code=404, detail="Collection not found")
    return collection


def _out(collection: dict) -> dict:
    document_ids = collection.get("document_ids") or []
    count = db.documents().count_documents(
        {"_id": {"$in": document_ids}, "deleted": {"$ne": True}}
    ) if document_ids else 0
    out = db.serialize(collection) or {}
    out["document_count"] = count
    return out


@router.post("")
def create_collection(payload: CollectionIn, user: CurrentUser = Depends(get_current_user)):
    existing = db.collections().find_one({"user_id": db.oid(user.id), "name": payload.name.strip()})
    if existing:
        raise HTTPException(status_code=409, detail="A collection with that name already exists")
    collection = {
        "user_id": db.oid(user.id),
        "name": payload.name.strip(),
        "description": payload.description,
        "document_ids": [],
        "created_at": db.utcnow(),
        "updated_at": db.utcnow(),
    }
    collection_id = db.collections().insert_one(collection).inserted_id
    collection["_id"] = collection_id
    audit("collection.create", user.id, collection_id=str(collection_id))
    return _out(collection)


@router.get("")
def list_collections(user: CurrentUser = Depends(get_current_user)):
    rows = db.collections().find({"user_id": db.oid(user.id)}).sort("created_at", -1)
    return {"collections": [_out(row) for row in rows]}


@router.patch("/{collection_id}")
def rename_collection(collection_id: str, payload: CollectionIn, user: CurrentUser = Depends(get_current_user)):
    collection = _owned(collection_id, user)
    db.collections().update_one(
        {"_id": collection["_id"]},
        {"$set": {"name": payload.name.strip(), "description": payload.description, "updated_at": db.utcnow()}},
    )
    return _out(_owned(collection_id, user))


@router.delete("/{collection_id}")
def delete_collection(collection_id: str, user: CurrentUser = Depends(get_current_user)):
    collection = _owned(collection_id, user)
    db.documents().update_many(
        {"_id": {"$in": collection.get("document_ids") or []}}, {"$set": {"collection_id": None}}
    )
    db.collections().delete_one({"_id": collection["_id"]})
    audit("collection.delete", user.id, collection_id=collection_id)
    return {"ok": True}


@router.post("/{collection_id}/documents")
def add_documents(collection_id: str, payload: CollectionDocsIn, user: CurrentUser = Depends(get_current_user)):
    collection = _owned(collection_id, user)
    oids = [db.oid(doc_id) for doc_id in payload.document_ids if db.oid(doc_id)]
    owned = list(db.documents().find({"_id": {"$in": oids}, "user_id": db.oid(user.id), "deleted": {"$ne": True}}))
    if len(owned) != len(oids):
        raise HTTPException(status_code=404, detail="One or more documents were not found")
    db.collections().update_one(
        {"_id": collection["_id"]},
        {"$addToSet": {"document_ids": {"$each": [doc["_id"] for doc in owned]}}, "$set": {"updated_at": db.utcnow()}},
    )
    db.documents().update_many({"_id": {"$in": [doc["_id"] for doc in owned]}}, {"$set": {"collection_id": collection["_id"]}})
    return _out(_owned(collection_id, user))


@router.delete("/{collection_id}/documents/{document_id}")
def remove_document(collection_id: str, document_id: str, user: CurrentUser = Depends(get_current_user)):
    collection = _owned(collection_id, user)
    db.collections().update_one(
        {"_id": collection["_id"]}, {"$pull": {"document_ids": db.oid(document_id)}, "$set": {"updated_at": db.utcnow()}}
    )
    db.documents().update_one(
        {"_id": db.oid(document_id), "user_id": db.oid(user.id)}, {"$set": {"collection_id": None}}
    )
    return _out(_owned(collection_id, user))
