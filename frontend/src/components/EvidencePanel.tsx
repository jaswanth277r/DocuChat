import { useEffect, useMemo, useState } from "react";
import type { Source } from "../lib/types";
import { Icon } from "./Icon";
import { Badge, IconButton, Spinner } from "./ui";

export interface ActiveEvidence {
  document_id: string;
  page_number: number;
  chunk_id?: string;
  label?: string;
  excerpt?: string;
  claim?: string;
  document_title?: string;
}

export function EvidencePanel({
  active,
  sources,
  documents,
  onClose,
  mobile = false,
}: {
  active: ActiveEvidence | null;
  sources: Source[];
  documents: { id: string; title: string; page_count?: number }[];
  onClose?: () => void;
  mobile?: boolean;
}) {
  const [tab, setTab] = useState<"pdf" | "passages">("pdf");
  const [documentId, setDocumentId] = useState<string>(active?.document_id || documents[0]?.id || "");
  const [page, setPage] = useState<number>(active?.page_number || 1);
  const [pageInput, setPageInput] = useState(String(active?.page_number || 1));
  const [highlight, setHighlight] = useState<string | null>(active?.excerpt || null);
  const [activeChunk, setActiveChunk] = useState<string | null>(active?.chunk_id || null);
  const [zoom, setZoom] = useState(100);
  const [imageLoading, setImageLoading] = useState(true);
  const [imageError, setImageError] = useState<string | null>(null);

  useEffect(() => {
    if (!active) return;
    setDocumentId(active.document_id);
    setPage(active.page_number);
    setPageInput(String(active.page_number));
    setHighlight(active.excerpt || null);
    setActiveChunk(active.chunk_id || null);
    setTab("pdf");
    setImageLoading(true);
    setImageError(null);
  }, [active]);

  useEffect(() => {
    if (!documents.length) return;
    if (!documentId || !documents.some((doc) => doc.id === documentId)) {
      setDocumentId(documents[0].id);
      setPage(1);
      setPageInput("1");
      setHighlight(null);
    }
  }, [documentId, documents]);

  const currentDoc = useMemo(
    () => documents.find((doc) => doc.id === documentId) || documents.find((doc) => doc.id === active?.document_id),
    [documents, documentId, active],
  );
  const pageCount = currentDoc?.page_count || 1;
  const fileUrl = documentId ? `/api/documents/${documentId}/file` : "";
  const imageUrl = documentId
    ? `/api/documents/${documentId}/pages/${page}/image?scale=2${highlight ? `&highlight=${encodeURIComponent(highlight.slice(0, 180))}` : ""}`
    : "";

  const goTo = (next: number, keepHighlight = false) => {
    const clamped = Math.max(1, Math.min(pageCount, next));
    setPage(clamped);
    setPageInput(String(clamped));
    if (!keepHighlight) setHighlight(null);
    setImageLoading(true);
    setImageError(null);
  };

  const selectSource = (source: Source) => {
    setDocumentId(source.document_id);
    setPage(source.page_number);
    setPageInput(String(source.page_number));
    setActiveChunk(source.chunk_id || null);
    setHighlight(source.excerpt || null);
    setTab("pdf");
    setImageLoading(true);
  };

  return (
    <div className="evidence-panel">
      <div className="evidence-head">
        <div className="evidence-tabs" role="tablist" aria-label="Evidence view">
          <button className={`evidence-tab ${tab === "pdf" ? "active" : ""}`} onClick={() => setTab("pdf")} role="tab" aria-selected={tab === "pdf"}>
            Page
          </button>
          <button
            className={`evidence-tab ${tab === "passages" ? "active" : ""}`}
            onClick={() => setTab("passages")}
            role="tab"
            aria-selected={tab === "passages"}
          >
            Passages {sources.length ? `(${sources.length})` : ""}
          </button>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 2 }}>
          <button
            className="icon-btn"
            onClick={() => setZoom((value) => Math.max(100, value - 20))}
            title="Zoom out"
            aria-label="Zoom out"
            disabled={zoom <= 100}
          >
            <span style={{ fontSize: 16, lineHeight: 1 }}>−</span>
          </button>
          <span className="mono" style={{ fontSize: 10, color: "#8a8391", alignSelf: "center", width: 32, textAlign: "center" }}>
            {zoom}%
          </span>
          <button
            className="icon-btn"
            onClick={() => setZoom((value) => Math.min(200, value + 20))}
            title="Zoom in"
            aria-label="Zoom in"
            disabled={zoom >= 200}
          >
            <span style={{ fontSize: 15, lineHeight: 1 }}>+</span>
          </button>
          {fileUrl ? (
            <a className="icon-btn" href={fileUrl} target="_blank" rel="noreferrer" title="Open original PDF" aria-label="Open original PDF">
              <Icon name="external" size={15} />
            </a>
          ) : null}
          {onClose ? <IconButton icon="close" label={mobile ? "Close evidence" : "Hide evidence panel"} onClick={onClose} /> : null}
        </div>
      </div>

      {tab === "pdf" ? (
        <>
          <div className="page-nav">
            <IconButton icon="chevronLeft" label="Previous page" onClick={() => goTo(page - 1)} disabled={page <= 1} />
            <span>
              Page
              <input
                className="input"
                style={{ display: "inline-block", margin: "0 5px", width: 44, padding: "2px 4px", textAlign: "center" }}
                value={pageInput}
                onChange={(event) => setPageInput(event.target.value.replace(/[^0-9]/g, ""))}
                onBlur={() => goTo(Number(pageInput) || 1)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") goTo(Number(pageInput) || 1);
                }}
                aria-label="Page number"
              />
              of {pageCount}
            </span>
            <IconButton icon="chevronRight" label="Next page" onClick={() => goTo(page + 1)} disabled={page >= pageCount} />
            <span
              style={{
                marginLeft: "auto",
                maxWidth: 180,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
              title={currentDoc?.title || active?.document_title || ""}
            >
              {currentDoc?.title || active?.document_title || ""}
            </span>
          </div>
          {active?.excerpt ? (
            <div style={{ borderBottom: "1px solid var(--color-line)", padding: "10px 14px", background: "#fbfaff" }}>
              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 4 }}>
                {active.label ? (
                  <Badge tone="accent" mono>
                    {active.label}
                  </Badge>
                ) : null}
                <span style={{ fontSize: 10.5, color: "#8a8391" }}>Cited passage · highlighted on the page</span>
              </div>
              <div style={{ fontSize: 11.8, color: "#4d4854", lineHeight: 1.5, maxHeight: 76, overflowY: "auto" }}>{active.excerpt}</div>
            </div>
          ) : null}
          <div className="pdf-scroll">
            {imageError ? (
              <div style={{ display: "grid", placeItems: "center", height: "100%", padding: 24, textAlign: "center", gap: 10 }}>
                <Icon name="alert" size={22} />
                <div style={{ fontSize: 12.5, color: "var(--color-muted)", maxWidth: 260 }}>{imageError}</div>
                <button className="btn btn-sm btn-secondary" onClick={() => { setImageError(null); setImageLoading(true); goTo(page, true); }}>
                  Retry
                </button>
              </div>
            ) : (
              <>
                {imageLoading ? (
                  <div className="pdf-loading">
                    <Spinner />
                  </div>
                ) : null}
                <img
                  key={`${documentId}-${page}-${highlight ? "h" : "n"}`}
                  className="pdf-page"
                  style={{ width: `${zoom}%`, display: imageLoading ? "none" : "block" }}
                  src={imageUrl}
                  alt={`Page ${page} of ${currentDoc?.title || "document"}`}
                  onLoad={() => setImageLoading(false)}
                  onError={() => {
                    setImageLoading(false);
                    setImageError("This page could not be rendered. You can open the original PDF instead.");
                  }}
                />
              </>
            )}
          </div>
        </>
      ) : (
        <div className="evidence-scroll">
          {sources.length === 0 ? (
            <div style={{ color: "var(--color-muted)", fontSize: 13, padding: 10 }}>
              Ask a question to see the passages behind the answer.
            </div>
          ) : (
            sources.map((source) => (
              <div
                key={`${source.chunk_id}-${source.label}`}
                className={`passage ${activeChunk && activeChunk === source.chunk_id ? "active" : ""}`}
                onClick={() => selectSource(source)}
                role="button"
                tabIndex={0}
                onKeyDown={(event) => {
                  if (event.key === "Enter") selectSource(source);
                }}
              >
                <div className="passage-head">
                  <Badge tone="accent" mono>
                    {source.label}
                  </Badge>
                  <span style={{ fontSize: 11, color: "#79727f", fontWeight: 550 }}>page {source.page_number}</span>
                  {source.extraction_method && source.extraction_method !== "text" ? (
                    <Badge tone="warning" mono>
                      {source.extraction_method}
                    </Badge>
                  ) : null}
                  {typeof source.score === "number" ? (
                    <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 10, color: "#9a93a1" }}>
                      rel {Math.round(Math.min(1, source.score) * 100)}%
                    </span>
                  ) : null}
                </div>
                <div className="passage-text">{source.text || source.excerpt}</div>
                <div className="passage-meta">
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "100%" }}>
                    {source.document_title}
                  </span>
                  {source.section_path ? <span>· {source.section_path}</span> : null}
                </div>
              </div>
            ))
          )}
        </div>
      )}
    </div>
  );
}
