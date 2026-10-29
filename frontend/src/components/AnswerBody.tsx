import type { ReactNode } from "react";
import type { Citation, Coverage } from "../lib/types";
import { Icon } from "./Icon";

const MARKER = /(\*\*[^*]+\*\*|\[S\d+\])/g;

interface AnswerBodyProps {
  content: string;
  citations?: Citation[];
  onCitation?: (citation: Citation) => void;
  streaming?: boolean;
}

export function AnswerBody({ content, citations = [], onCitation, streaming }: AnswerBodyProps) {
  const map = new Map<string, Citation>();
  for (const citation of citations) {
    if (!map.has(citation.label)) map.set(citation.label, citation);
  }

  const renderInline = (text: string, keyPrefix: string) => {
    const parts = text.split(MARKER).filter((part) => part !== "");
    return parts.map((part, index) => {
      const key = `${keyPrefix}-${index}`;
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={key}>{part.slice(2, -2)}</strong>;
      }
      const marker = part.match(/^\[S(\d+)\]$/);
      if (marker) {
        const label = `S${marker[1]}`;
        const citation = map.get(label);
        return (
          <CitationChip
            key={key}
            label={label}
            citation={citation}
            onClick={() => citation && onCitation?.(citation)}
          />
        );
      }
      return <span key={key}>{part}</span>;
    });
  };

  const lines = (content || "").split("\n");
  const blocks: ReactNode[] = [];
  let listItems: string[] = [];
  let paragraph: string[] = [];

  const flushList = (key: string) => {
    if (!listItems.length) return;
    blocks.push(
      <ul key={key}>
        {listItems.map((item, index) => (
          <li key={`${key}-${index}`}>{renderInline(item, `${key}-${index}`)}</li>
        ))}
      </ul>,
    );
    listItems = [];
  };

  const flushParagraph = (key: string) => {
    if (!paragraph.length) return;
    blocks.push(<p key={key}>{renderInline(paragraph.join(" "), key)}</p>);
    paragraph = [];
  };

  lines.forEach((rawLine, index) => {
    const line = rawLine.trimEnd();
    const key = `line-${index}`;
    if (!line.trim()) {
      flushList(`list-${index}`);
      flushParagraph(`p-${index}`);
      return;
    }
    if (/^\*\*[^*]+\*\*$/.test(line.trim())) {
      flushList(`list-${index}`);
      flushParagraph(`p-${index}`);
      blocks.push(
        <div className="md-h" key={key}>
          {line.trim().slice(2, -2)}
        </div>,
      );
      return;
    }
    if (/^[-*]\s+/.test(line)) {
      flushParagraph(`p-${index}`);
      listItems.push(line.replace(/^[-*]\s+/, ""));
      return;
    }
    flushList(`list-${index}`);
    paragraph.push(line.trim());
  });
  flushList("list-final");
  flushParagraph("p-final");

  return (
    <div className="answer">
      {blocks.length ? blocks : <p style={{ color: "var(--color-muted)" }}>{content}</p>}
      {streaming ? <span className="stream-caret" aria-hidden="true" /> : null}
    </div>
  );
}

export function CitationChip({
  label,
  citation,
  onClick,
}: {
  label: string;
  citation?: Citation;
  onClick?: () => void;
}) {
  const status = citation?.status ?? "invalid";
  const cls = status === "invalid" ? "invalid" : status === "pending" ? "pending" : "";
  const page = citation?.page_number;
  const title = citation
    ? `${status === "invalid" ? "Unverified citation" : `Page ${page}`} — ${citation.document_title || "source"}${citation.reason ? `\n${citation.reason}` : ""}`
    : "Citation does not resolve to a retrieved passage";
  return (
    <button type="button" className={`cite-chip ${cls}`} title={title} onClick={onClick} disabled={!citation}>
      {label}
      {page ? ` · p.${page}` : ""}
      {status === "verified" ? <Icon name="check" size={9} strokeWidth={2.4} /> : null}
    </button>
  );
}

export function CoverageBadge({ coverage }: { coverage?: Coverage | null }) {
  if (!coverage) return null;
  if (coverage.status === "all_claims_cited") {
    return (
      <span className="badge badge-success" title="Every substantive claim carries a citation to a verified passage">
        <Icon name="shield" size={11} /> All claims cited
      </span>
    );
  }
  if (coverage.status === "invalid_citations") {
    return (
      <span className="badge badge-danger" title="One or more citations did not resolve to an authorized page">
        <Icon name="alert" size={11} /> Citation check failed
      </span>
    );
  }
  if (coverage.status === "some_claims_uncited" || coverage.status === "mostly_uncited") {
    return (
      <span className="badge badge-warning" title="Some statements in this answer are not tied to a source">
        <Icon name="alert" size={11} /> Some claims uncited
      </span>
    );
  }
  return null;
}

export function SourcesStrip({
  citations,
  onOpen,
}: {
  citations: Citation[];
  onOpen: (citation: Citation) => void;
}) {
  if (!citations.length) return null;
  const seen = new Set<string>();
  const items: Citation[] = [];
  for (const citation of citations) {
    const key = `${citation.document_id}:${citation.page_number}:${citation.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    items.push(citation);
  }
  return (
    <div className="source-strip">
      <span style={{ fontSize: 10.5, color: "#918b98", textTransform: "uppercase", letterSpacing: "0.06em", fontWeight: 600 }}>
        Sources
      </span>
      {items.map((citation, index) => (
        <button
          key={`${citation.label}-${index}`}
          type="button"
          className="source-pill"
          onClick={() => onOpen(citation)}
          title={citation.excerpt || citation.section_path || ""}
        >
          <Icon name="page" size={12} />
          <span style={{ maxWidth: 140, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {citation.document_title || "Document"}
          </span>
          <span className="source-page">p.{citation.page_number}</span>
        </button>
      ))}
    </div>
  );
}
