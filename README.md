# DocuChat

Chat with your PDFs: hybrid search (dense + BM25 with RRF), validated page citations, and a Cloud (Groq) / Local (Ollama) model switch with no silent fallback.

## Run
```bash
cp .env.example .env      # set JWT_SECRET, INTERNAL_TOKEN, GROQ_API_KEY
docker compose --env-file .env up --build   # API on :4000
cd apps/web && npm install && npm run dev   # UI on :5173
```
Local model: install Ollama on the host, `ollama pull llama3.2:3b`, then choose "Local (Ollama)" in the UI.

## Layout
- `services/gateway` Node/Express: auth (JWT), ownership checks, rate limits, PDF validation
- `services/rag` FastAPI: ingestion (PyMuPDF, page-exact chunks), Qdrant + BM25 retrieval, LLM router, citation validation
- `apps/web` React + Vite: library, chat, clickable citations that open the PDF page

## Implemented vs. not yet
Done: auth, private libraries, ingestion with statuses/failure messages, hybrid retrieval with owner/doc filters inside the Qdrant query, JSON-grounded answers, citation validation, retention-ready deletion.
Not yet: shared workspaces/RBAC, OCR for scanned PDFs, Celery/Redis queue + DLQ (ingestion uses FastAPI background tasks), summarize/compare/extract modes, multilingual evaluation, benchmarks, SFT/RLVR/distillation experiments (do these after measuring a baseline).
