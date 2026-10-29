import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { api, initials, notifySessionsChanged } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useToast } from "../lib/toast";
import type { DocumentRecord, Session } from "../lib/types";
import { Icon } from "./Icon";
import { Badge, Button, Modal, Spinner } from "./ui";

export function Shell() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const toast = useToast();
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [newChatOpen, setNewChatOpen] = useState(false);
  const [documents, setDocuments] = useState<DocumentRecord[]>([]);
  const [selectedDocs, setSelectedDocs] = useState<string[]>([]);
  const [loadingDocs, setLoadingDocs] = useState(false);
  const [creating, setCreating] = useState(false);

  const loadSessions = useCallback(async () => {
    try {
      const data = await api<{ sessions: Session[] }>("/chat/sessions");
      setSessions(data.sessions);
    } catch {
      /* sidebar is non-critical */
    }
  }, []);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions, location.pathname]);

  useEffect(() => {
    const handler = () => void loadSessions();
    window.addEventListener("docuchat:sessions", handler);
    return () => window.removeEventListener("docuchat:sessions", handler);
  }, [loadSessions]);

  useEffect(() => {
    setDrawerOpen(false);
  }, [location.pathname]);

  const openNewChat = async () => {
    setNewChatOpen(true);
    setLoadingDocs(true);
    setSelectedDocs([]);
    try {
      const data = await api<{ documents: DocumentRecord[] }>("/documents");
      setDocuments(data.documents);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not load documents", "error");
    } finally {
      setLoadingDocs(false);
    }
  };

  const createChat = async () => {
    if (!selectedDocs.length) return;
    setCreating(true);
    try {
      const session = await api<Session>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify({ document_ids: selectedDocs }),
      });
      notifySessionsChanged();
      setNewChatOpen(false);
      navigate(`/chat/${session.id}`);
    } catch (error) {
      toast.push(error instanceof Error ? error.message : "Could not start the chat", "error");
    } finally {
      setCreating(false);
    }
  };

  const readyDocuments = useMemo(() => documents.filter((doc) => doc.status === "ready"), [documents]);

  return (
    <div className="shell">
      {drawerOpen ? <button className="sidebar-backdrop" aria-label="Close menu" onClick={() => setDrawerOpen(false)} /> : null}
      <aside className={`sidebar ${drawerOpen ? "open" : ""}`}>
        <div className="sidebar-brand">
          <div className="brand-mark">
            <Icon name="logo" size={19} strokeWidth={1.7} />
          </div>
          <div>
            <div className="brand-name">DocuChat</div>
            <div className="brand-sub">Understand every document</div>
          </div>
        </div>

        <div style={{ padding: "0 12px 8px" }}>
          <button className="btn btn-primary" style={{ width: "100%" }} onClick={openNewChat}>
            <Icon name="plus" size={15} />
            New chat
          </button>
        </div>

        <div className="sidebar-scroll">
          <nav aria-label="Main">
            <div className="sidebar-section-label">Workspace</div>
            <NavLink to="/library" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon name="library" size={16} />
              Library
            </NavLink>
            <NavLink to="/study" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon name="study" size={16} />
              Study mode
            </NavLink>
            {user?.role === "admin" ? (
              <NavLink to="/admin" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
                <Icon name="admin" size={16} />
                Evaluation
              </NavLink>
            ) : null}
            <NavLink to="/settings" className={({ isActive }) => `nav-item ${isActive ? "active" : ""}`}>
              <Icon name="settings" size={16} />
              Settings
            </NavLink>
          </nav>

          <div className="sidebar-section-label" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Recent chats</span>
            <span style={{ fontFamily: "var(--font-mono)", letterSpacing: 0 }}>{sessions.length}</span>
          </div>
          {sessions.length === 0 ? (
            <div style={{ padding: "4px 10px 10px", color: "#736e81", fontSize: 12 }}>No conversations yet.</div>
          ) : (
            sessions.slice(0, 18).map((session) => {
              const active = location.pathname === `/chat/${session.id}`;
              return (
                <Link key={session.id} to={`/chat/${session.id}`} className={`chat-link ${active ? "active" : ""}`} title={session.title}>
                  {session.title}
                </Link>
              );
            })
          )}
        </div>

        <div className="sidebar-user">
          <div className="avatar accent">{initials(user?.name || "U")}</div>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{ fontSize: 12.5, fontWeight: 600, color: "#f0edf7", overflow: "hidden", textOverflow: "ellipsis" }}>
              {user?.name}
            </div>
            <div style={{ fontSize: 10.5, color: "#817b90", textTransform: "capitalize" }}>{user?.role === "admin" ? "Administrator" : "Student"}</div>
          </div>
          <button
            className="icon-btn"
            style={{ color: "#8d879c" }}
            aria-label="Sign out"
            title="Sign out"
            onClick={async () => {
              await logout();
              navigate("/login");
            }}
          >
            <Icon name="logout" size={16} />
          </button>
        </div>
      </aside>

      <div className="main">
        <div className="topbar">
          <button className="icon-btn" aria-label="Open menu" onClick={() => setDrawerOpen(true)}>
            <Icon name="menu" size={19} />
          </button>
          <div className="brand-mark" style={{ width: 28, height: 28, borderRadius: 8 }}>
            <Icon name="logo" size={15} />
          </div>
          <span style={{ fontWeight: 640, fontSize: 14 }}>DocuChat</span>
          <span style={{ marginLeft: "auto" }}>
            <div className="avatar">{initials(user?.name || "U")}</div>
          </span>
        </div>
        <Outlet />
      </div>

      <Modal
        open={newChatOpen}
        title="Start a conversation"
        onClose={() => setNewChatOpen(false)}
        footer={
          <>
            <Button variant="ghost" onClick={() => setNewChatOpen(false)}>
              Cancel
            </Button>
            <Button variant="primary" onClick={createChat} loading={creating} disabled={!selectedDocs.length}>
              Open chat
            </Button>
          </>
        }
      >
        <p style={{ marginTop: 0, color: "var(--color-muted)", fontSize: 13 }}>
          Choose the documents this conversation can use. You can change the scope later.
        </p>
        {loadingDocs ? (
          <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "18px 0" }}>
            <Spinner /> Loading documents…
          </div>
        ) : readyDocuments.length === 0 ? (
          <div className="empty" style={{ padding: "26px 18px" }}>
            <div style={{ fontSize: 13.5, fontWeight: 600, marginBottom: 4 }}>No ready documents</div>
            <div style={{ fontSize: 12.5, color: "var(--color-muted)", marginBottom: 14 }}>
              Upload a PDF first — processing usually takes a few seconds.
            </div>
            <Button icon="upload" onClick={() => { setNewChatOpen(false); navigate("/library"); }}>
              Go to library
            </Button>
          </div>
        ) : (
          <div style={{ display: "grid", gap: 8 }}>
            {readyDocuments.map((doc) => {
              const checked = selectedDocs.includes(doc.id);
              return (
                <label
                  key={doc.id}
                  className="card"
                  style={{
                    display: "flex",
                    gap: 10,
                    alignItems: "flex-start",
                    padding: "11px 12px",
                    cursor: "pointer",
                    borderColor: checked ? "#b9aff8" : undefined,
                    background: checked ? "#fbfaff" : undefined,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={(event) =>
                      setSelectedDocs((current) =>
                        event.target.checked ? [...current, doc.id] : current.filter((id) => id !== doc.id),
                      )
                    }
                    style={{ marginTop: 3, accentColor: "var(--color-accent)" }}
                  />
                  <span style={{ minWidth: 0 }}>
                    <span style={{ display: "block", fontWeight: 600, fontSize: 13 }}>{doc.title}</span>
                    <span style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 3 }}>
                      <Badge tone="neutral" mono>
                        {doc.page_count ?? "—"} pages
                      </Badge>
                      <span style={{ fontSize: 11, color: "var(--color-muted)" }}>{doc.category?.replace(/_/g, " ") || "document"}</span>
                    </span>
                  </span>
                </label>
              );
            })}
          </div>
        )}
      </Modal>
    </div>
  );
}
