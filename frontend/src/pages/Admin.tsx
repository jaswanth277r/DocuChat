import { useCallback, useEffect, useState } from "react";
import { api, formatDate, percent } from "../lib/api";
import { useToast } from "../lib/toast";
import type { AdminMetrics, EvalRun } from "../lib/types";
import { Icon } from "../components/Icon";
import { Badge, Button, Spinner } from "../components/ui";

function metric(value: string | number | null | undefined, label: string, note?: string) {
  return (
    <div className="metric">
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value ?? "—"}</div>
      {note ? <div className="metric-note">{note}</div> : null}
    </div>
  );
}

export function AdminPage() {
  const toast = useToast();
  const [metrics, setMetrics] = useState<AdminMetrics | null>(null);
  const [runs, setRuns] = useState<EvalRun[]>([]);
  const [latest, setLatest] = useState<EvalRun | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);

  const load = useCallback(async () => {
    try {
      const [metricsData, runsData] = await Promise.all([
        api<AdminMetrics>("/admin/metrics"),
        api<{ evaluations: EvalRun[] }>("/admin/evaluations"),
      ]);
      setMetrics(metricsData);
      setRuns(runsData.evaluations);
      if (runsData.evaluations[0]?.id) {
        const detail = await api<EvalRun>(`/admin/evaluations/${runsData.evaluations[0].id}`);
        setLatest(detail);
      } else if (metricsData.latest_evaluation?.id) {
        const detail = await api<EvalRun>(`/admin/evaluations/${metricsData.latest_evaluation.id}`);
        setLatest(detail);
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not load evaluation metrics", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => {
    void load();
  }, [load]);

  const runEvaluation = async () => {
    setRunning(true);
    try {
      const report = await api<EvalRun>("/admin/evaluations/run?dataset=default", { method: "POST" });
      toast.push("Evaluation finished", "success");
      await load();
      if (report?.records) {
        setLatest({
          ...report,
          id: latest?.id,
          created_at: new Date().toISOString(),
        });
      }
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Evaluation failed", "error");
    } finally {
      setRunning(false);
    }
  };

  if (loading) {
    return (
      <div className="page" style={{ display: "grid", placeItems: "center" }}>
        <Spinner />
      </div>
    );
  }

  const summary = latest?.summary || metrics?.latest_evaluation?.summary;
  const records = latest?.records || [];

  return (
    <div className="page">
      <div className="page-narrow">
        <header className="page-header">
          <div>
            <h1 className="page-title">Evaluation & observability</h1>
            <p className="page-sub">Measure retrieval, citation support, abstention, and latency on a fixed test suite.</p>
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <Button icon="refresh" onClick={() => void load()}>
              Refresh
            </Button>
            <Button variant="primary" icon="flask" onClick={() => void runEvaluation()} loading={running}>
              Run evaluation
            </Button>
          </div>
        </header>

        <div className="metric-grid">
          {metric(
            metrics?.documents.success_rate != null ? percent(metrics.documents.success_rate) : "—",
            "Ingestion success",
            `${metrics?.documents.ready ?? 0} ready · ${metrics?.documents.failed ?? 0} failed`,
          )}
          {metric(
            metrics?.documents.avg_ingest_seconds != null ? `${metrics.documents.avg_ingest_seconds}s` : "—",
            "Median ingest time",
            `${metrics?.chunks ?? 0} chunks indexed`,
          )}
          {metric(
            metrics?.chat.latency_p50_ms != null ? `${metrics.chat.latency_p50_ms} ms` : "—",
            "Chat p50 latency",
            `p95 ${metrics?.chat.latency_p95_ms ?? "—"} ms`,
          )}
          {metric(
            metrics?.chat.citation_validity_rate != null ? percent(metrics.chat.citation_validity_rate) : "—",
            "Citation validity",
            "Across stored answers",
          )}
          {metric(
            metrics?.chat.abstention_rate != null ? percent(metrics.chat.abstention_rate) : "—",
            "Abstention rate",
            "Answers with insufficient evidence",
          )}
          {metric(summary?.recall_at_5 != null ? summary.recall_at_5.toFixed(3) : "—", "Recall@5", "Latest evaluation")}
          {metric(summary?.mrr != null ? summary.mrr.toFixed(3) : "—", "MRR", "Latest evaluation")}
          {metric(
            summary?.correct_abstention_rate != null ? percent(summary.correct_abstention_rate) : "—",
            "Correct abstention",
            "Unanswerable questions",
          )}
        </div>

        <div className="section-card">
          <div className="section-card-head">
            <div>
              <div className="section-card-title">Latest evaluation</div>
              <div className="hint">
                {latest?.dataset ? `Dataset: ${latest.dataset}` : "No evaluation has run yet"} ·{" "}
                {latest?.created_at ? formatDate(latest.created_at) : "—"}
              </div>
            </div>
            {summary ? (
              <div style={{ display: "flex", gap: 6 }}>
                <Badge tone="success">citations {percent(summary.citation_validity_rate)}</Badge>
                <Badge tone="accent">support {percent(summary.citation_support_rate)}</Badge>
              </div>
            ) : null}
          </div>
          <div className="section-card-body">
            {!summary ? (
              <div style={{ color: "var(--color-muted)", fontSize: 13 }}>
                Run the evaluation suite to establish a baseline. It ingests two fixture PDFs and runs 12 labelled
                questions covering section numbers, tables, multi-page answers, cross-document conflicts, and
                unanswerable questions.
              </div>
            ) : (
              <>
                <div className="metric-grid" style={{ marginBottom: 8 }}>
                  {metric(summary.questions, "Questions", `${summary.answerable} answerable · ${summary.unanswerable} unanswerable`)}
                  {metric(percent(summary.answer_accuracy), "Answer accuracy", "Expected facts present")}
                  {metric(percent(summary.citation_support_rate), "Citation support", "Verified or partial")}
                  {metric(`${summary.latency_p50_ms} ms`, "Eval p50", `p95 ${summary.latency_p95_ms} ms`)}
                </div>

                <div style={{ overflowX: "auto" }}>
                  <table className="table">
                    <thead>
                      <tr>
                        <th>Question</th>
                        <th>Type</th>
                        <th>Recall@5</th>
                        <th>Confidence</th>
                        <th>Abstained</th>
                        <th>Cited pages</th>
                        <th>Answer</th>
                      </tr>
                    </thead>
                    <tbody>
                      {records.map((record) => {
                        const pass = record.expected_abstain ? record.abstained : record.answer_hit;
                        return (
                          <tr key={record.id}>
                            <td>
                              <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                                <span style={{ marginTop: 2, color: pass ? "var(--color-success)" : "var(--color-warning)" }}>
                                  <Icon name={pass ? "check" : "alert"} size={13} />
                                </span>
                                <span style={{ maxWidth: 300 }}>{record.question}</span>
                              </div>
                            </td>
                            <td>
                              <Badge tone="neutral" mono>
                                {record.type || "question"}
                              </Badge>
                            </td>
                            <td className="mono">{record.recall_at_5.toFixed(2)}</td>
                            <td className="mono">{record.confidence?.toFixed(2)}</td>
                            <td>{record.abstained ? <Badge tone="warning">Yes</Badge> : <Badge tone="neutral">No</Badge>}</td>
                            <td className="mono">{(record.selected_pages || []).join(", ") || "—"}</td>
                            <td style={{ color: "#6b6472", maxWidth: 360 }}>
                              <div style={{ display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical", overflow: "hidden" }}>
                                {record.answer}
                              </div>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16 }}>
          <div className="section-card">
            <div className="section-card-head">
              <div className="section-card-title">Serving configuration</div>
            </div>
            <div className="section-card-body">
              <dl className="kv">
                <dt>Embedding model</dt>
                <dd>
                  {metrics?.embedder.provider} · {metrics?.embedder.model} ({metrics?.embedder.dim}d)
                  {metrics?.embedder.degraded ? <Badge tone="warning">degraded</Badge> : null}
                </dd>
                <dt>Generation</dt>
                <dd>
                  {metrics?.provider.provider} · {metrics?.provider.model} <Badge tone="neutral" mono>{metrics?.provider.mode}</Badge>
                </dd>
                <dt>Retrieval</dt>
                <dd>Dense + BM25 · RRF fusion · heuristic rerank</dd>
                <dt>Queue depth</dt>
                <dd>
                  {metrics?.queue_depth ?? "—"} queued · {metrics?.dead_letters ?? 0} dead letters
                </dd>
                <dt>Storage</dt>
                <dd>{Math.round((metrics?.storage_bytes || 0) / 1024)} KB of PDFs</dd>
                <dt>Tokens (7 days)</dt>
                <dd>{metrics?.chat.tokens_last_7_days ?? 0}</dd>
              </dl>
              <div className="hint" style={{ marginTop: 12 }}>
                Configure a cloud or local model in <span className="mono">.env</span>; the active provider is always shown
                in the chat header.
              </div>
            </div>
          </div>

          <div className="section-card">
            <div className="section-card-head">
              <div className="section-card-title">Recent processing jobs</div>
              <span className="hint">{metrics?.jobs.length || 0} recent jobs</span>
            </div>
            <div className="section-card-body" style={{ padding: 0 }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>Job</th>
                    <th>Status</th>
                    <th>Attempts</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {(metrics?.jobs || []).slice(0, 7).map((job) => (
                    <tr key={job.id}>
                      <td className="mono">{job.type}</td>
                      <td>
                        <Badge tone={job.status === "succeeded" ? "success" : job.status === "failed" ? "danger" : "warning"}>
                          {job.status}
                        </Badge>
                      </td>
                      <td className="mono">{job.attempts}</td>
                      <td>{formatDate(job.created_at)}</td>
                    </tr>
                  ))}
                  {!metrics?.jobs?.length ? (
                    <tr>
                      <td colSpan={4} style={{ color: "var(--color-muted)" }}>
                        No jobs yet.
                      </td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
