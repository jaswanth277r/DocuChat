# DocuChat API

Base path: `/api`. Interactive OpenAPI docs are served at `/api/docs`.

## Authentication

All endpoints except `/api/health`, `/api/auth/register`, and `/api/auth/login` require a session. The session is an HTTP-only cookie (`docuchat_session`) set by login/register. A bearer token is also accepted:

```
Authorization: Bearer <jwt>
```

| Method | Path | Body | Notes |
|---|---|---|---|
| POST | `/auth/register` | `{email, password, name}` | First non-evaluation account becomes admin. 409 on duplicate email. |
| POST | `/auth/login` | `{email, password}` | 401 on bad credentials. |
| POST | `/auth/logout` | — | Clears the cookie. |
| GET | `/auth/me` | — | Returns the current user. |

## Documents

| Method | Path | Notes |
|---|---|---|
| POST | `/documents` | `multipart/form-data`: `file` (PDF), optional `collection_id`. Queues ingestion. |
| GET | `/documents` | Query: `q`, `status_filter`. Returns up to 200 newest documents. |
| GET | `/documents/{id}` | Metadata, outline, warnings. |
| GET | `/documents/{id}/status` | Processing state, progress, latest job. |
| GET | `/documents/{id}/file` | Original PDF (`application/pdf`). |
| GET | `/documents/{id}/pages/{n}` | Extracted page text, headings, tables. |
| GET | `/documents/{id}/pages/{n}/image?scale=2&highlight=...` | Server-rendered PNG of the page. `highlight` draws a translucent annotation for the first matching sentence. |
| GET | `/documents/{id}/evidence?chunk_id=<doc>:<index>` | Chunk text plus the surrounding page. |
| GET | `/documents/{id}/outline` | Detected headings and extraction warnings. |
| PATCH | `/documents/{id}` | `{title?, category?}`. Setting a category locks classification. |
| POST | `/documents/{id}/retry` | Re-queues a failed or ready document. |
| DELETE | `/documents/{id}` | Cascades pages, chunks, study material, scope membership, file, and page cache. |

Document statuses:

```
uploaded → queued → validating → extracting → ocr_check → chunking → embedding → indexing → ready
                                                                                         ↘ failed
```

Errors use `detail: {code, message}` for upload/processing failures.

## Collections

| Method | Path | Body |
|---|---|---|
| POST | `/collections` | `{name, description?}` |
| GET | `/collections` | — |
| PATCH | `/collections/{id}` | `{name, description?}` |
| DELETE | `/collections/{id}` | — |
| POST | `/collections/{id}/documents` | `{document_ids: []}` |
| DELETE | `/collections/{id}/documents/{document_id}` | — |

## Chat

| Method | Path | Notes |
|---|---|---|
| POST | `/chat/sessions` | `{document_ids?: [], collection_id?, title?}`. Scope is validated: every document must be owned and `ready`. |
| GET | `/chat/sessions?q=` | Recent sessions. |
| GET | `/chat/sessions/{id}` | `{session, messages, documents}`. Only current message revisions are returned. |
| PATCH | `/chat/sessions/{id}` | `{title?, document_ids?, collection_id?}`. |
| DELETE | `/chat/sessions/{id}` | Removes the session and its messages. |
| POST | `/chat/sessions/{id}/messages` | `{content}` → **SSE stream**. |
| POST | `/chat/sessions/{id}/messages/{message_id}/regenerate` | Empty body → **SSE stream**. |
| POST | `/chat/messages/{message_id}/feedback` | `{rating: -1|0|1, comment?}` |
| GET | `/messages/{message_id}/citations` | Stored citations, claims, coverage. |
| GET | `/chat/sessions/{id}/export` | Markdown download. |

### SSE contract

`Content-Type: text/event-stream`. Each event is `event: <name>\ndata: <json>\n\n`.

| Event | Payload |
|---|---|
| `status` | `{stage, message}` |
| `retrieval` | `{sources[], confidence, sufficient, mode, diagnostics}` |
| `start` | `{message_id, provider, model, mode, sufficient}` |
| `delta` | `{text}` |
| `citations` | `{message_id, citations[], claims[], coverage}` |
| `done` | `{message_id, latency_ms, provider, model, mode, abstained, coverage, generation_error, status}` |
| `error` | `{message}` |

