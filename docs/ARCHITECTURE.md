# DocuChat architecture

## Design goals

1. **Ground every answer.** The model may only use retrieved passages, and every citation is resolved by the server to a real, authorized page.
2. **Make quality measurable.** A fixed evaluation suite, stored per run, is part of the product.
3. **Fail visibly.** Typed errors, retry states, OCR/table warnings, and abstention are first-class.
4. **Isolate tenants.** Ownership is checked at every API boundary and inside retrieval.
5. **Keep the operational surface small.** One API process, MongoDB, Redis, local storage. Components have interfaces so they can be replaced or split later.

## Why a modular monolith

The original blueprint proposed five services (React, Node gateway, Python ingestion, Python RAG, MongoDB, vector DB, object storage). For a single deployment, that adds network failure modes, duplicated auth, and operational cost without a demonstrated bottleneck.

This build keeps the same boundaries as modules:

```
routers/         HTTP contract, authentication, ownership checks
ingestion/       PDF → structured pages → chunks → vectors
retrieval/       query → hybrid candidates → rerank → context
generation/      context → answer → citations → verification
evaluation/      dataset → metrics → stored runs
jobs.py          durable background processing
storage.py       original files + rendered pages
```

Each module talks to the next through plain data structures; extraction into services is a deployment change, not a rewrite. The Redis queue and job records already model asynchronous work the way a worker service would.

## Runtime components

| Component | Responsibility | Failure behavior |
|---|---|---|
| React SPA | Chat, library, study mode, admin | Errors shown inline/toasts; optimistic UI reconciled from the server |
| FastAPI | Auth, CRUD, SSE streaming, static SPA | Typed HTTP errors; generic 500 handler hides internals |
| MongoDB | Metadata, chunks + embeddings, messages, jobs, eval runs, audit | Indexes created at startup; unique `(document_id, chunk.index)` prevents duplicate chunks on retry |
| Redis | Job queue, dead-letter queue, rate-limit counters | Queue falls back to an in-process queue if Redis is unavailable |
| Storage | PDF originals, page-render cache | Missing files surface as 404s and failed jobs |
| fastembed | Local neural embeddings | Falls back to hashed n-grams; `/api/system/status` reports degradation |
| LLM provider | Optional generation and citation judging | Errors are caught; extractive fallback is used if no tokens were emitted |

## Ingestion pipeline

```
upload → validate → queue → extract → OCR check → chunk → embed → index → ready
             │                    │                     │
             └─ rejected          └─ warnings          └─ retry / DLQ
```

1. **Upload.** The API checks PDF signature, size, extension, and collection ownership; stores the file under `DATA_DIR/uploads/<id>.pdf`; creates a document record and job.
2. **Worker.** A Redis list is consumed by a daemon thread. Jobs are claimed atomically with `find_one_and_update`, retried up to three times with backoff, and pushed to `docuchat:jobs:dlq` after final failure. Stale `processing` jobs are requeued at startup.
3. **Parse.** PyMuPDF opens the file (encrypted PDFs rejected). Text blocks retain font size, boldness, and bounding boxes. Headings are detected by size relative to the body, boldness, numbering (`Section 4.2`), and named sections. Tables are extracted with `page.find_tables()` and stored as markdown plus headers/rows with a `0.62` confidence marker.
4. **OCR.** A page with fewer than ~60 characters and raster images is treated as scanned. If Tesseract is installed, the page is OCR'd and the block is tagged `extraction_method=ocr`; otherwise a per-page warning is stored and shown in the library.
5. **Chunk.** Chunks never cross page boundaries, so a citation always maps to one page. Consecutive blocks in the same section are packed to ~900 characters; oversized paragraphs split on sentence boundaries. Each chunk stores `page_number`, `section_path`, `heading`, `extraction_method`, `confidence`, and text used for embedding with the section path prepended.
6. **Embed.** Vectors are generated in batches and normalized. Stored in MongoDB with six-decimal floats to control size.
7. **Index.** The per-document index is invalidated; retrieval reloads lazily from MongoDB, keyed by `ingest_version`.

