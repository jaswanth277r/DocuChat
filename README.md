# DocuChat

**Understand every document. Verify every answer.**

DocuChat is a working retrieval-augmented document assistant: upload PDFs, ask questions, and click any citation to open the exact page with the supporting passage highlighted. It is built as a modular monolith (FastAPI + MongoDB + Redis + React) with a configurable embedding model and generation provider.

This repository is an implementation, not a mockup. The golden path — upload → parse → embed → hybrid retrieve → answer → cite → verify — runs locally, and the evaluation suite reports its quality.

---

## What is implemented

| Area | Capability |
|---|---|
| Auth | Email/password registration and login, scrypt password hashing, JWT in an HTTP-only cookie, admin/student roles, rate limiting, audit log |
| Ingestion | PDF signature and size validation, encrypted/oversized rejection, PyMuPDF structure parsing (headings, sections, tables, page boundaries), OCR detection (Tesseract when installed), structure-aware chunking with original page numbers |
| Background jobs | Redis-backed queue, processing stages (`validating → extracting → ocr_check → chunking → embedding → indexing → ready`), retries, dead-letter queue, crash recovery, retention cleanup |
| Embeddings | Local neural model (`BAAI/bge-small-en-v1.5` via fastembed, 384 dims), offline hashing fallback, optional OpenAI embeddings |
| Retrieval | Dense vector search + BM25, weighted Reciprocal Rank Fusion, heuristic reranker, context selection with deduplication and page diversity, permission filtering at query time |
| Grounding | Query sanitization against instruction injection, retrieval-confidence and term-presence abstention, claim-level citations resolved server-side, two-layer citation verification, evidence coverage |
| Chat | SSE streaming, stop generation, regenerate, feedback, conversation export, searchable history, editable scope across multiple documents |
| Viewer | Server-rendered PDF pages (PyMuPDF → PNG) with page navigation, zoom, and server-side highlight of the cited sentence |
| Study mode | Cited study guides, flashcards, quizzes with numeric-distractor MCQs; deterministic grading and per-question feedback |
| Evaluation | 12-question labelled suite, Recall@5 / MRR / nDCG, answer accuracy, citation validity and support, abstention rates, latency; CLI runner and admin dashboard |
| Admin | Ingestion metrics, chat latency, abstention, citation validity, queue depth, jobs, evaluation runs, serving configuration |