`source` shape:

```json
{
  "label": "S1",
  "document_id": "…",
  "document_title": "Transformer Architectures: Lecture Notes",
  "page_number": 2,
  "section_path": "… > Section 4.2 Scaling Factors",
  "chunk_id": "…:4",
  "excerpt": "…",
  "text": "…",
  "extraction_method": "text",
  "chunk_kind": "text",
  "score": 0.94
}
```

`citation` shape:

```json
{
  "label": "S1",
  "claim": "…",
  "document_id": "…",
  "page_number": 2,
  "chunk_id": "…:4",
  "excerpt": "…",
  "status": "verified",
  "method": "verbatim_extract",
  "reason": "…"
}
```

Citation `status`: `verified`, `partial`, `pending`, `unsupported`, `invalid`. `coverage.status`: `all_claims_cited`, `some_claims_uncited`, `mostly_uncited`, `invalid_citations`, `no_claims`.

Abort the fetch to stop generation. The server stores partial output with `status=cancelled` and no completed-answer state.

## Study mode

| Method | Path | Body |
|---|---|---|
| POST | `/documents/{id}/study-guides` | `{focus?, count?, difficulty?}` |
| GET | `/documents/{id}/study-guides` | Latest guide |
| POST | `/documents/{id}/flashcards` | `{focus?, count?}` (replaces the deck) |
| GET | `/documents/{id}/flashcards` | Deck |
| PATCH | `/flashcards/{card_id}` | `{front?, back?, status?}` (`new`, `known`, `difficult`) |
| DELETE | `/flashcards/{card_id}` | — |
| POST | `/documents/{id}/quizzes` | `{count?, difficulty?}` (`beginner`, `intermediate`, `advanced`, `exam`) |
| GET | `/documents/{id}/quizzes` | Quiz list (answers stripped) |
| GET | `/quizzes/{id}` | Full quiz with answers |
| POST | `/quizzes/{id}/attempts` | `{answers: [string]}` → score, per-question feedback, pages |
| GET | `/quizzes/{id}/attempts` | Recent attempts |
| GET | `/study/progress` | Flashcard and attempt summary |

Bodies accept `{}`; `StudyRequest` fields are optional. Generation uses the LLM provider when configured, otherwise a deterministic extractive generator; `generated_by` identifies which.

## Admin (role: `admin`)

| Method | Path | Notes |
|---|---|---|
| GET | `/admin/metrics` | Ingestion success, median ingest time, chat latency, abstention, citation validity, queue depth, jobs, provider status, latest evaluation |
| GET | `/admin/jobs?status_filter=` | Job list |
| GET | `/admin/audit-logs?limit=` | Recent audit entries |
| GET | `/admin/evaluations` | Evaluation runs (summaries) |
| GET | `/admin/evaluations/{run_id}` | Full run with per-question records |
| POST | `/admin/evaluations/run?dataset=default` | Runs the fixture suite synchronously |

## System

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | Public liveness check |
| GET | `/api/system/status` | Mongo/Redis health, embedder, provider, limits, retrieval configuration |

## Errors and limits

- Validation errors: `422` with FastAPI’s detail array.
- Authentication: `401`; authorization: `403` or `404` for resources outside the caller’s scope.
- Rate limits: `429` for uploads (10/hour), chat (120/hour), study generation (40/hour), and auth attempts.
- Upload rejection: `400` with `{code, message}` such as `not_pdf`, `too_large`, `empty_file`, `password_protected`, `too_many_pages`.
- Unhandled errors return `500` with a generic message; details stay in server logs.

Example:

```bash
curl -c cookies.txt -H 'Content-Type: application/json' \
  -d '{"email":"demo@docuchat.local","password":"docuchat-demo"}' \
  http://127.0.0.1:8000/api/auth/login

curl -b cookies.txt -F file=@evaluation/fixtures/transformer_notes.pdf \
  http://127.0.0.1:8000/api/documents

curl -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"document_ids":["<document id>"]}' \
  http://127.0.0.1:8000/api/chat/sessions

curl -N -b cookies.txt -H 'Content-Type: application/json' \
  -d '{"content":"What does Section 4.2 say about the scaling factor?"}' \
  http://127.0.0.1:8000/api/chat/sessions/<session id>/messages
```
