export type KnowledgeBaseStatus = "active" | "deleting" | "error";
export type KnowledgeDocumentStatus =
  | "queued"
  | "parsing"
  | "embedding"
  | "indexing"
  | "ready"
  | "failed"
  | "deleting";

export interface KnowledgeBase {
  id: string;
  user_id: string;
  name: string;
  description: string;
  status: KnowledgeBaseStatus;
  document_count: number;
  chunk_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  knowledge_base_id: string;
  filename: string;
  media_type: string;
  size_bytes: number;
  content_sha256: string;
  status: KnowledgeDocumentStatus;
  version: number;
  index_revision: number;
  chunk_count: number;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeIngestionJob {
  id: string;
  document_id: string;
  operation: "index" | "delete" | "reindex";
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeUploadResult {
  document: KnowledgeDocument;
  job: KnowledgeIngestionJob | null;
  duplicate: boolean;
}

export interface KnowledgeSearchHit {
  id: string;
  knowledge_base_id: string;
  document_id: string;
  content: string;
  metadata: Record<string, unknown>;
  score: number;
  vector_score: number | null;
  text_score: number | null;
}

export interface KnowledgeBindingSelection {
  strategy: "inherit" | "union" | "replace";
  knowledge_base_ids: string[];
}
