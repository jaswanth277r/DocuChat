from functools import lru_cache
from fastembed import TextEmbedding
from pymongo import MongoClient
from qdrant_client import QdrantClient, models
from .config import *

qdrant = QdrantClient(url=QDRANT_URL)
docs = MongoClient(MONGO_URL)["docuchat"]["documents"]

@lru_cache(maxsize=1)
def embedder() -> TextEmbedding:
    return TextEmbedding(EMBED_MODEL)

def ensure_collection():
    if not qdrant.collection_exists(COLLECTION):
        qdrant.create_collection(COLLECTION, vectors_config=models.VectorParams(
            size=EMBED_DIM, distance=models.Distance.COSINE))
    for f in ("owner_id", "document_id"):
        qdrant.create_payload_index(COLLECTION, f, models.PayloadSchemaType.KEYWORD)

def delete_document_vectors(document_id: str):
    qdrant.delete(COLLECTION, models.FilterSelector(filter=models.Filter(must=[
        models.FieldCondition(key="document_id", match=models.MatchValue(value=document_id))])))
