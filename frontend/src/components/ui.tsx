import { useEffect, type ButtonHTMLAttributes, type ReactNode } from "react";
import { Icon, type IconName } from "./Icon";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md" | "lg";

export function Button({
  variant = "secondary",
  size = "md",
  loading = false,
  icon,
  children,
  className = "",
  disabled,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant;
  size?: Size;
  loading?: boolean;
  icon?: IconName;
}) {
  const classes = ["btn", `btn-${variant}`, size === "md" ? "" : `btn-${size}`, className].filter(Boolean).join(" ");
  return (
    <button className={classes} disabled={disabled || loading} {...rest}>
      {loading ? <span className={`spinner ${variant === "primary" ? "light" : ""}`} /> : icon ? <Icon name={icon} size={15} /> : null}
      {children}
    </button>
  );
}

export function IconButton({
  icon,
  label,
  className = "",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { icon: IconName; label: string }) {
  return (
    <button className={`icon-btn ${className}`} aria-label={label} title={label} {...rest}>
      <Icon name={icon} size={16} />
    </button>
  );
}

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

export function Badge({
  tone = "neutral",
  children,
  mono = false,
  className = "",
  title,
}: {
  tone?: Tone;
  children: ReactNode;
  mono?: boolean;
  className?: string;
  title?: string;
}) {
  return (
    <span className={`badge badge-${tone} ${mono ? "badge-mono" : ""} ${className}`.trim()} title={title}>
      {children}
    </span>
  );
}

export function Spinner({ light = false }: { light?: boolean }) {
  return <span className={`spinner ${light ? "light" : ""}`} aria-label="Loading" />;
}

export function Progress({ value, className = "" }: { value: number; className?: string }) {
  return (
    <div className={`progress-track ${className}`} role="progressbar" aria-valuenow={value} aria-valuemin={0} aria-valuemax={100}>
      <div className="progress-fill" style={{ width: `${Math.max(2, Math.min(100, value))}%` }} />
    </div>
  );
}

const STATUS_MAP: Record<string, { tone: Tone; label: string }> = {
  ready: { tone: "success", label: "Ready" },
  failed: { tone: "danger", label: "Failed" },
  deleted: { tone: "neutral", label: "Deleted" },
  uploaded: { tone: "neutral", label: "Uploaded" },
  queued: { tone: "warning", label: "Queued" },
  validating: { tone: "warning", label: "Validating" },
  extracting: { tone: "warning", label: "Extracting" },
  ocr_check: { tone: "warning", label: "OCR check" },
  chunking: { tone: "warning", label: "Chunking" },
  embedding: { tone: "warning", label: "Embedding" },
  indexing: { tone: "warning", label: "Indexing" },
};

export function StatusPill({ status, detail }: { status: string; detail?: string }) {
  const entry = STATUS_MAP[status] || { tone: "neutral" as Tone, label: status };
  const working = !["ready", "failed", "deleted"].includes(status);
  return (
    <span className={`badge badge-${entry.tone}`} title={detail}>
      {working ? <span className="spinner" style={{ width: 10, height: 10, borderWidth: 1.5 }} /> : null}
      {entry.label}
    </span>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  width,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
  width?: number;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    const previous = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = previous;
    };
  }, [open, onClose]);

  if (!open) return null;
  return (
    <div
      className="modal-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div className="modal" role="dialog" aria-modal="true" aria-label={title} style={width ? { width: `min(${width}px, 100%)` } : undefined}>
        <div className="modal-head">
          <h2 className="modal-title">{title}</h2>
          <IconButton icon="close" label="Close dialog" onClick={onClose} />
        </div>
        <div className="modal-body">{children}</div>
        {footer ? <div className="modal-foot">{footer}</div> : null}
      </div>
    </div>
  );
}

export function EmptyState({
  icon = "sparkle",
  title,
  description,
  action,
}: {
  icon?: IconName;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">
        <Icon name={icon} size={21} />
      </div>
      <div style={{ fontWeight: 640, fontSize: 15, marginBottom: 4 }}>{title}</div>
      {description ? <div style={{ color: "var(--color-muted)", fontSize: 13, maxWidth: 460, margin: "0 auto 16px" }}>{description}</div> : null}
      {action}
    </div>
  );
}

export function Field({ label, hint, children, htmlFor }: { label: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="field">
      <label className="label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint ? <div className="hint" style={{ marginTop: 5 }}>{hint}</div> : null}
    </div>
  );
}