Idempotency: existing chunks and pages for the document are deleted before writing, and unique indexes prevent duplicate chunk indices if a worker is interrupted.

## Retrieval

Given a question and a set of authorized documents:

1. **Sanitize the query.** Instruction-like clauses (`ignore previous instructions`, `reveal your system prompt`) are removed before embedding and BM25. The original question remains in the conversation history; the sanitization flag is returned in diagnostics.
2. **Dense search.** Cosine similarity over the document’s normalized embedding matrix.
3. **BM25.** Okapi BM25 (`k1=1.5`, `b=0.75`) over embedding text. Tokenization preserves identifiers such as `4.2`, `d_model`, and `bm25`, and applies a light suffix stemmer.
4. **Fusion.** Weighted Reciprocal Rank Fusion:
   `score(d) = Σ_arm w_arm / (k + rank_arm(d) + 1)` with `k=60`, vector weight `0.7`, BM25 weight `0.3`. RRF avoids comparing incompatible raw scores.
5. **Rerank.** A transparent heuristic combines normalized RRF (55%), IDF-weighted query-term coverage (25%), normalized vector score (20%), plus small bonuses for exact section references, quoted phrases, table intent, and full term coverage.
6. **Select context.** Near-duplicate chunks are removed (token Jaccard > 0.82), at most two chunks per page, token budget enforced, and every document in scope is represented when possible.
7. **Confidence and abstention.** Raw top vector similarity is calibrated, then combined with coverage and term presence:
   `confidence = 0.45·semantic + 0.25·coverage_top + 0.30·term_presence + 0.05·margin`.
   The query is answerable only if `term_presence ≥ 0.5` or semantic similarity is very high, and confidence clears `MIN_RETRIEVAL_CONFIDENCE`. Otherwise the assistant abstains. This deliberately trades recall for precision in the offline mode; synonyms with no shared terms may abstain and should be rephrased.

Summary questions take a separate path: chunks are sampled across the document (and across documents) rather than ranked by similarity.

## Answer generation and citations

### Modes

- **Extractive (default, no key).** Sentences are scored by query overlap, passage rank, and position; at most a few are selected, grouped by document, and emitted as bullets with `[S#]` markers. Table questions return rows reconstructed from the extracted table with a marker per row. This is deterministic, cheap, and inherently grounded.
- **OpenAI-compatible / Ollama.** A strict system prompt requires answers only from labeled passages, `[S#]` citations, explicit abstention, and resistance to instructions inside documents. Streaming tokens are forwarded over SSE.

### Citation resolution (layer 1, deterministic)

The model never emits page numbers. It cites passage labels (`S1…Sn`). The server:

1. Maps each label back to the exact retrieved chunk.
2. Verifies the chunk’s document is in the conversation scope and owned by the user.
3. Verifies the page exists in the document.
4. Treats any unknown label as **invalid**; invalid citations are rendered in red and excluded from evidence coverage.

### Support verification (layer 2, optional)

With a configured judge model, each unresolved citation is checked with “does this passage support this claim?” (`SUPPORTED`, `PARTIAL`, `NOT_SUPPORTED`). Extractive citations are marked verified as verbatim extracts. A page existing is necessary but not sufficient; the UI distinguishes verified, partial, pending, and invalid.

## Chat streaming and cancellation

```
POST /api/chat/sessions/{id}/messages
  event: status       searching / checking evidence
  event: retrieval    sources, confidence, sufficiency, diagnostics
  event: start        assistant message id, provider, model, mode
  event: delta        text fragments
  event: citations    citations, claims, coverage
  event: done         status, latency, abstention, generation error
  event: error        user-safe failure message
```

The assistant message is persisted before streaming. If the client aborts, Starlette cancels the response task; the generator catches cancellation, stores the partial content with `status=cancelled`, and does not present it as complete. Regeneration marks the previous message `is_current=false` and creates a new answer.

## Data model

