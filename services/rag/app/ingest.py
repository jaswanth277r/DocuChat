import uuid
import fitz  # PyMuPDF
from qdrant_client import models
from .config import COLLECTION, MAX_PAGES
from .store import qdrant, docs, embedder, delete_document_vectors

def chunk_page(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    """Paragraph-aware chunks that never cross a page, so citations stay page-exact."""
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if cur and len(cur) + len(p) > size:
            chunks.append(cur)
            cur = cur[-overlap:] + "\n" + p
        else:
            cur = f"{cur}\n\n{p}" if cur else p
        while len(cur) > size * 2:  # very long paragraph
            chunks.append(cur[:size]); cur = cur[size - overlap:]
    if cur.strip():
        chunks.append(cur)
    return chunks

def page_text(page) -> str:
    """Tables become 'Label | value | Label | value' rows so fields stay paired with their values."""
    rows = []
    try:
        for t in page.find_tables().tables:
            for row in t.extract():
                cells = [(c or "").replace("\n", " ").strip() for c in row]
                cells = [c for c in cells if c]
                if cells:
                    rows.append(" | ".join(cells))
    except Exception:
        pass
    body = page.get_text("text", sort=True)
    return ("\n".join(rows) + "\n\n" + body) if rows else body

def _fail(doc_id: str, msg: str):
    docs.update_one({"_id": doc_id}, {"$set": {"status": "failed", "error": msg}})

def ingest_document(doc_id: str, owner_id: str, path: str, filename: str):
    docs.update_one({"_id": doc_id}, {"$set": {"status": "processing", "error": None}})
    try:
        pdf = fitz.open(path)
        if pdf.needs_pass:
            return _fail(doc_id, "This PDF is password-protected. Upload an unprotected copy.")
        if pdf.page_count > MAX_PAGES:
            return _fail(doc_id, f"This PDF has {pdf.page_count} pages; the limit is {MAX_PAGES}.")
        items = []  # (page_number, text)
        for i, page in enumerate(pdf, start=1):  # page 1 = first physical page
            for c in chunk_page(page_text(page)):
                items.append((i, c))
        if sum(len(t.split()) for _, t in items) < 30:
            return _fail(doc_id, "No readable text found. This looks like a scanned PDF; OCR is not enabled yet.")

        delete_document_vectors(doc_id)  # idempotent re-runs
        vectors = list(embedder().embed([t for _, t in items], batch_size=32))
        points = [models.PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, f"{doc_id}:{n}")),
            vector=v.tolist(),
            payload={"owner_id": owner_id, "document_id": doc_id, "filename": filename,
                     "page": page, "text": text})
            for n, ((page, text), v) in enumerate(zip(items, vectors))]
        for i in range(0, len(points), 128):
            qdrant.upsert(COLLECTION, points[i:i + 128])
        docs.update_one({"_id": doc_id}, {"$set": {
            "status": "indexed", "page_count": pdf.page_count, "chunk_count": len(points)}})
    except Exception as e:  # corrupted file, embedding failure, etc.
        _fail(doc_id, f"Processing failed: {type(e).__name__}")
