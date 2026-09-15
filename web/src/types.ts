export type SourceType = "local_import" | "web_upload" | "external_web";
export type TaskStatus = "queued" | "running" | "completed" | "failed";

export interface Session {
  username: string;
  auth_kind: "session" | "bearer";
  csrf_token: string | null;
}

export interface KnowledgeBase {
  id: string;
  name: string;
  created_at: string;
}

export interface DocumentSummary {
  id: string;
  knowledge_base_id: string;
  logical_path: string;
}

export interface DocumentDetail {
  document_id: string;
  knowledge_base_id: string;
  logical_path: string;
  current_version: number;
  version_count: number;
  source_type: SourceType;
  source_uri: string;
  content_hash: string;
  updated_at: string;
  ingested_at: string;
  status: string;
  parsed_content_preview: string;
  preview_truncated: boolean;
}

export interface DocumentVersion {
  document_id: string;
  knowledge_base_id: string;
  logical_path: string;
  version: number;
  source_type: SourceType;
  source_uri: string;
  content_hash: string;
  updated_at: string;
  ingested_at: string;
  status: string;
  parsed_content?: string;
  pages?: Array<{ raw_content: string }>;
}

export interface TaskError {
  code: string;
  message: string;
}

export interface ResearchTask {
  id: string;
  query: string;
  status: TaskStatus;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error: TaskError | null;
}

export interface ResearchInput {
  query: string;
  knowledge_base_ids: string[];
  required_claims: string[];
  required_source_types: SourceType[];
  minimum_distinct_sources: number;
  require_current_version: boolean;
  as_of?: string;
  max_deep_calls: number;
}

export interface CliToken {
  id: string;
  label: string;
  created_at: string;
  revoked_at: string | null;
  last_used_at: string | null;
}

export interface IssuedCliToken extends CliToken {
  token: string;
}

export interface ProviderStatus {
  research_provider: { configured: boolean; detail: string };
  web_search_provider: { configured: boolean; detail: string };
}