| Collection | Key fields |
|---|---|
| `users` | email (unique), password hash, role, disabled |
| `documents` | owner, title, filename, size, sha256, status, progress, page/chunk counts, category, warnings, outline, ingest version |
| `document_pages` | document, page number, text, headings, tables, OCR flags |
| `document_chunks` | document, index, page number, section path, text, embedding text, vector, extraction method, confidence, table |
| `collections` | owner, name, document ids |
| `chat_sessions` | owner, document ids, title, timestamps |
| `messages` | session, role, content, citations, claims, coverage, status, provider, latency |
| `processing_jobs` | type, document, status, attempts, progress, error, timestamps |
| `study_guides`, `flashcards`, `quizzes`, `quiz_attempts` | owner, document, generated content, citations/pages |
| `reviews`, `usage_records` | feedback and estimated usage |
| `evaluation_runs` | dataset, config snapshot, summary, per-question records |
| `audit_logs` | action, user, metadata, timestamp |

Deletion cascades across pages, chunks, study material, collections, session scopes, the original file, the page cache, and the in-process index.

## Security boundaries

1. **Session:** cookie or bearer JWT → user lookup on every request.
2. **Route:** ownership filter is part of every query (`user_id` + `_id`).
3. **Retrieval:** documents are re-fetched and authorized; chunk queries use those IDs. A caller cannot retrieve by supplying a foreign document ID.
4. **Citations/pages:** page images, evidence, and original PDFs repeat the ownership check.
5. **Prompt:** documents are labeled as untrusted data; the system prompt forbids following embedded instructions or revealing configuration.
6. **Worker:** operates on document IDs from authenticated uploads; no user input is executed.

## Failure modes

| Failure | Detection | User experience |
|---|---|---|
| Password-protected PDF | PyMuPDF `needs_pass` | 400 with a specific message; retry not offered |
| Too many pages / too large | limits | 400, document marked failed |
| Scanned without OCR | page heuristic | Warning per page; answer may abstain |
| Table extraction uncertain | confidence marker | `table` badge in evidence; inspect original page |
| Embedding model unavailable | provider init failure | Hashing fallback; status shows degraded |
| LLM provider down | exception before tokens | Extractive fallback; generation error recorded |
| Worker crash | stale `processing` job | Requeued at startup |
| Unanswerable question | confidence + term presence | Explicit abstention; no citations |
| Client disconnects | task cancellation | Partial answer saved as `cancelled` |

## Scaling path

| Need | Change |
|---|---|
| Millions of chunks | Replace the in-process index with Qdrant/Pinecone; keep the `search()` contract and metadata filters |
| Many concurrent ingestions | Move `ingest_document` behind Celery/RQ workers; the job record and retry semantics already exist |
| Object storage | Implement the storage interface with S3 pre-signed uploads; keep page rendering on the API |
| Independent frontend | Keep FastAPI as the API; CORS is restricted to configured origins |
| Cross-site embedding | Add CSRF tokens, stricter CSP, and cookie domain configuration |
| Neural reranking | Swap `_rerank` for a cross-encoder service; the evaluate harness already measures MRR |
| Fine-tuned models | Add a provider adapter; use the evaluation suite to gate deployment |

## Evaluation methodology

`evaluation/dataset.json` defines fixture documents and labelled questions with expected pages, expected answer substrings, and `expected_abstain`. The runner:

1. Reuses or ingests fixture documents for an internal evaluation user (content-addressed by SHA-256).
2. Runs retrieval, extractive answering, citation resolution, and coverage for each question.
3. Computes Recall@5, MRR, nDCG@5, answer accuracy, citation validity/support, abstention rates, and latency.
4. Stores the run with a configuration snapshot (embedder, weights, thresholds, provider) so later runs are comparable.

Limitations: the current corpus is small, so Recall@5 saturates; answer accuracy is substring-based; support verification is verbatim in offline mode. The suite is a regression gate, not proof of general correctness. Rerun it whenever chunking, embeddings, fusion weights, reranker, generation model, or prompts change.
