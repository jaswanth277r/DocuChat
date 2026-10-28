import express from "express";
import cors from "cors";
import jwt from "jsonwebtoken";
import bcrypt from "bcryptjs";
import multer from "multer";
import rateLimit from "express-rate-limit";
import { MongoClient } from "mongodb";
import crypto from "crypto";
import fs from "fs";
import path from "path";

const { MONGO_URL = "mongodb://localhost:27017", JWT_SECRET, INTERNAL_TOKEN,
  RAG_URL = "http://localhost:8000", UPLOAD_DIR = "/data/uploads", PORT = 4000 } = process.env;
if (!JWT_SECRET || !INTERNAL_TOKEN) throw new Error("JWT_SECRET and INTERNAL_TOKEN are required");
fs.mkdirSync(UPLOAD_DIR, { recursive: true });

const db = (await new MongoClient(MONGO_URL).connect()).db("docuchat");
const users = db.collection("users"), docs = db.collection("documents"), messages = db.collection("messages");
await users.createIndex({ email: 1 }, { unique: true });

const rag = (p, { method = "POST", body } = {}) => fetch(`${RAG_URL}${p}`, {
  method, signal: AbortSignal.timeout(200_000),
  headers: { "Content-Type": "application/json", "X-Internal-Token": INTERNAL_TOKEN },
  body: body && JSON.stringify(body) });

const app = express();
app.use(cors());
app.use(express.json({ limit: "100kb" }));

const auth = (req, res, next) => {
  try { req.uid = jwt.verify((req.headers.authorization || "").replace("Bearer ", ""), JWT_SECRET).sub; next(); }
  catch { res.status(401).json({ error: "Please sign in again." }); }
};
const token = (id) => jwt.sign({ sub: id }, JWT_SECRET, { expiresIn: "8h" });
// Ownership is always checked server-side against the token's user id.
const ownDoc = (req, id) => docs.findOne({ _id: String(id), owner_id: req.uid });

app.get("/api/health", (_, res) => res.json({ ok: true }));

const authLimit = rateLimit({ windowMs: 15 * 60_000, limit: 30 });
const cred = (req) => {
  const { email, password } = req.body || {};
  if (typeof email !== "string" || !/^\S+@\S+\.\S+$/.test(email)) return null;
  if (typeof password !== "string" || password.length < 8) return null;
  return { email: email.toLowerCase(), password };
};
app.post("/api/auth/register", authLimit, async (req, res) => {
  const c = cred(req);
  if (!c) return res.status(400).json({ error: "Enter a valid email and a password of 8+ characters." });
  const user = { _id: crypto.randomUUID(), email: c.email, role: "student",
    password_hash: await bcrypt.hash(c.password, 10), created_at: new Date() };
  try { await users.insertOne(user); } catch { return res.status(409).json({ error: "That email is already registered." }); }
  res.json({ token: token(user._id), email: user.email });
});
app.post("/api/auth/login", authLimit, async (req, res) => {
  const c = cred(req);
  const user = c && await users.findOne({ email: c.email });
  if (!user || !(await bcrypt.compare(c.password, user.password_hash)))
    return res.status(401).json({ error: "Incorrect email or password." });
  res.json({ token: token(user._id), email: user.email });
});

const uploadLimit = rateLimit({ windowMs: 3600_000, limit: 10, keyGenerator: (req) => req.uid,
  message: { error: "Upload limit reached (10 per hour). Try again later." } });
const upload = multer({ storage: multer.memoryStorage(), limits: { fileSize: 50 * 1024 * 1024 } });

app.post("/api/documents", auth, uploadLimit, upload.single("file"), async (req, res) => {
  const f = req.file;
  if (!f || f.buffer.subarray(0, 5).toString() !== "%PDF-")
    return res.status(400).json({ error: "Upload a valid PDF file (max 50 MB)." });
  const id = crypto.randomUUID();
  const filePath = path.join(UPLOAD_DIR, `${id}.pdf`);
  fs.writeFileSync(filePath, f.buffer);
  const filename = path.basename(f.originalname).slice(0, 200);
  await docs.insertOne({ _id: id, owner_id: req.uid, filename, path: filePath, status: "queued", created_at: new Date() });
  try {
    const r = await rag("/ingest", { body: { document_id: id, owner_id: req.uid, path: filePath, filename } });
    if (!r.ok) throw new Error();
  } catch {
    await docs.updateOne({ _id: id }, { $set: { status: "failed", error: "Processing service unavailable. Try again." } });
  }
  res.status(202).json({ id, filename, status: "queued" });
});

app.get("/api/documents", auth, async (req, res) => {
  res.json(await docs.find({ owner_id: req.uid }, { projection: { path: 0, owner_id: 0 } })
    .sort({ created_at: -1 }).toArray());
});
app.get("/api/documents/:id/file", auth, async (req, res) => {
  const d = await ownDoc(req, req.params.id);
  if (!d) return res.status(404).json({ error: "Document not found." });
  res.type("application/pdf").sendFile(path.resolve(d.path));
});
app.delete("/api/documents/:id", auth, async (req, res) => {
  const d = await ownDoc(req, req.params.id);
  if (!d) return res.status(404).json({ error: "Document not found." });
  try { await rag(`/documents/${d._id}`, { method: "DELETE" }); } catch {}
  fs.rmSync(d.path, { force: true });
  await docs.deleteOne({ _id: d._id });
  res.json({ deleted: true });
});

app.post("/api/chat", auth, async (req, res) => {
  const { documentIds, question, provider = "groq" } = req.body || {};
  if (!Array.isArray(documentIds) || !documentIds.length || documentIds.length > 20 ||
      !documentIds.every((x) => typeof x === "string") ||
      typeof question !== "string" || !question.trim() || question.length > 2000 ||
      !["groq", "ollama"].includes(provider))
    return res.status(400).json({ error: "Select documents and enter a question." });
  const owned = await docs.countDocuments({ _id: { $in: documentIds }, owner_id: req.uid, status: "indexed" });
  if (owned !== new Set(documentIds).size) return res.status(404).json({ error: "Some documents are missing or not ready." });
  try {
    const r = await rag("/query", { body: { owner_id: req.uid, document_ids: documentIds, question, provider } });
    const data = await r.json();
    if (!r.ok) return res.status(502).json({ error: data.detail || "The answer service failed." });
    await messages.insertOne({ owner_id: req.uid, documentIds, question, ...data, created_at: new Date() });
    res.json(data);
  } catch { res.status(504).json({ error: "The answer service timed out." }); }
});

app.listen(PORT, () => console.log(`gateway on :${PORT}`));
