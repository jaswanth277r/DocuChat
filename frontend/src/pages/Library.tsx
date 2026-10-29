import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, formatBytes, formatDate, notifySessionsChanged, titleCase } from "../lib/api";
import { useToast } from "../lib/toast";
import type { Collection, DocumentRecord, Session } from "../lib/types";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, Field, IconButton, Modal, Progress, Spinner, StatusPill } from "../components/ui";

const STAGES = ["validating", "extracting", "ocr_check", "chunking", "embedding", "indexing"];
const FINAL = new Set(["ready", "failed", "deleted"]);

function stageIndex(status: string) {
  if (status === "ready") return STAGES.length;
  const index = STAGES.indexOf(status);
  return index < 0 ? 0 : index;
}

export function LibraryPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [collections, setCollections] = useState<Collection[]>([]);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<"all" | "ready" | "processing" | "failed">("all");
  const [collectionFilter, setCollectionFilter] = useState<string>("all");
  const [uploadCollection, setUploadCollection] = useState<string>("");
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [detail, setDetail] = useState<DocumentRecord | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentRecord | null>(null);
  const [collectionModal, setCollectionModal] = useState(false);
  const [collectionName, setCollectionName] = useState("");
  const [busy, setBusy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  const load = useCallback(async (silent = false) => {
    try {
      const [docs, cols] = await Promise.all([
        api<{ documents: DocumentRecord[] }>("/documents"),
        api<{ collections: Collection[] }>("/collections"),
      ]);
      setDocuments(docs.documents);
      setCollections(cols.collections);
    } catch (error) {
      if (!silent) toast.push(error instanceof Error ? error.message : "Could not load the library", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const processingCount = documents.filter((doc) => !FINAL.has(doc.status)).length;
  useEffect(() => {
    if (!processingCount) return;
    const timer = window.setInterval(() => void load(true), 2500);
    return () => window.clearInterval(timer);
  }, [processingCount, load]);

  const uploadFiles = async (files: FileList | File[]) => {
    const list = Array.from(files);
    if (!list.length) return;
    setUploading(true);
    for (const file of list) {
      if (!file.name.toLowerCase().endsWith(".pdf")) {
        toast.push(`${file.name} is not a PDF`, "error");
        continue;
      }
      const data = new FormData();
      data.append("file", file);
      if (uploadCollection) data.append("collection_id", uploadCollection);
      try {
        await api<DocumentRecord>("/documents", { method: "POST", body: data });
        toast.push(`${file.name} queued for processing`, "success");
      } catch (error) {
        toast.push(error instanceof Error ? error.message : `Upload failed for ${file.name}`, "error");
      }
    }
    setUploading(false);
    await load(true);
  };

  const openChat = async (doc: DocumentRecord) => {
    if (doc.status !== "ready") {
      toast.push("Wait until the document is ready", "error");
      return;
    }
    try {
      const session = await api<Session>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ document_ids: [doc.id], title: `Chat — ${doc.title}` }),
      });
      notifySessionsChanged();
      navigate(`/chat/${session.id}`);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not start chat", "error");
    }
  };

  const removeDocument = async () => {
    if (!deleteTarget) return;
    setBusy(true);
    try {
      await api(`/documents/${deleteTarget.id}`, { method: "DELETE" });
      toast.push("Document deleted", "success");
      setDeleteTarget(null);
      setDetail(null);
      await load(true);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Delete failed", "error");
    } finally {
      setBusy(false);
    }
  };

  const retry = async (doc: DocumentRecord) => {
    try {
      await api(`/documents/${doc.id}/retry`, { method: "POST" });
      toast.push("Reprocessing queued", "success");
      await load(true);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Retry failed", "error");
    }
  };

  const updateCategory = async (doc: DocumentRecord, category: string) => {
    try {
      await api(`/documents/${doc.id}`, { method: "PATCH", body: JSON.stringify({ category }) });
      const updated = { ...doc, category };
      setDetail(updated);
      await load(true);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not update category", "error");
    }
  };

  const assignCollection = async (doc: DocumentRecord, collectionId: string) => {
    try {
      if (doc.collection_id && doc.collection_id !== collectionId) {
        await api(`/collections/${doc.collection_id}/documents/${doc.id}`, { method: "DELETE" });
      }
      if (collectionId) {
        await api(`/collections/${collectionId}/documents`, {
          method: "POST",
          body: JSON.stringify({ document_ids: [doc.id] }),
        });
      }
      const refreshed = await api<DocumentRecord>(`/documents/${doc.id}`);
      setDetail(refreshed);
      await load(true);
      toast.push(collectionId ? "Added to collection" : "Removed from collection", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not update collection", "error");
    }
  };

  const createCollection = async () => {
    if (!collectionName.trim()) return;
    setBusy(true);
    try {
      await api("/collections", { method: "POST", body: JSON.stringify({ name: collectionName.trim() }) });
      setCollectionModal(false);
      setCollectionName("");
      toast.push("Collection created", "success");
      await load(true);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not create collection", "error");
    } finally {
      setBusy(false);
    }
  };

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return documents.filter((doc) => {
      if (filter === "ready" && doc.status !== "ready") return false;
      if (filter === "failed" && doc.status !== "failed") return false;
      if (filter === "processing" && FINAL.has(doc.status)) return false;
      if (collectionFilter !== "all" && doc.collection_id !== collectionFilter) return false;
      if (needle && !`${doc.title} ${doc.original_name} ${doc.category || ""}`.toLowerCase().includes(needle)) return false;
      return true;
    });
  }, [documents, query, filter, collectionFilter]);

  const stats = useMemo(() => {
    const ready = documents.filter((doc) => doc.status === "ready");
    const pages = documents.reduce((sum, doc) => sum + (doc.page_count || 0), 0);
    const chunks = documents.reduce((sum, doc) => sum + (doc.chunk_count || 0), 0);
    const bytes = documents.reduce((sum, doc) => sum + (doc.size_bytes || 0), 0);
    return { ready: ready.length, pages, chunks, bytes };
  }, [documents]);

  return (
    <div className="page">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <h1 className="page-title">Document library</h1>
            <p className="page-sub">Upload PDFs, then chat with them or turn them into study material.</p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button icon="book" onClick={() => setCollectionModal(true)}>
              New collection
            </Button>
            <Button variant="primary" icon="upload" onClick={() => fileInput.current?.click()} loading={uploading}>
              Upload PDF
            </Button>
          </div>
        </header>

        <div className="stats-row">
          <div className="stat">
            <div className="stat-label">Documents</div>
            <div className="stat-value">{documents.length}</div>
            <div className="stat-note">{stats.ready} ready to chat</div>
          </div>
          <div className="stat">
            <div className="stat-label">Pages indexed</div>
            <div className="stat-value">{stats.pages}</div>
            <div className="stat-note">{stats.chunks} chunks with page metadata</div>
          </div>
          <div className="stat">
            <div className="stat-label">Collections</div>
            <div className="stat-value">{collections.length}</div>
            <div className="stat-note">Group related documents</div>
          </div>
          <div className="stat">
            <div className="stat-label">Storage</div>
            <div className="stat-value">{formatBytes(stats.bytes)}</div>
            <div className="stat-note">Originals kept for page previews</div>
          </div>
        </div>

        <div
          className={`dropzone ${dragging ? "dragging" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragging(false);
            void uploadFiles(event.dataTransfer.files);
          }}
        >
          <div className="dropzone-icon">
            <Icon name="upload" size={21} />
          </div>
          <div style={{ flex: 1 }}>
            <div style={{ fontWeight: 620, fontSize: 14 }}>Drop a PDF here, or choose a file</div>
            <div style={{ color: "var(--color-muted)", fontSize: 12.5, marginTop: 2 }}>
              Up to 25 MB and 500 pages · text and scanned PDFs · tables extracted where possible
            </div>
          </div>
          <div style={{ minWidth: 190 }}>
            <label className="label" htmlFor="upload-collection">
              Upload into
            </label>
            <select
              id="upload-collection"
              className="select"
              value={uploadCollection}
              onChange={(event) => setUploadCollection(event.target.value)}
            >
              <option value="">No collection</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
          </div>
          <Button icon="file" onClick={() => fileInput.current?.click()} disabled={uploading}>
            {uploading ? "Uploading…" : "Choose file"}
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,.pdf"
            multiple
            hidden
            onChange={(event) => {
              if (event.target.files) void uploadFiles(event.target.files);
              event.target.value = "";
            }}
          />
        </div>

        <div className="toolbar">
          <div className="search-box">
            <Icon name="search" size={15} />
            <input className="input" placeholder="Search documents…" value={query} onChange={(event) => setQuery(event.target.value)} aria-label="Search documents" />
          </div>
          <div className="filter-chips">
            {(["all", "ready", "processing", "failed"] as const).map((value) => (
              <button key={value} className={`chip ${filter === value ? "active" : ""}`} onClick={() => setFilter(value)}>
                {value === "all" ? "All" : titleCase(value)}
                {value === "processing" && processingCount ? ` (${processingCount})` : ""}
              </button>
            ))}
          </div>
          {collections.length ? (
            <select
              className="select"
              style={{ width: "auto", minWidth: 150 }}
              value={collectionFilter}
              onChange={(event) => setCollectionFilter(event.target.value)}
              aria-label="Filter by collection"
            >
              <option value="all">All collections</option>
              {collections.map((collection) => (
                <option key={collection.id} value={collection.id}>
                  {collection.name}
                </option>
              ))}
            </select>
          ) : null}
        </div>

        {loading ? (
          <div className="doc-grid">
            {[0, 1, 2].map((index) => (
              <div key={index} className="doc-card">
                <div className="skeleton" style={{ height: 38, width: 38, borderRadius: 10 }} />
                <div className="skeleton" style={{ height: 16, width: "75%" }} />
                <div className="skeleton" style={{ height: 12, width: "50%" }} />
                <div className="skeleton" style={{ height: 12, width: "35%", marginTop: "auto" }} />
              </div>
            ))}
          </div>
        ) : filtered.length === 0 ? (
          <EmptyState
            icon="library"
            title={documents.length ? "No documents match this view" : "Your library is empty"}
            description={
              documents.length
                ? "Adjust the search or filters to find a document."
                : "Upload a PDF to begin. For a quick demo, use the fixtures in evaluation/fixtures/transformer_notes.pdf and retrieval_report.pdf."
            }
            action={
              <Button variant="primary" icon="upload" onClick={() => fileInput.current?.click()}>
                Upload your first PDF
              </Button>
            }
          />
        ) : (
          <div className="doc-grid">
            {filtered.map((doc) => {
              const processing = !FINAL.has(doc.status);
              const done = stageIndex(doc.status);
              return (
                <article className="doc-card" key={doc.id}>
                  <div className="doc-card-top">
                    <div className="doc-icon">
                      <Icon name="file" size={18} />
                    </div>
                    <div style={{ minWidth: 0, flex: 1 }}>
                      <button
                        onClick={() => setDetail(doc)}
                        style={{ border: "none", background: "transparent", padding: 0, textAlign: "left", width: "100%" }}
                        title="Open document details"
                      >
                        <div className="doc-title">{doc.title}</div>
                      </button>
                      <div className="doc-meta" style={{ marginTop: 4 }}>
                        <Badge tone={doc.status === "failed" ? "danger" : doc.status === "ready" ? "accent" : "neutral"}>
                          {titleCase(doc.category)}
                        </Badge>
                        {doc.page_count ? <span>{doc.page_count} pages</span> : null}
                        {doc.chunk_count ? <span>{doc.chunk_count} chunks</span> : null}
                        <span>{formatDate(doc.created_at)}</span>
                      </div>
                    </div>
                    <StatusPill status={doc.status} detail={doc.error?.message} />
                  </div>

                  {processing ? (
                    <div>
                      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 11, color: "#7d7685", marginBottom: 4 }}>
                        <span>{doc.stage_message || "Processing"}</span>
                        <span>{doc.progress || 0}%</span>
                      </div>
                      <Progress value={doc.progress || 0} />
                      <div className="stage-list" aria-hidden="true">
                        {STAGES.map((stage, index) => (
                          <span key={stage} className={`stage-dot ${index < done ? "done" : index === done ? "active" : ""}`} />
                        ))}
                      </div>
                    </div>
                  ) : null}

                  {doc.status === "failed" ? (
                    <div style={{ fontSize: 12, color: "var(--color-danger)", background: "#fdf4f2", border: "1px solid #f4d8d2", borderRadius: 8, padding: "7px 9px" }}>
                      {doc.error?.message || "Processing failed."}
                    </div>
                  ) : null}

                  {doc.warnings?.length ? (
                    <div style={{ fontSize: 11.5, color: "var(--color-warning)", display: "flex", gap: 6, alignItems: "flex-start" }}>
                      <Icon name="alert" size={13} />
                      <span>
                        {doc.warnings.length} extraction warning{doc.warnings.length > 1 ? "s" : ""} — inspect the page.
                      </span>
                    </div>
                  ) : null}

                  <div className="doc-actions">
                    <Button size="sm" variant={doc.status === "ready" ? "primary" : "secondary"} icon="chat" disabled={doc.status !== "ready"} onClick={() => void openChat(doc)}>
                      Chat
                    </Button>
                    <Button size="sm" icon="study" disabled={doc.status !== "ready"} onClick={() => navigate(`/study/${doc.id}`)}>
                      Study
                    </Button>
                    <span style={{ marginLeft: "auto", display: "flex", gap: 2 }}>
                      {doc.status === "failed" ? (
                        <IconButton icon="refresh" label="Retry processing" onClick={() => void retry(doc)} />
                      ) : null}
                      <IconButton icon="page" label="Document details" onClick={() => setDetail(doc)} />
                      <IconButton icon="trash" label="Delete document" onClick={() => setDeleteTarget(doc)} />
                    </span>
                  </div>
                </article>
              );
            })}
          </div>
        )}
      </div>

      <Modal
        open={Boolean(detail)}
        title={detail?.title || "Document"}
        onClose={() => setDetail(null)}
        width={620}
        footer={
          detail ? (
            <>
              <Button variant="danger" icon="trash" onClick={() => setDeleteTarget(detail)}>
                Delete
              </Button>
              <span style={{ flex: 1 }} />
              <Button icon="study" disabled={detail.status !== "ready"} onClick={() => navigate(`/study/${detail.id}`)}>
                Study mode
              </Button>
              <Button variant="primary" icon="chat" disabled={detail.status !== "ready"} onClick={() => void openChat(detail)}>
                Open chat
              </Button>
            </>
          ) : null
        }
      >
        {detail ? (
          <div>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 14 }}>
              <StatusPill status={detail.status} />
              <Badge tone="neutral">{detail.page_count || "—"} pages</Badge>
              <Badge tone="neutral">{detail.chunk_count || 0} chunks</Badge>
              <Badge tone="neutral">{formatBytes(detail.size_bytes)}</Badge>
              {detail.embedder?.provider ? <Badge tone="accent" mono>{detail.embedder.provider}</Badge> : null}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12, marginBottom: 14 }}>
              <div>
                <Field label="Category" hint="Override the automatic classification if needed.">
                  <select className="select" value={detail.category || "other"} onChange={(event) => void updateCategory(detail, event.target.value)}>
                    {["research_paper", "lecture_notes", "textbook", "technical_manual", "legal", "business_report", "other", "unknown"].map((value) => (
                      <option key={value} value={value}>
                        {titleCase(value)}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
              <div>
                <Field label="Collection">
                  <select className="select" value={detail.collection_id || ""} onChange={(event) => void assignCollection(detail, event.target.value)}>
                    <option value="">No collection</option>
                    {collections.map((collection) => (
                      <option key={collection.id} value={collection.id}>
                        {collection.name}
                      </option>
                    ))}
                  </select>
                </Field>
              </div>
            </div>

            {detail.error ? (
              <div className="form-error" style={{ marginBottom: 12 }}>
                <strong>{detail.error.code}</strong> — {detail.error.message}
                <div style={{ marginTop: 8 }}>
                  <Button size="sm" icon="refresh" onClick={() => void retry(detail)}>
                    Retry processing
                  </Button>
                </div>
              </div>
            ) : null}

            {detail.warnings?.length ? (
              <div style={{ marginBottom: 14 }}>
                <div className="label">Extraction warnings</div>
                {detail.warnings.slice(0, 6).map((warning, index) => (
                  <div key={index} style={{ fontSize: 12, color: "var(--color-warning)", display: "flex", gap: 6, marginBottom: 4 }}>
                    <Icon name="alert" size={13} />
                    <span>{warning.message}</span>
                  </div>
                ))}
              </div>
            ) : null}

            <div className="label">Detected outline</div>
            {detail.outline?.length ? (
              <div style={{ maxHeight: 200, overflowY: "auto", border: "1px solid var(--color-line)", borderRadius: 9 }}>
                {detail.outline.slice(0, 40).map((item, index) => (
                  <div key={index} style={{ display: "flex", gap: 8, padding: "6px 10px", borderBottom: "1px solid #f2eee7", fontSize: 12.5 }}>
                    <span className="mono" style={{ color: "#99919e", width: 26 }}>p.{item.page_number}</span>
                    <span style={{ paddingLeft: (item.level - 1) * 12 }}>{item.text}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="hint">No headings were detected in this PDF.</div>
            )}
          </div>
        ) : null}
      </Modal>

      <Modal
        open={Boolean(deleteTarget)}
        title="Delete document?"
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={() => void removeDocument()}>
              Delete permanently
            </Button>
          </>
        }
      >
        <p style={{ marginTop: 0, fontSize: 13.5 }}>
          <strong>{deleteTarget?.title}</strong> and its extracted pages, chunks, embeddings, and study material will be
          removed. Conversations will no longer include this document.
        </p>
        <p className="hint">This action cannot be undone.</p>
      </Modal>

      <Modal
        open={collectionModal}
        title="New collection"
        onClose={() => setCollectionModal(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setCollectionModal(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void createCollection()} loading={busy} disabled={!collectionName.trim()}>
              Create
            </Button>
          </>
        }
      >
        <Field label="Collection name" hint="For example: Semester 5, Machine Learning papers, Final-year project.">
          <input
            className="input"
            value={collectionName}
            onChange={(event) => setCollectionName(event.target.value)}
            placeholder="Machine learning research"
            autoFocus
          />
        </Field>
      </Modal>

      {uploading ? (
        <div className="toast" style={{ position: "fixed", bottom: 18, right: 18 }}>
          <Spinner light /> Uploading PDF…
        </div>
      ) : null}
    </div>
  );
}
