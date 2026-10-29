export type Role = "student" | "admin";

export interface User {
  id: string;
  email: string;
  name: string;
  role: Role;
  created_at?: string | null;
}

export interface DocError {
  code: string;
  message: string;
}

export interface DocWarning {
  page_number: number | null;
  code: string;
  message: string;
}

export interface DocumentRecord {
  id: string;
  title: string;
  original_name: string;
  status: string;
  progress: number;
  stage_message?: string;
  page_count?: number | null;
  chunk_count?: number;
  category?: string | null;
  category_confidence?: number | null;
  size_bytes?: number;
  warnings?: DocWarning[];
  error?: DocError | null;
  file_available?: boolean;
  collection_id?: string | null;
  created_at?: string;
  updated_at?: string;
  embedder?: { provider?: string; model?: string; dim?: number };
  outline?: { text: string; level: number; page_number: number }[];
  authors?: string[];
  language?: string;
}

export interface DocumentStatus {
  id: string;
  status: string;
  progress: number;
  stage_message?: string;
  error?: DocError | null;
  warnings?: DocWarning[];
  chunk_count: number;
  page_count?: number | null;
  embedder?: { provider?: string; model?: string; dim?: number };
  job?: { id: string; status: string; attempts: number; message?: string } | null;
  updated_at?: string;
}

export interface Collection {
  id: string;
  name: string;
  description?: string | null;
  document_ids: string[];
  document_count: number;
  created_at?: string;
}

export interface Session {
  id: string;
  user_id: string;
  document_ids: string[];
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}

export interface Citation {
  label: string;
  claim_index?: number;
  claim?: string;
  document_id?: string;
  document_title?: string;
  page_number?: number;
  page_count?: number;
  section_path?: string;
  chunk_id?: string;
  excerpt?: string;
  extraction_method?: string;
  status: "verified" | "partial" | "pending" | "invalid" | "unsupported";
  method?: string;
  reason?: string | null;
}

export interface Claim {
  text: string;
  markers: number[];
  cited: boolean;
  citation_status?: string;
}

export interface Coverage {
  claims: number;
  cited: number;
  verified?: number;
  ratio: number;
  status: string;
  invalid_citations: number;
}

export interface Source {
  label: string;
  document_id: string;
  document_title: string;
  page_number: number;
  page_count?: number;
  section_path?: string;
  heading?: string;
  chunk_id?: string;
  excerpt: string;
  text?: string;
  extraction_method?: string;
  chunk_kind?: string;
  score?: number;
  confidence?: number;
}

export interface RetrievalInfo {
  sources: Source[];
  confidence: number;
  sufficient: boolean;
  mode?: string;
  diagnostics?: Record<string, unknown>;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  citations?: Citation[];
  claims?: Claim[];
  coverage?: Coverage | null;
  status?: string;
  provider?: string;
  model?: string;
  latency_ms?: number;
  abstained?: boolean;
  feedback?: { rating: number; comment?: string } | null;
  retrieval?: RetrievalInfo | null;
  created_at?: string;
  is_current?: boolean;
  streaming?: boolean;
  streamSources?: Source[];
  streamConfidence?: number;
  statusStage?: string;
  streamError?: string | null;
  clientKey?: string;
}

export interface SessionDetail {
  session: Session;
  messages: Message[];
  documents: { id: string; title: string; page_count?: number; status: string }[];
}

export interface PageData {
  id?: string;
  page_number: number;
  text: string;
  headings?: { text: string; level: number; page_number: number }[];
  tables?: { title: string; markdown: string; headers: string[]; rows: string[][] }[];
  scanned?: boolean;
  ocr_used?: boolean;
  warnings?: string[];
}

export interface EvidenceResponse {
  chunk: {
    id: string;
    index: number;
    page_number: number;
    section_path?: string;
    text: string;
    extraction_method?: string;
    confidence?: number;
    table?: { headers: string[]; rows: string[][]; title?: string } | null;
  };
  page: PageData;
  document: { id: string; title: string; page_count?: number };
}

