import { useState, type FormEvent } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ApiError } from "../lib/api";
import { useAuth } from "../lib/auth";
import { Icon } from "../components/Icon";
import { Button } from "../components/ui";

export function AuthPage({ mode }: { mode: "login" | "register" }) {
  const { user, login, register } = useAuth();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (user) return <Navigate to="/library" replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError(null);
    if (mode === "register" && password.length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    setBusy(true);
    try {
      if (mode === "login") await login(email.trim(), password);
      else await register(name.trim(), email.trim(), password);
      navigate("/library", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-shell">
      <aside className="auth-brand">
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 11 }}>
            <div className="brand-mark" style={{ width: 40, height: 40, borderRadius: 12 }}>
              <Icon name="logo" size={21} />
            </div>
            <div>
              <div className="brand-name" style={{ fontSize: 18 }}>
                DocuChat
              </div>
              <div className="brand-sub">Document intelligence</div>
            </div>
          </div>

          <h1 className="auth-headline">
            Understand every document.
            <br />
            Verify every answer.
          </h1>
          <p className="auth-sub">
            Upload PDFs, ask questions, and inspect the exact page behind every claim. Built for research papers,
            lecture notes, manuals, and reports.
          </p>

          <div className="auth-features">
            <div className="auth-feature">
              <span className="auth-feature-icon">
                <Icon name="shield" size={14} />
              </span>
              <span>
                <strong style={{ color: "#ece8fb" }}>Evidence-first citations.</strong> Click a claim to open the source
                page and read the supporting passage.
              </span>
            </div>
            <div className="auth-feature">
              <span className="auth-feature-icon">
                <Icon name="search" size={14} />
              </span>
              <span>
                <strong style={{ color: "#ece8fb" }}>Hybrid retrieval.</strong> Dense embeddings plus BM25 and
                reciprocal rank fusion find concepts and exact section numbers.
              </span>
            </div>
            <div className="auth-feature">
              <span className="auth-feature-icon">
                <Icon name="study" size={14} />
              </span>
              <span>
                <strong style={{ color: "#ece8fb" }}>Study mode.</strong> Generate cited study guides, flashcards, and
                quizzes from your own material.
              </span>
            </div>
          </div>
        </div>
        <div className="auth-footnote">
          Every answer is grounded in retrieved pages. When the document does not contain the answer, DocuChat says so.
        </div>
      </aside>

      <main className="auth-panel">
        <div className="auth-card">
          <h1>{mode === "login" ? "Welcome back" : "Create your workspace"}</h1>
          <p className="sub">
            {mode === "login"
              ? "Sign in to your document library and conversations."
              : "The first account created becomes the workspace administrator."}
          </p>

          {error ? <div className="form-error">{error}</div> : null}

          <form onSubmit={submit} noValidate>
            {mode === "register" ? (
              <div className="field">
                <label className="label" htmlFor="name">
                  Full name
                </label>
                <input
                  id="name"
                  className="input"
                  value={name}
                  onChange={(event) => setName(event.target.value)}
                  placeholder="Aarav Sharma"
                  autoComplete="name"
                  required
                  minLength={1}
                />
              </div>
            ) : null}
            <div className="field">
              <label className="label" htmlFor="email">
                Email
              </label>
              <input
                id="email"
                className="input"
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                placeholder="you@college.edu"
                autoComplete="email"
                required
              />
            </div>
            <div className="field">
              <label className="label" htmlFor="password">
                Password
              </label>
              <input
                id="password"
                className="input"
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                placeholder={mode === "register" ? "At least 8 characters" : "Your password"}
                autoComplete={mode === "login" ? "current-password" : "new-password"}
                required
                minLength={mode === "register" ? 8 : 1}
              />
            </div>
            <Button type="submit" variant="primary" size="lg" loading={busy} style={{ width: "100%", marginTop: 6 }}>
              {mode === "login" ? "Sign in" : "Create account"}
            </Button>
          </form>

          <div className="auth-switch">
            {mode === "login" ? (
              <>
                New here? <Link to="/register">Create an account</Link>
              </>
            ) : (
              <>
                Already have an account? <Link to="/login">Sign in</Link>
              </>
            )}
          </div>

          <div style={{ marginTop: 28, paddingTop: 18, borderTop: "1px solid var(--color-line)", color: "#938d98", fontSize: 11.5, display: "flex", gap: 7 }}>
            <Icon name="shield" size={13} />
            <span>Sessions use an HTTP-only cookie. Uploaded PDFs are only accessible to their owner.</span>
          </div>
        </div>
      </main>
    </div>
  );
}
