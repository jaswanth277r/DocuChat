import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { SystemStatus } from "../lib/types";
import { Icon } from "../components/Icon";
import { Badge, Button, Spinner } from "../components/ui";

const LLM_SNIPPET = `# Cloud (Groq example)
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=your-key
LLM_MODEL=llama-3.3-70b-versatile

# Local (Ollama)
LLM_PROVIDER=ollama
LLM_BASE_URL=http://127.0.0.1:11434
LLM_MODEL=qwen2.5:3b-instruct`;

function Dot({ ok }: { ok: boolean }) {
  return (
    <span
      style={{
        width: 7,
        height: 7,
        borderRadius: "50%",
        background: ok ? "var(--color-success)" : "var(--color-danger)",
        display: "inline-block",
        marginRight: 6,
      }}
    />
  );
}

export function SettingsPage() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const [status, setStatus] = useState<SystemStatus | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api<SystemStatus>("/system/status")
      .then(setStatus)
      .catch((error) => toast.push(error instanceof Error ? error.message : "Could not load system status", "error"))
      .finally(() => setLoading(false));
  }, [toast]);

  const copySnippet = async () => {
    try {
      await navigator.clipboard.writeText(LLM_SNIPPET);
      toast.push("Configuration copied", "success");
    } catch {
      toast.push("Clipboard is unavailable", "error");
    }
  };

  return (
    <div className="page">
      <div className="page-narrow" style={{ maxWidth: 900 }}>
        <header className="page-header">
          <div>
            <h1 className="page-title">Settings</h1>
            <p className="page-sub">Account, models, retrieval, and data handling.</p>
          </div>
        </header>

        <div className="section-card">
          <div className="section-card-head">
            <div className="section-card-title">Account</div>
            <Badge tone={user?.role === "admin" ? "accent" : "neutral"}>{user?.role === "admin" ? "Administrator" : "Student"}</Badge>
          </div>
          <div className="section-card-body" style={{ display: "flex", gap: 14, alignItems: "center" }}>
            <div className="avatar accent" style={{ width: 42, height: 42, fontSize: 14 }}>
              {(user?.name || "U")
                .split(" ")
                .slice(0, 2)
                .map((part) => part[0]?.toUpperCase())
                .join("")}
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 620 }}>{user?.name}</div>
              <div style={{ color: "var(--color-muted)", fontSize: 12.5 }}>{user?.email}</div>
            </div>
            <Button
              icon="logout"
              onClick={async () => {
                await logout();
                navigate("/login");
              }}
            >
              Sign out
            </Button>
          </div>
        </div>

        <div className="section-card">
          <div className="section-card-head">
            <div className="section-card-title">System status</div>
            {loading ? <Spinner /> : null}
          </div>
          <div className="section-card-body">
            {status ? (
              <dl className="kv">
                <dt>MongoDB</dt>
                <dd>
                  <Dot ok={status.mongo} /> {status.mongo ? "Connected" : "Unavailable"}
                </dd>
                <dt>Redis job queue</dt>
                <dd>
                  <Dot ok={status.redis} /> {status.redis ? "Connected" : "In-process fallback"}
                </dd>
                <dt>Embedding provider</dt>
                <dd>
                  <span className="mono">{status.embedder.provider}</span> · {status.embedder.model} · {status.embedder.dim} dims
                  {status.embedder.degraded ? <Badge tone="warning">degraded</Badge> : null}
                </dd>
                <dt>Answer generation</dt>
                <dd>
                  <span className="mono">{status.provider.provider}</span> · {status.provider.model}{" "}
                  <Badge tone="neutral" mono>
                    {status.provider.mode}
                  </Badge>
                </dd>
                <dt>Retrieval</dt>
                <dd>
                  {String(status.retrieval.mode)} · top {String(status.retrieval.top_k)} → rerank {String(status.retrieval.rerank_top_n)} ·
                  vector {String(status.retrieval.vector_weight)} / BM25 {String(status.retrieval.bm25_weight)}
                </dd>
                <dt>Citation verification</dt>
                <dd>{status.retrieval.support_verification ? "Enabled when a verifier model is configured" : "Deterministic checks only"}</dd>
              </dl>
            ) : (
              <div className="hint">Status unavailable.</div>
            )}
          </div>
        </div>

        <div className="section-card">
          <div className="section-card-head">
            <div className="section-card-title">Connect a generation model</div>
            <Button size="sm" icon="copy" onClick={() => void copySnippet()}>
              Copy config
            </Button>
          </div>
          <div className="section-card-body">
            <p style={{ marginTop: 0, fontSize: 13, color: "var(--color-muted)" }}>
              Without a configured model, answers are composed from retrieved sentences with verbatim citations. Add a
              provider in <span className="mono">.env</span> and restart the API to enable generative answers. The active
              provider is always displayed in the chat header.
            </p>
            <pre
              className="mono"
              style={{
                background: "#1d1b24",
                color: "#ded9ee",
                padding: 14,
                borderRadius: 10,
                fontSize: 11.5,
                lineHeight: 1.7,
                overflowX: "auto",
                margin: 0,
              }}
            >
              {LLM_SNIPPET}
            </pre>
            <div className="hint" style={{ marginTop: 10, display: "flex", gap: 6 }}>
              <Icon name="shield" size={13} />
              API keys stay server-side. When a cloud model is enabled, retrieved passages are sent to that provider.
            </div>
          </div>
        </div>

        <div className="section-card">
          <div className="section-card-head">
            <div className="section-card-title">Limits and data handling</div>
          </div>
          <div className="section-card-body">
            <dl className="kv">
              <dt>Maximum upload size</dt>
              <dd>{status ? `${status.limits.max_upload_mb} MB` : "—"}</dd>
              <dt>Maximum pages</dt>
              <dd>{status ? status.limits.max_pages : "—"}</dd>
              <dt>Upload rate limit</dt>
              <dd>{status ? `${status.limits.uploads_per_hour} PDFs / hour` : "—"}</dd>
              <dt>Chat rate limit</dt>
              <dd>{status ? `${status.limits.chats_per_hour} messages / hour` : "—"}</dd>
              <dt>Retention</dt>
              <dd>
                {status ? `${status.limits.retention_days} days` : "—"} · originals, pages, chunks, embeddings, and study
                material are deleted together
              </dd>
              <dt>Retrieval confidence floor</dt>
              <dd>{status ? String(status.limits.min_retrieval_confidence) : "—"} · below this, the assistant abstains</dd>
            </dl>
            <div style={{ marginTop: 14, padding: 12, border: "1px solid #eee9e0", borderRadius: 9, background: "#fbfaf7", display: "flex", gap: 9 }}>
              <Icon name="shield" size={16} />
              <div style={{ fontSize: 12.3, color: "#5d5764", lineHeight: 1.55 }}>
                Document text is treated as untrusted data. Instruction-like phrases are stripped from queries before
                retrieval, prompts delimit sources explicitly, and retrieval filters by owner at query time.
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
