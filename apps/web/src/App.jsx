import { useEffect, useRef, useState, useCallback } from "react";

export default function App() {
  const [token, setToken] = useState(() => sessionStorage.getItem("token"));
  const api = useCallback(async (path, opts = {}) => {
    const r = await fetch("/api" + path, { ...opts, headers: { ...(opts.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}) } });
    if (opts.raw) return r;
    const data = await r.json().catch(() => ({}));
    if (r.status === 401 && token) { sessionStorage.removeItem("token"); setToken(null); }
    if (!r.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  }, [token]);
  if (!token) return <Login api={api} onToken={(t) => { sessionStorage.setItem("token", t); setToken(t); }} />;
  return <Workspace api={api} onLogout={() => { sessionStorage.removeItem("token"); setToken(null); }} />;
}

function Login({ api, onToken }) {
  const [mode, setMode] = useState("login"), [email, setEmail] = useState(""), [pw, setPw] = useState(""), [err, setErr] = useState("");
  const submit = async (e) => { e.preventDefault(); setErr("");
    try { onToken((await api(`/auth/${mode}`, { method: "POST", body: JSON.stringify({ email, password: pw }) })).token); }
    catch (x) { setErr(x.message); } };
  return <form className="login" onSubmit={submit}>
    <h1>DocuChat</h1>
    <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
    <input type="password" placeholder="Password (8+ characters)" value={pw} onChange={(e) => setPw(e.target.value)} required />
    {err && <p className="err" role="alert">{err}</p>}
    <button className="primary">{mode === "login" ? "Sign in" : "Create account"}</button>
    <button type="button" onClick={() => setMode(mode === "login" ? "register" : "login")}>
      {mode === "login" ? "Create an account" : "I already have an account"}</button>
  </form>;
}

function Workspace({ api, onLogout }) {
  const [docs, setDocs] = useState([]), [sel, setSel] = useState([]), [msgs, setMsgs] = useState([]);
  const [q, setQ] = useState(""), [provider, setProvider] = useState("groq"), [busy, setBusy] = useState(false), [err, setErr] = useState("");
  const [view, setView] = useState(null), blobs = useRef({}), end = useRef();

  const load = useCallback(() => api("/documents").then(setDocs).catch((e) => setErr(e.message)), [api]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (!docs.some((d) => ["queued", "processing"].includes(d.status))) return;
    const t = setInterval(load, 3000); return () => clearInterval(t); }, [docs, load]);
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs]);

  const upload = async (e) => { const f = e.target.files[0]; e.target.value = ""; if (!f) return;
    const fd = new FormData(); fd.append("file", f); setErr("");
    try { await api("/documents", { method: "POST", body: fd }); load(); } catch (x) { setErr(x.message); } };
  const remove = async (id) => { await api(`/documents/${id}`, { method: "DELETE" }).catch((x) => setErr(x.message));
    setSel((s) => s.filter((x) => x !== id)); load(); };
  const ask = async (e) => { e.preventDefault(); if (!q.trim() || !sel.length) return;
    const question = q; setQ(""); setBusy(true); setErr(""); setMsgs((m) => [...m, { role: "q", text: question }]);
    try { const r = await api("/chat", { method: "POST", body: JSON.stringify({ documentIds: sel, question, provider }) });
      setMsgs((m) => [...m, { role: "a", text: r.answer, cites: r.citations }]); }
    catch (x) { setErr(x.message); } finally { setBusy(false); } };
  const open = async (c) => { if (!blobs.current[c.document_id]) {
      const r = await api(`/documents/${c.document_id}/file`, { raw: true });
      blobs.current[c.document_id] = URL.createObjectURL(await r.blob()); }
    setView({ url: blobs.current[c.document_id], page: c.page }); };

  return <div className="app">
    <section className="col" aria-label="Documents">
      <h2>Documents</h2>
      <p><input type="file" accept="application/pdf" onChange={upload} aria-label="Upload a PDF" /></p>
      {!docs.length && <p className="empty">Upload a PDF to start asking questions.</p>}
      {docs.map((d) => <div className="doc" key={d._id}>
        <input type="checkbox" id={d._id} disabled={d.status !== "indexed"} checked={sel.includes(d._id)}
          onChange={(e) => setSel(e.target.checked ? [...sel, d._id] : sel.filter((x) => x !== d._id))} />
        <label htmlFor={d._id}>{d.filename}<div className={`status ${d.status}`}>
          {d.status === "failed" ? d.error : d.status === "indexed" ? `${d.page_count} pages` : "Processing…"}</div></label>
        <button onClick={() => remove(d._id)} aria-label={`Delete ${d.filename}`}>Delete</button>
      </div>)}
      <p><button onClick={onLogout}>Sign out</button></p>
    </section>
    <section className="col" aria-label="Chat">
      <div className="msgs">
        {!msgs.length && <p className="empty">Select one or more indexed documents, then ask a question.</p>}
        {msgs.map((m, i) => m.role === "q" ? <div key={i} className="q">{m.text}</div> :
          <div key={i} className="a">{m.text}<div className="cites">
            {m.cites.map((c) => <button key={c.n} onClick={() => open(c)} title={c.snippet}>[{c.n}] {c.filename}, p.{c.page}</button>)}
          </div></div>)}
        {busy && <div className="empty">Searching your documents…</div>}
        {err && <p className="err" role="alert">{err}</p>}
        <div ref={end} />
      </div>
      <form className="ask" onSubmit={ask}>
        <select value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Model">
          <option value="groq">Cloud (Groq)</option><option value="ollama">Local (Ollama)</option></select>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask about the selected documents" />
        <button className="primary" disabled={busy || !sel.length}>Ask</button>
      </form>
    </section>
    <section className="col viewer" aria-label="PDF viewer">
      {view ? <iframe key={view.url + view.page} src={`${view.url}#page=${view.page}`} title="PDF" />
            : <p className="empty">Click a citation to open that page here.</p>}
    </section>
  </div>;
}