export interface FlashcardT {
  id: string;
  document_id: string;
  front: string;
  back: string;
  citation?: string;
  page_number?: number | null;
  section_path?: string;
  difficulty?: string;
  status?: "new" | "known" | "difficult";
}

export interface QuizQuestion {
  type: "mcq" | "true_false" | "short_answer";
  prompt: string;
  options?: string[];
  answer?: string;
  explanation?: string;
  citation?: string;
  page_number?: number | null;
  excerpt?: string;
}

export interface Quiz {
  id: string;
  document_id?: string;
  title: string;
  difficulty: string;
  questions: QuizQuestion[];
  generated_by?: string;
  generation_note?: string | null;
  attempt_count?: number;
}

export interface QuizResult {
  attempt_id?: string;
  score: number;
  correct: number;
  total: number;
  results: {
    index: number;
    prompt: string;
    given: string;
    expected: string;
    correct: boolean;
    feedback: string;
    citation?: string;
    page_number?: number | null;
    source_excerpt?: string;
  }[];
}

export interface StudyGuide {
  id?: string;
  title: string;
  sections: { heading: string; points: { text: string; citation?: string; page_number?: number }[] }[];
  key_terms: { term: string; definition: string; citation?: string; page_number?: number }[];
  generated_by?: string;
  generation_note?: string | null;
}

export interface SystemStatus {
  app: string;
  environment: string;
  mongo: boolean;
  redis: boolean;
  embedder: { provider: string; model: string; dim: number; degraded?: boolean };
  provider: { provider: string; model: string; mode: string; configured: boolean; note?: string };
  limits: Record<string, number>;
  retrieval: Record<string, unknown>;
  user: { id: string; role: string };
}

export interface EvalSummary {
  questions: number;
  answerable: number;
  unanswerable: number;
  recall_at_5: number | null;
  mrr: number | null;
  ndcg_at_5?: number | null;
  answer_accuracy: number | null;
  correct_abstention_rate: number | null;
  false_abstention_rate: number | null;
  citation_validity_rate: number | null;
  citation_support_rate: number | null;
  latency_p50_ms: number;
  latency_p95_ms: number;
  citations?: number;
  invalid_citations?: number;
}

export interface EvalRecord {
  id: string;
  type?: string;
  question: string;
  expected_pages: number[];
  ranked_pages: number[];
  selected_pages: number[];
  recall_at_5: number;
  rr: number;
  confidence: number;
  sufficient: boolean;
  abstained: boolean;
  expected_abstain: boolean;
  answer_hit: boolean;
  answer: string;
  citations_total: number;
  citations_invalid: number;
  citations_supported: number;
  latency_ms: number;
}

export interface EvalRun {
  id?: string;
  dataset: string;
  summary: EvalSummary;
  config?: Record<string, unknown>;
  records?: EvalRecord[];
  created_at: string;
}

export interface AdminMetrics {
  users: number;
  documents: {
    total: number;
    ready: number;
    processing: number;
    failed: number;
    success_rate: number | null;
    avg_ingest_seconds: number | null;
  };
  chunks: number;
  storage_bytes: number;
  chat: {
    sessions: number;
    messages: number;
    latency_p50_ms: number;
    latency_p95_ms: number;
    abstention_rate: number | null;
    citation_validity_rate: number | null;
    tokens_last_7_days: number;
  };
  queue_depth: number | null;
  dead_letters: number | null;
  jobs: {
    id: string;
    type: string;
    status: string;
    attempts: number;
    message?: string;
    created_at?: string;
    error?: { code?: string; message?: string } | null;
  }[];
  embedder: SystemStatus["embedder"];
  provider: SystemStatus["provider"];
  latest_evaluation: { id: string; dataset: string; summary: EvalSummary; created_at: string } | null;
}
