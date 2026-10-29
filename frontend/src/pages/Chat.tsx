import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { api, notifySessionsChanged } from "../lib/api";
import { useToast } from "../lib/toast";
import type { Citation, DocumentRecord, Message, Session, SessionDetail, Source, SystemStatus } from "../lib/types";
import { AnswerBody, CoverageBadge, SourcesStrip } from "../components/AnswerBody";
import { EvidencePanel, type ActiveEvidence } from "../components/EvidencePanel";
import { Icon } from "../components/Icon";
import { Badge, Button, EmptyState, IconButton, Modal, Spinner, StatusPill } from "../components/ui";
import { streamRequest } from "../lib/api";

const SUGGESTIONS = [
  { label: "Summarize this document", prompt: "Summarize the key points of this document." },
  { label: "Key definitions", prompt: "What are the key definitions and concepts in this document?" },
  { label: "Important limitations", prompt: "What limitations or caveats does the document mention?" },
  { label: "Find a section", prompt: "What does the document say in its main findings or conclusions section?" },
];

function tempId() {
  return `tmp-${Date.now()}-${Math.floor(Math.random() * 1000)}`;
}

export function ChatPage() {
  const { sessionId } = useParams<{ sessionId: string }>();
  const navigate = useNavigate();
  const toast = useToast();
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [statusLabel, setStatusLabel] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(true);
  const [mobileEvidence, setMobileEvidence] = useState(false);
  const [activeEvidence, setActiveEvidence] = useState<ActiveEvidence | null>(null);
  const [panelSources, setPanelSources] = useState<Source[]>([]);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [availableDocs, setAvailableDocs] = useState<DocumentRecord[]>([]);
  const [scopeSelection, setScopeSelection] = useState<string[]>([]);
  const [scopeBusy, setScopeBusy] = useState(false);
  const [titleDraft, setTitleDraft] = useState("");
  const [editingTitle, setEditingTitle] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [providerStatus, setProviderStatus] = useState<SystemStatus | null>(null);
  const [showJump, setShowJump] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  
  const load = useCallback(
    async (silent = false) => {
      if (!sessionId) return;
      try {
        const data = await api<SessionDetail>(`/chat/sessions/${sessionId}`);
        setDetail(data);
        setMessages(data.messages);
        setTitleDraft(data.session.title);
        const lastWithSources = [...data.messages].reverse().find((message) => message.retrieval?.sources?.length);
        if (lastWithSources?.retrieval) {
          setPanelSources(lastWithSources.retrieval.sources);
          const first = lastWithSources.retrieval.sources[0];
          if (first && !activeEvidence) {
            setActiveEvidence({
              document_id: first.document_id,
              page_number: first.page_number,
              chunk_id: first.chunk_id,
              excerpt: first.excerpt,
              label: first.label,
              document_title: first.document_title,
            });
          }
        }
      } catch (error) {
        if (!silent) {
          toast.push(error instanceof Error ? error.message : "Could not load this conversation", "error");
          navigate("/library");
        }
      } finally {
        setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessionId, navigate, toast],
  );

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    setMessages([]);
    setActiveEvidence(null);
    setPanelSources([]);
    void load();
  }, [load]);

  useEffect(() => {
    api<SystemStatus>("/system/status")
      .then(setProviderStatus)
      .catch(() => undefined);
  }, []);

  const scrollToBottom = useCallback((smooth = true) => {
    bottomRef.current?.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "end" });
  }, []);

  useEffect(() => {
    scrollToBottom(false);
  }, [messages.length, scrollToBottom]);

  useEffect(() => {
    if (streaming) scrollToBottom(false);
  }, [messages, streaming, scrollToBottom]);

  const updateMessage = useCallback((key: string, updater: (message: Message) => Message) => {
    setMessages((current) => current.map((message) => (message.clientKey === key ? updater(message) : message)));
  }, []);

  const send = async (text: string) => {
    if (!sessionId || !text.trim() || streaming) return;
    const content = text.trim();
    setInput("");
    if (textareaRef.current) textareaRef.current.style.height = "auto";
    setStreaming(true);
    setStatusLabel("Searching documents");
    const userMessage: Message = {
      id: tempId(),
      role: "user",
      content,
      created_at: new Date().toISOString(),
    };
    const assistantKey = tempId();
    const assistant: Message = {
      id: assistantKey,
      clientKey: assistantKey,
      role: "assistant",
      content: "",
      statusStage: "Searching documents",
      streaming: true,
      citations: [],
      streamSources: [],
    };
    setMessages((current) => [...current, userMessage, assistant]);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamRequest(
        `/chat/sessions/${sessionId}/messages`,
        { content },
        (event, data) => {
          if (event === "status") {
            setStatusLabel(data.message || "Working");
            updateMessage(assistantKey, (message) => ({ ...message, statusStage: data.message || undefined }));
          } else if (event === "retrieval") {
            setStatusLabel(data.sufficient ? "Writing a grounded answer" : "Checking evidence");
            setPanelSources(data.sources || []);
            const first = data.sources?.[0];
            if (first) {
              setActiveEvidence({
                document_id: first.document_id,
                page_number: first.page_number,
                chunk_id: first.chunk_id,
                excerpt: first.excerpt,
                label: first.label,
                document_title: first.document_title,
              });
            }
            updateMessage(assistantKey, (message) => ({
              ...message,
              statusStage: undefined,
              streamSources: data.sources || [],
              streamConfidence: data.confidence,
              retrieval: {
                sources: data.sources || [],
                confidence: data.confidence,
                sufficient: data.sufficient,
                mode: data.mode,
                diagnostics: data.diagnostics,
              },
            }));
          } else if (event === "start") {
            setStatusLabel(null);
            updateMessage(assistantKey, (message) => ({
              ...message,
              id: data.message_id,
              provider: data.provider,
              model: data.model,
            }));
          } else if (event === "delta") {
            updateMessage(assistantKey, (message) => ({ ...message, content: message.content + (data.text || "") }));
          } else if (event === "citations") {
            updateMessage(assistantKey, (message) => ({
              ...message,
              citations: data.citations || [],
              claims: data.claims || [],
              coverage: data.coverage,
            }));
          } else if (event === "done") {
            updateMessage(assistantKey, (message) => ({
              ...message,
              id: data.message_id,
              streaming: false,
              status: data.status,
              abstained: data.abstained,
              latency_ms: data.latency_ms,
              provider: data.provider,
              model: data.model,
              coverage: data.coverage || message.coverage,
              streamError: data.generation_error || null,
            }));
          } else if (event === "error") {
            updateMessage(assistantKey, (message) => ({
              ...message,
              streaming: false,
              streamError: data.message || "The answer could not be generated.",
            }));
            toast.push(data.message || "The answer could not be generated", "error");
          }
        },
        controller.signal,
      );
      notifySessionsChanged();
    } catch (error) {
      if ((error as Error).name === "AbortError") {
        updateMessage(assistantKey, (message) => ({ ...message, streaming: false, status: "cancelled", statusStage: undefined }));
        await load(true);
        notifySessionsChanged();
      } else {
        updateMessage(assistantKey, (message) => ({
          ...message,
          streaming: false,
          streamError: error instanceof Error ? error.message : "Streaming failed",
        }));
        toast.push(error instanceof Error ? error.message : "Streaming failed", "error");
      }
    } finally {
      setStreaming(false);
      setStatusLabel(null);
      abortRef.current = null;
      window.setTimeout(() => scrollToBottom(), 80);
    }
  };

  const stop = () => {
    abortRef.current?.abort();
  };

  const regenerate = async (message: Message) => {
    if (!sessionId || streaming) return;
    const assistantKey = tempId();
    const placeholder: Message = {
      id: assistantKey,
      clientKey: assistantKey,
      role: "assistant",
      content: "",
      statusStage: "Regenerating answer",
      streaming: true,
      citations: [],
    };
    setMessages((current) => [
      ...current.filter((item) => item.id !== message.id),
      placeholder,
    ]);
    setStreaming(true);
    setStatusLabel("Regenerating answer");
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamRequest(
        `/chat/sessions/${sessionId}/messages/${message.id}/regenerate`,
        {},
        (event, data) => {
          if (event === "retrieval") {
            setPanelSources(data.sources || []);
            updateMessage(assistantKey, (item) => ({
              ...item,
              statusStage: undefined,
              streamSources: data.sources || [],
              retrieval: { sources: data.sources, confidence: data.confidence, sufficient: data.sufficient, mode: data.mode },
            }));
          } else if (event === "start") {
            setStatusLabel(null);
            updateMessage(assistantKey, (item) => ({ ...item, id: data.message_id, provider: data.provider, model: data.model }));
          } else if (event === "delta") {
            updateMessage(assistantKey, (item) => ({ ...item, content: item.content + (data.text || "") }));
          } else if (event === "citations") {
            updateMessage(assistantKey, (item) => ({ ...item, citations: data.citations || [], claims: data.claims || [], coverage: data.coverage }));
          } else if (event === "done") {
            updateMessage(assistantKey, (item) => ({
              ...item,
              streaming: false,
              id: data.message_id,
              status: data.status,
              abstained: data.abstained,
              latency_ms: data.latency_ms,
              coverage: data.coverage,
              streamError: data.generation_error || null,
            }));
          } else if (event === "error") {
            updateMessage(assistantKey, (item) => ({ ...item, streaming: false, streamError: data.message }));
          }
        },
        controller.signal,
      );
      notifySessionsChanged();
    } catch (error) {
      if ((error as Error).name !== "AbortError") {
        updateMessage(assistantKey, (item) => ({ ...item, streaming: false, streamError: error instanceof Error ? error.message : "Regeneration failed" }));
      }
    } finally {
      setStreaming(false);
      setStatusLabel(null);
      abortRef.current = null;
    }
  };

  const feedback = async (message: Message, rating: number) => {
    try {
      await api(`/chat/messages/${message.id}/feedback`, {
        method: "POST",
        body: JSON.stringify({ rating }),
      });
      setMessages((current) =>
        current.map((item) => (item.id === message.id ? { ...item, feedback: { rating } } : item)),
      );
      toast.push("Feedback recorded", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not save feedback", "error");
    }
  };

  const copy = async (message: Message) => {
    try {
      await navigator.clipboard.writeText(message.content);
      toast.push("Answer copied", "success");
    } catch {
      toast.push("Clipboard is unavailable", "error");
    }
  };

  const openScope = async () => {
    setScopeOpen(true);
    setScopeSelection(detail?.session.document_ids || []);
    try {
      const data = await api<{ documents: DocumentRecord[] }>("/documents");
      setAvailableDocs(data.documents.filter((doc) => doc.status === "ready"));
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not load documents", "error");
    }
  };

  const saveScope = async () => {
    if (!sessionId || !scopeSelection.length) return;
    setScopeBusy(true);
    try {
      await api(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify({ document_ids: scopeSelection }),
      });
      setScopeOpen(false);
      await load(true);
      toast.push("Conversation scope updated", "success");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not update scope", "error");
    } finally {
      setScopeBusy(false);
    }
  };

  const saveTitle = async () => {
    if (!sessionId || !detail) return;
    const title = titleDraft.trim() || "New chat";
    setEditingTitle(false);
    if (title === detail.session.title) return;
    try {
      await api(`/chat/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify({ title }) });
      setDetail({ ...detail, session: { ...detail.session, title } });
      notifySessionsChanged();
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not rename the chat", "error");
    }
  };

  const deleteChat = async () => {
    if (!sessionId) return;
    setDeleting(true);
    try {
      await api(`/chat/sessions/${sessionId}`, { method: "DELETE" });
      notifySessionsChanged();
      navigate("/library");
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not delete the chat", "error");
    } finally {
      setDeleting(false);
    }
  };

  const openCitation = (citation: Citation, sources: Source[] | undefined) => {
    if (!citation.document_id || !citation.page_number) {
      toast.push(citation.reason || "This citation did not resolve to a page", "error");
      return;
    }
    if (sources?.length) setPanelSources(sources);
    setActiveEvidence({
      document_id: citation.document_id,
      page_number: citation.page_number,
      chunk_id: citation.chunk_id,
      label: citation.label,
      excerpt: citation.excerpt,
      claim: citation.claim,
      document_title: citation.document_title,
    });
    setPanelOpen(true);
    if (window.matchMedia("(max-width: 980px)").matches) setMobileEvidence(true);
  };

  const documentsForPanel = useMemo(
    () => detail?.documents.map((doc) => ({ id: doc.id, title: doc.title, page_count: doc.page_count })) || [],
    [detail],
  );

  const latestSources = useMemo(() => {
    if (panelSources.length) return panelSources;
    const last = [...messages].reverse().find((message) => message.retrieval?.sources?.length);
    return last?.retrieval?.sources || [];
  }, [panelSources, messages]);

  if (loading) {
    return (
      <div className="page" style={{ display: "grid", placeItems: "center" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", color: "var(--color-muted)" }}>
          <Spinner /> Loading conversation…
        </div>
      </div>
    );
  }

  if (!detail) return null;

  const currentSession: Session = detail.session;
  const provider = providerStatus?.provider;

  return (
    <div className={`chat-layout ${panelOpen ? "" : "panel-closed"}`} style={{ flex: 1, minHeight: 0 }}>
      <div className="chat-main">
        <div className="chat-head">
          <div style={{ minWidth: 0, display: "flex", alignItems: "center", gap: 6 }}>
            {editingTitle ? (
              <input
                className="input"
                style={{ width: 320, padding: "4px 8px", fontSize: 14 }}
                value={titleDraft}
                autoFocus
                onChange={(event) => setTitleDraft(event.target.value)}
                onBlur={() => void saveTitle()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") void saveTitle();
                  if (event.key === "Escape") {
                    setEditingTitle(false);
                    setTitleDraft(currentSession.title);
                  }
                }}
              />
            ) : (
              <button
                className="chat-title"
                onClick={() => setEditingTitle(true)}
                title="Rename conversation"
                style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}
              >
                {currentSession.title}
              </button>
            )}
            {provider ? (
              <span title={provider.note || `${provider.provider} · ${provider.model}`}>
                <Badge tone={provider.provider === "extractive" ? "neutral" : "accent"} mono>
                  {provider.provider === "extractive" ? "grounded" : provider.provider}
                </Badge>
              </span>
            ) : null}
          </div>
          <div style={{ marginLeft: "auto", display: "flex", gap: 2, alignItems: "center" }}>
            <Button size="sm" variant="ghost" icon="plus" onClick={() => void openScope()}>
              Documents
            </Button>
            <a className="icon-btn" href={`/api/chat/sessions/${currentSession.id}/export`} title="Export conversation" aria-label="Export conversation">
              <Icon name="copy" size={15} />
            </a>
            <IconButton
              icon="panel"
              label={panelOpen ? "Hide evidence panel" : "Show evidence panel"}
              onClick={() => setPanelOpen((value) => !value)}
              className="desktop-only"
            />
            <IconButton icon="trash" label="Delete conversation" onClick={() => setDeleteOpen(true)} />
          </div>
        </div>

        <div className="scope-row">
          {detail.documents.map((doc) => (
            <span className="scope-chip" key={doc.id} title={doc.title}>
              <Icon name="file" size={11} />
              <span>{doc.title}</span>
              <span className="mono" style={{ color: "#9a93a1" }}>
                {doc.page_count ?? "—"}p
              </span>
            </span>
          ))}
          <button className="scope-chip" onClick={() => void openScope()} style={{ borderStyle: "dashed", color: "#7b7483" }}>
            <Icon name="plus" size={11} /> Edit scope
          </button>
        </div>

        <div
          className="messages"
          ref={scrollRef}
          onScroll={(event) => {
            const element = event.currentTarget;
            setShowJump(element.scrollHeight - element.scrollTop - element.clientHeight > 220);
          }}
        >
          <div className="messages-inner">
            {messages.length === 0 ? (
              <div style={{ padding: "36px 0 10px" }}>
                <div style={{ width: 46, height: 46, borderRadius: 14, background: "var(--color-accent-soft)", color: "var(--color-accent)", display: "grid", placeItems: "center", marginBottom: 14 }}>
                  <Icon name="sparkle" size={22} />
                </div>
                <h2 style={{ margin: "0 0 6px", fontSize: 21, letterSpacing: "-0.02em" }}>Ask anything about this document</h2>
                <p style={{ margin: "0 0 20px", color: "var(--color-muted)", fontSize: 13.5, maxWidth: 560 }}>
                  Answers are built only from retrieved pages. Click a citation to open the exact page beside the chat.
                </p>
                <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                  {SUGGESTIONS.map((suggestion) => (
                    <button
                      key={suggestion.label}
                      className="chip"
                      style={{ padding: "8px 13px", fontSize: 12.5 }}
                      onClick={() => void send(suggestion.prompt)}
                    >
                      {suggestion.label}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}

            {messages.map((message) =>
              message.role === "user" ? (
                <div className="msg user" key={message.clientKey || message.id}>
                  <div className="msg-avatar user">You</div>
                  <div className="msg-body">{message.content}</div>
                </div>
              ) : (
                <div className="msg assistant" key={message.clientKey || message.id}>
                  <div className="msg-avatar assistant">
                    <Icon name="logo" size={14} />
                  </div>
                  <div className="msg-body">
                    {message.streaming && !message.content ? (
                      <div className="status-line">
                        <Spinner />
                        <span>{message.statusStage || "Working"}</span>
                      </div>
                    ) : null}

                    {message.streamSources?.length ? (
                      <div className="source-strip" style={{ marginBottom: message.content ? 8 : 4 }}>
                        {message.streamSources.slice(0, 4).map((source) => (
                          <button
                            key={`${source.label}-${source.chunk_id}`}
                            className="source-pill"
                            onClick={() =>
                              setActiveEvidence({
                                document_id: source.document_id,
                                page_number: source.page_number,
                                chunk_id: source.chunk_id,
                                excerpt: source.excerpt,
                                label: source.label,
                                document_title: source.document_title,
                              })
                            }
                          >
                            <Badge tone="accent" mono>
                              {source.label}
                            </Badge>
                            <span className="source-page">p.{source.page_number}</span>
                          </button>
                        ))}
                        {typeof message.streamConfidence === "number" ? (
                          <span style={{ fontSize: 10.5, color: "#9a93a1" }}>confidence {Math.round(message.streamConfidence * 100)}%</span>
                        ) : null}
                      </div>
                    ) : null}

                    {message.content ? (
                      <AnswerBody
                        content={message.content}
                        citations={message.citations}
                        streaming={message.streaming}
                        onCitation={(citation) => openCitation(citation, message.retrieval?.sources)}
                      />
                    ) : null}

                    {message.streamError ? (
                      <div className="form-error" style={{ marginTop: 10, marginBottom: 0 }}>
                        <div style={{ display: "flex", gap: 6, alignItems: "flex-start" }}>
                          <Icon name="alert" size={14} />
                          <span>{message.streamError}</span>
                        </div>
                      </div>
                    ) : null}

                    {!message.streaming ? (
                      <>
                        <div className="msg-meta">
                          <CoverageBadge coverage={message.coverage} />
                          {message.abstained ? <Badge tone="warning">No supporting evidence</Badge> : null}
                          {message.status === "cancelled" ? <Badge tone="neutral">Stopped</Badge> : null}
                          {message.status === "incomplete" ? <Badge tone="warning">Partial answer</Badge> : null}
                          <span style={{ fontSize: 10.5, color: "#9a93a1", display: "flex", gap: 7, alignItems: "center" }}>
                            {message.model ? <span className="mono">{message.model}</span> : null}
                            {message.latency_ms ? <span>{Math.round(message.latency_ms)} ms</span> : null}
                          </span>
                          <div className="msg-actions">
                            <IconButton icon="copy" label="Copy answer" onClick={() => void copy(message)} />
                            <IconButton icon="refresh" label="Regenerate answer" onClick={() => void regenerate(message)} disabled={streaming} />
                            <IconButton
                              icon="thumbsUp"
                              label="Helpful answer"
                              onClick={() => void feedback(message, 1)}
                              style={{ color: message.feedback?.rating === 1 ? "var(--color-success)" : undefined }}
                            />
                            <IconButton
                              icon="thumbsDown"
                              label="Unhelpful answer"
                              onClick={() => void feedback(message, -1)}
                              style={{ color: message.feedback?.rating === -1 ? "var(--color-danger)" : undefined }}
                            />
                          </div>
                        </div>
                        <SourcesStrip
                          citations={message.citations || []}
                          onOpen={(citation) => openCitation(citation, message.retrieval?.sources)}
                        />
                      </>
                    ) : null}
                  </div>
                </div>
              ),
            )}
            <div ref={bottomRef} />
          </div>
        </div>

        {showJump ? (
          <div style={{ position: "relative" }}>
            <button
              className="icon-btn"
              style={{ position: "absolute", right: 24, bottom: 8, background: "#fff", border: "1px solid var(--color-line)", boxShadow: "var(--shadow-md)", zIndex: 5 }}
              onClick={() => scrollToBottom()}
              aria-label="Scroll to latest message"
            >
              <Icon name="chevronDown" size={16} />
            </button>
          </div>
        ) : null}

        <div className="composer-wrap">
          <div className="composer">
            <textarea
              ref={textareaRef}
              rows={1}
              placeholder="Ask about these documents…"
              value={input}
              disabled={streaming}
              onChange={(event) => {
                setInput(event.target.value);
                const element = event.currentTarget;
                element.style.height = "auto";
                element.style.height = `${Math.min(element.scrollHeight, 160)}px`;
              }}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  void send(input);
                }
              }}
              aria-label="Ask a question"
            />
            {streaming ? (
              <button className="btn btn-danger" onClick={stop} title="Stop generating">
                <Icon name="stop" size={14} />
                Stop
              </button>
            ) : (
              <button className="btn btn-primary" onClick={() => void send(input)} disabled={!input.trim()} aria-label="Send question">
                <Icon name="send" size={15} />
              </button>
            )}
          </div>
          <div className="composer-hint">
            <span>{statusLabel || "Answers cite real pages — click a citation to verify."}</span>
            <span>
              {detail.documents.length} document{detail.documents.length === 1 ? "" : "s"} in scope
              {provider ? ` · ${provider.provider === "extractive" ? "extractive grounding" : provider.model}` : ""}
            </span>
          </div>
        </div>
      </div>

      {panelOpen || mobileEvidence ? (
        <div className={mobileEvidence ? "mobile-evidence" : undefined}>
          <EvidencePanel
            active={activeEvidence}
            sources={latestSources}
            documents={documentsForPanel}
            onClose={() => {
              if (mobileEvidence) setMobileEvidence(false);
              else setPanelOpen(false);
            }}
            mobile={mobileEvidence}
          />
        </div>
      ) : null}

      <Modal
        open={scopeOpen}
        title="Documents in this conversation"
        onClose={() => setScopeOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setScopeOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void saveScope()} loading={scopeBusy} disabled={!scopeSelection.length}>
              Save scope
            </Button>
          </>
        }
      >
        <p style={{ marginTop: 0, color: "var(--color-muted)", fontSize: 13 }}>
          Retrieval is restricted to the selected documents. Removing a document does not delete it from your library.
        </p>
        <div style={{ display: "grid", gap: 8 }}>
          {availableDocs.map((doc) => {
            const checked = scopeSelection.includes(doc.id);
            return (
              <label key={doc.id} className="card" style={{ display: "flex", gap: 10, alignItems: "flex-start", padding: "10px 12px", cursor: "pointer" }}>
                <input
                  type="checkbox"
                  checked={checked}
                  style={{ marginTop: 3, accentColor: "var(--color-accent)" }}
                  onChange={(event) =>
                    setScopeSelection((current) =>
                      event.target.checked ? [...current, doc.id] : current.filter((id) => id !== doc.id),
                    )
                  }
                />
                <span>
                  <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>{doc.title}</span>
                  <span style={{ fontSize: 11.5, color: "var(--color-muted)" }}>
                    {doc.page_count || "—"} pages · {doc.category?.replace(/_/g, " ") || "document"}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </Modal>

      <Modal
        open={deleteOpen}
        title="Delete this conversation?"
        onClose={() => setDeleteOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setDeleteOpen(false)}>
              Cancel
            </Button>
            <Button variant="danger" loading={deleting} onClick={() => void deleteChat()}>
              Delete conversation
            </Button>
          </>
        }
      >
        <p style={{ marginTop: 0, fontSize: 13.5 }}>
          All messages and citations in <strong>{currentSession.title}</strong> will be removed. Your documents stay in
          the library.
        </p>
      </Modal>
    </div>
  );
}