Not implemented (and not claimed): collaborative workspaces, annotations/highlights authored by users, table charting, a separate research-assistant mode, Qdrant/S3/Celery adapters, and the SFT/RLVR/distillation experiments. See [Known limitations](#known-limitations) and the research-track note below.

---

## Architecture at a glance

```
Browser (React + TypeScript + Tailwind)
        │  fetch / SSE
        ▼
FastAPI application  ────────────────┐
  ├─ auth / documents / collections  │
  ├─ chat streaming + citations      │  Redis: job queue + rate limits
  ├─ study mode                     │
  └─ admin + evaluation             │
        │                            ▼
        ├── MongoDB: users, documents, pages, chunks + vectors,
        │            sessions, messages, jobs, study material,
        │            evaluations, audit log
        ├── Local storage: original PDFs + rendered page cache
        └── Embeddings: fastembed (bge-small) | hashing fallback
              │
              └── Generation: extractive (default) | OpenAI-compatible | Ollama
```

A deliberate deviation from the original microservice plan: identifying durable boundaries matters more than deploying five processes. The ingestion worker, retrieval pipeline, and generation layer are separate modules with explicit interfaces; they can be extracted into services when load justifies it. See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full design and scaling path.

---

## Quick start

### Prerequisites

- Python 3.12, Node.js 20+
- MongoDB and Redis running locally
- ~150 MB for the embedding model (downloaded once)

### 1. Install dependencies

```bash
# Backend (venv + pip cache can be redirected with .env.local)
./scripts/install-backend.sh

# Frontend (installs outside the repo and symlinks node_modules)
./scripts/install-frontend.sh
```

> **Storage note:** npm removes a symlinked `node_modules` when it installs. The install scripts therefore build dependencies in `DOCUCHAT_DEPS_DIR` (outside the repository) and link them in. See [Storage layout](#storage-layout) if your system partition is small.

### 2. Configure

```bash
cp .env.example .env
python -c "import secrets; print('SECRET_KEY=' + secrets.token_urlsafe(48))"  # append/replace in .env
```

Defaults use MongoDB `docuchat` and Redis `127.0.0.1:6379`. Keep `LLM_PROVIDER=extractive` for a key-free local run.

### 3. Seed demo content

```bash
.venv/bin/python scripts/make_fixtures.py
.venv/bin/python scripts/seed_demo.py
```

This creates two fixture PDFs and a demo workspace:

```
email:    demo@docuchat.local
password: docuchat-demo
```

### 4. Run

```bash
# Terminal 1 — API on http://127.0.0.1:8000
./scripts/run-api.sh
# if port 8000 is occupied: PORT=8010 ./scripts/run-api.sh

# Terminal 2 — Vite on http://127.0.0.1:5173
./scripts/run-frontend.sh
```

Production-style single-process run:

```bash
npm --prefix frontend run build     # writes frontend/dist
PORT=8000 ./scripts/run-api.sh      # FastAPI serves the SPA and /api
```

Open `http://127.0.0.1:8000` (or the Vite port). API docs: `http://127.0.0.1:8000/api/docs`.

---

## Configuration

All settings are environment variables (see `.env.example`).

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | required | JWT signing key |
| `MONGO_URL`, `MONGO_DB` | `mongodb://127.0.0.1:27017`, `docuchat` | Application database |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Job queue and rate limits |
| `DATA_DIR` | `./data` | PDFs, page renders, model cache |
| `MAX_UPLOAD_MB`, `MAX_PAGES` | `25`, `500` | Upload limits |
| `RETENTION_DAYS` | `30` | Deletes expired documents and derived data (hourly worker) |
| `UPLOADS_PER_HOUR`, `CHATS_PER_HOUR` | `10`, `120` | Per-user rate limits |
| `EMBED_PROVIDER` | `fastembed` | `fastembed`, `hashing`, or `openai` |
| `EMBED_MODEL` | `BAAI/bge-small-en-v1.5` | Embedding model |
| `LLM_PROVIDER` | `extractive` | `extractive`, `openai` (OpenAI/Groq-compatible), `ollama` |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | — | Generation provider |
| `RETRIEVAL_TOP_K`, `RERANK_TOP_N` | `20`, `5` | Candidate and context sizes |
| `RRF_K`, `VECTOR_WEIGHT`, `BM25_WEIGHT` | `60`, `0.7`, `0.3` | Rank fusion |
| `MIN_RETRIEVAL_CONFIDENCE` | `0.22` | Confidence floor for answering |
| `ENABLE_SUPPORT_VERIFICATION` | `true` | Second-layer citation judging when a model is configured |

### Switching generation providers

```dotenv
# Groq (OpenAI-compatible)
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=gsk_...
LLM_MODEL=llama-3.3-70b-versatile

# Local Ollama
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=qwen2.5:3b-instruct
```

The active provider and model are displayed in the chat header and settings; the UI never claims a local model while calling a cloud API. When no provider is configured, answers are composed from retrieved sentences (verbatim, cited) rather than generated.

---

## Evaluation results

Run:

```bash
cd backend
../.venv/bin/python -m app.evaluation.run --json-out ../evaluation/report.json
```

Latest run (`evaluation/report.json`, extractive answer mode, local bge-small embeddings):

| Metric | Result |
|---|---|
| Questions | 12 (10 answerable, 2 unanswerable) |
| Recall@5 | **1.000** |
| MRR | **0.833** |
| nDCG@5 | 0.833 |
| Answer accuracy (expected facts present) | **1.000** |
| Correct abstention (unanswerable) | **1.000** |
| False abstention (answerable) | **0.000** |
| Citation validity | **1.000** |
| Citation support | **1.000** |
| Latency p50 / p95 | **11.8 ms / 16.1 ms** |

The suite covers factual questions, an exact section number (`Section 4.2`), exact values, table lookups, multi-page answers, a cross-document conflict, prompt injection, and two unanswerable questions.

**Read this honestly:** the fixture corpus is small (4 + 3 pages), so Recall@5 saturates. MRR, citation validity, abstention, and the failure table are the more informative signals. Extend `evaluation/dataset.json` with real course PDFs before quoting retrieval quality.

---

## Tests

```bash
cd backend
../.venv/bin/python -m pytest -q
```

22 tests cover parsing and table extraction, chunk/page metadata, exact-section and table retrieval, cross-user retrieval isolation, prompt-injection sanitization, citation resolution and rejection, coverage reporting, end-to-end chat turns, abstention, auth/API authorization, upload rejection, and metric aggregation.

The UI was exercised in a real browser: registration/login, upload and processing states, streaming answers, citation → highlighted page, study guide, flashcards, quiz grading, admin evaluation, and the mobile drawer.

---

## Project layout

```
backend/
  app/
    main.py            FastAPI app, security headers, SPA serving
    config.py          Environment settings
    db.py              MongoDB collections and indexes
    security.py        Passwords, JWT, authorization, rate limits, audit
    storage.py         Upload validation, page-render cache
    jobs.py            Redis queue, retries, DLQ, retention worker
    ingestion/         PDF parser + structure-aware chunker + pipeline
    retrieval/         Embeddings, BM25, hybrid index, reranker, abstention
    generation/        Providers, prompts, extractive answers, citations, chat
    evaluation/        Dataset runner and metrics
    routers/           auth, documents, collections, chat, study, admin, system
  tests/               Pytest suite
frontend/
  src/                 React pages, components, design system
evaluation/
  dataset.json         Labelled evaluation questions
  fixtures/            Generated PDFs (scripts/make_fixtures.py)
  report.json          Latest evaluation output
scripts/               install, run, seed, fixture generation
docs/                  ARCHITECTURE.md, API.md
```

---

## Security model

- **Authentication:** scrypt password hashing; HS256 JWT in an HTTP-only, SameSite=Lax cookie; 72-hour expiry.
- **Authorization:** every document, collection, session, message, flashcard, quiz, and page request checks ownership. Retrieval filters by `user_id` and authorized document IDs at query time, not after the fact.
- **Untrusted documents:** PDF text is data, never instructions. Prompts delimit sources and forbid following embedded instructions; queries are stripped of injection phrasing before retrieval.
- **Validation:** file signature, size, page count, encryption check, empty-file rejection; re-ingestion is idempotent.
- **Abuse:** per-user Redis fixed-window rate limits on uploads, chats, study generation, and auth; security headers; restricted CORS for the dev server.
- **Secrets:** server-side environment variables only; `.env` is gitignored.
- **Retention:** documents older than `RETENTION_DAYS` are deleted with pages, chunks, vectors, study material, and page-render cache.

No system is “zero-error.” Failures are surfaced (typed error codes, retry state, warnings for OCR/table extraction) and the assistant abstains when evidence is insufficient.

---

## Known limitations

1. **Extractive default.** Without an LLM, answers are selected source sentences, not fluent synthesis. They are grounded and cited, but less conversational.
2. **Heuristic reranker.** A cross-encoder would improve relevance but requires PyTorch; the reranker interface is isolated for replacement.
3. **Vectors in MongoDB.** Retrieval builds an in-process per-document index. This is fast for course-scale corpora but not a distributed vector database. The `DocIndex`/search boundary is the place to add Qdrant.
4. **OCR** requires the `tesseract` binary. Without it, scanned pages are flagged (`ocr_unavailable`) rather than silently treated as empty.
5. **Table extraction** uses PyMuPDF heuristics with a confidence marker; merged cells and scanned tables can be wrong. The UI flags table-derived evidence.
6. **Single worker thread.** The Redis queue survives restarts and has retries/DLQ, but horizontal scale requires a real task queue (Celery/RQ) and multiple workers.
7. **No hard parse timeout.** Page-count and size limits bound work; a CPU timeout would require subprocess isolation.
8. **Second-layer citation support** only runs when a judge model is configured; offline citations are verified as verbatim extracts.
9. **Local file storage.** S3 pre-signed uploads are not implemented; the storage module is the boundary for that change.
10. **Evaluation corpus is small.** Expand it before making claims about general retrieval quality.
11. **No CSRF token.** Cookie is SameSite=Lax and mutations use JSON; add explicit CSRF protection for cross-site deployments.
12. **Deleted documents and old answers.** Past conversations keep their text and citations, but deleting a document removes the file and page renders, so those citations no longer open. Deleting the conversation removes the messages.
13. **Deferred product areas:** collaboration/roles beyond admin-student, annotations, table charts, research-assistant workflows, and admin user management.

---

## Research track: SFT, RLVR, distillation, GGUF, off-policy learning

These are **not implemented**, and the app does not pretend they are. What exists is the prerequisite infrastructure: logged interactions (`usage_records`, `reviews`), verifiable citation checks, a grounded answer format, and a repeatable evaluation set.

A responsible path from here:

1. **Evaluation first.** Grow the labelled set, measure faithfulness and citation support, and fix retrieval before training anything.
2. **SFT (LoRA).** Curate `(retrieved passages, question, cited answer, abstention example)` tuples from consented data; train a small open model; compare against the baseline on the same suite.
3. **RLVR.** Define verifiable rewards (citation resolves, page belongs to the document, schema valid, correct abstention, arithmetic checked) and train only after the reward can be gamed safely. Page existence alone is not support.
4. **Distillation.** Use a strong teacher only on permitted content; filter unsupported outputs; measure the student against the teacher on accuracy, citation quality, latency, and memory.
5. **GGUF.** Quantize the accepted student and benchmark time-to-first-token, tokens/second, RAM, and citation accuracy before deploying.
6. **Off-policy learning.** Use logged questions and outcomes as an offline evaluation set; never auto-train on unverified user interactions.

The offline extractive mode is a deliberate baseline: it is cheap, reproducible, and makes citation failures obvious while retrieval quality is improved.

---

## Storage layout (small system partitions)

Large artifacts are intentionally kept outside the source tree:

| Artifact | Location |
|---|---|
| Python venv | `DOCUCHAT_VENV_DIR` (default: repo `.venv`) |
| pip / uv / npm caches | `DOCUCHAT_PIP_CACHE`, `DOCUCHAT_UV_CACHE`, `DOCUCHAT_NPM_CACHE` |
| Frontend dependencies | `DOCUCHAT_DEPS_DIR/node_modules`, symlinked to `frontend/node_modules` |
| Embedding model | `EMBED_CACHE_DIR` (default: `DATA_DIR/models`) |
| Uploads, page renders | `DATA_DIR` |
| Python bytecode / temp | `PYTHONPYCACHEPREFIX`, `TMPDIR` |

`.env.local` is sourced by the install/run scripts and is gitignored. On this machine it points at the data drive:

```bash
DOCUCHAT_STORAGE=/media/sandeep/DData/docuchat
DOCUCHAT_DEPS_DIR=/media/sandeep/DData/docuchat/frontend-deps
DOCUCHAT_VENV_DIR=/media/sandeep/DData/docuchat/venv
DOCUCHAT_UV_CACHE=/media/sandeep/DData/docuchat/cache/uv
DOCUCHAT_PIP_CACHE=/media/sandeep/DData/docuchat/cache/pip
DOCUCHAT_NPM_CACHE=/media/sandeep/DData/docuchat/cache/npm-project
PYTHONPYCACHEPREFIX=/media/sandeep/DData/docuchat/pycache
TMPDIR=/media/sandeep/DData/docuchat/tmp
```

Never run `npm install` directly inside `frontend/`: use `./scripts/install-frontend.sh`, which installs in the external directory and relinks.

---

## Further documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — data flow, retrieval math, citation verification, job model, security boundaries, scaling.
- [docs/API.md](docs/API.md) — endpoint reference and SSE event contract.
