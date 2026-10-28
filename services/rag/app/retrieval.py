import re
from rank_bm25 import BM25Okapi
from qdrant_client import models
from .config import COLLECTION
from .store import qdrant, embedder

_tok = lambda s: re.findall(r"\w+", s.lower())

def hybrid_search(question: str, owner_id: str, doc_ids: list[str], k: int = 10) -> list[dict]:
    # Authorization lives INSIDE the query filter, never applied afterwards.
    flt = models.Filter(must=[
        models.FieldCondition(key="owner_id", match=models.MatchValue(value=owner_id)),
        models.FieldCondition(key="document_id", match=models.MatchAny(any=doc_ids))])

    qvec = next(iter(embedder().query_embed(question))).tolist()
    dense = qdrant.query_points(COLLECTION, query=qvec, query_filter=flt,
                                limit=20, with_payload=True).points

    corpus, offset = [], None
    while True:
        batch, offset = qdrant.scroll(COLLECTION, scroll_filter=flt, limit=256,
                                      offset=offset, with_payload=True)
        corpus += batch
        if offset is None:
            break
    sparse = []
    if corpus:
        scores = BM25Okapi([_tok(p.payload["text"]) for p in corpus]).get_scores(_tok(question))
        ranked = sorted(zip(corpus, scores), key=lambda x: -x[1])[:20]
        sparse = [p for p, s in ranked if s > 0]

    # Reciprocal Rank Fusion
    fused, by_id = {}, {}
    for ranking in (dense, sparse):
        for rank, p in enumerate(ranking):
            fused[p.id] = fused.get(p.id, 0) + 1 / (60 + rank)
            by_id[p.id] = p.payload
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [by_id[i] for i in top]
