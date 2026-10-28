import json, os
from fastapi import FastAPI, BackgroundTasks, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from .config import INTERNAL_TOKEN
from .store import ensure_collection, delete_document_vectors
from .ingest import ingest_document
from .retrieval import hybrid_search
from .llm import generate, LLMError

app = FastAPI(title="DocuChat RAG")

def internal_only(x_internal_token: str = Header("")):
    if not INTERNAL_TOKEN or x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(401, "Unauthorized")

@app.on_event("startup")
def _startup(): ensure_collection()

@app.get("/health")
def health(): return {"ok": True}

class IngestReq(BaseModel):
    document_id: str; owner_id: str; path: str; filename: str

@app.post("/ingest", dependencies=[Depends(internal_only)], status_code=202)
def ingest(req: IngestReq, bg: BackgroundTasks):
    if not os.path.realpath(req.path).startswith("/data/uploads/"):
        raise HTTPException(400, "Invalid path")
    bg.add_task(ingest_document, req.document_id, req.owner_id, req.path, req.filename)
    return {"queued": True}

@app.delete("/documents/{document_id}", dependencies=[Depends(internal_only)])
def remove(document_id: str):
    delete_document_vectors(document_id); return {"deleted": True}

class QueryReq(BaseModel):
    owner_id: str
    document_ids: list[str] = Field(min_length=1, max_length=20)
    question: str = Field(min_length=1, max_length=2000)
    provider: str = "groq"

IDK = "I don't know based on the provided documents."

@app.post("/query", dependencies=[Depends(internal_only)])
def query(req: QueryReq):
    hits = hybrid_search(req.question, req.owner_id, req.document_ids)
    if not hits:
        return {"answer": IDK, "citations": [], "provider": req.provider}
    ctx = "\n\n".join(f"[{i}] ({h['filename']}, page {h['page']})\n{h['text']}" for i, h in enumerate(hits, 1))
    try:
        raw = generate(req.provider, f"SOURCES:\n{ctx}\n\nQUESTION: {req.question}").strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            raw = "\n".join(lines).strip()
        data = json.loads(raw)
        answer = str(data["answer"])
    except LLMError as e:
        raise HTTPException(502, str(e))
    except (ValueError, KeyError, TypeError):
        raise HTTPException(502, "The model returned an unusable response. Try again.")

    # Citation validation: only source numbers we actually supplied are accepted.
    seen, cites, dropped = set(), [], 0
    for n in data.get("citations", []):
        if isinstance(n, int) and 1 <= n <= len(hits) and n not in seen:
            seen.add(n); h = hits[n - 1]
            cites.append({"n": n, "document_id": h["document_id"], "filename": h["filename"],
                          "page": h["page"], "snippet": h["text"][:240]})
        else:
            dropped += 1
    return {"answer": answer, "citations": cites, "dropped_citations": dropped, "provider": req.provider}
