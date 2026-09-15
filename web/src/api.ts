import { z } from "zod";
import type {
  CliToken,
  DocumentDetail,
  DocumentSummary,
  DocumentVersion,
  IssuedCliToken,
  KnowledgeBase,
  ProviderStatus,
  ResearchInput,
  ResearchTask,
  Session,
} from "./types";

let csrfToken: string | null = null;

const sessionSchema = z.object({
  username: z.string(),
  auth_kind: z.enum(["session", "bearer"]),
  csrf_token: z.string().nullable(),
});

const knowledgeBaseSchema = z.object({
  id: z.string(),
  name: z.string(),
  created_at: z.string(),
});

const taskSchema = z.object({
  id: z.string(),
  query: z.string(),
  status: z.enum(["queued", "running", "completed", "failed"]),
  created_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),
  error: z.object({ code: z.string(), message: z.string() }).nullable(),
});

export class ApiError extends Error {
  status: number;
  code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function isMutation(method: string) {
  return !["GET", "HEAD", "OPTIONS"].includes(method.toUpperCase());
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method ?? "GET";
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (isMutation(method) && csrfToken) {
    headers.set("X-CSRF-Token", csrfToken);
  }
  const response = await fetch(path, { ...init, method, headers, credentials: "include" });
  const contentType = response.headers.get("content-type") ?? "";
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = payload?.detail;
    const code = typeof detail === "object" ? detail.code : "request_failed";
    const message = typeof detail === "object" ? detail.message : "请求失败";
    throw new ApiError(response.status, code ?? "request_failed", message ?? "请求失败");
  }
  return payload as T;
}

export function setCsrfToken(value: string | null) {
  csrfToken = value;
}

export async function getSession(): Promise<Session> {
  const session = sessionSchema.parse(await request<unknown>("/api/auth/session"));
  setCsrfToken(session.csrf_token);
  return session;
}

export async function login(username: string, password: string): Promise<Session> {
  const session = sessionSchema.parse(await request<unknown>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  }));
  setCsrfToken(session.csrf_token);
  return session;
}

export async function logout() {
  await request("/api/auth/logout", { method: "POST" });
  setCsrfToken(null);
}

export async function listKnowledgeBases(): Promise<KnowledgeBase[]> {
  return z.array(knowledgeBaseSchema).parse(await request("/api/kbs"));
}

export function createKnowledgeBase(name: string): Promise<KnowledgeBase> {
  return request("/api/kbs", { method: "POST", body: JSON.stringify({ name }) });
}

export function renameKnowledgeBase(id: string, name: string): Promise<KnowledgeBase> {
  return request(`/api/kbs/${id}`, { method: "PATCH", body: JSON.stringify({ name }) });
}

export function listDocuments(kbId: string): Promise<DocumentSummary[]> {
  return request(`/api/kbs/${kbId}/documents`);
}

export function getDocument(kbId: string, documentId: string): Promise<DocumentDetail> {
  return request(`/api/kbs/${kbId}/documents/${documentId}`);
}

export function listVersions(kbId: string, documentId: string): Promise<DocumentVersion[]> {
  return request(`/api/kbs/${kbId}/documents/${documentId}/versions`);
}

export function getVersion(kbId: string, documentId: string, version: number): Promise<DocumentVersion> {
  return request(`/api/kbs/${kbId}/documents/${documentId}/versions/${version}`);
}

export function uploadDocument(kbId: string, file: File, logicalPath: string) {
  const form = new FormData();
  form.set("logical_path", logicalPath);
  form.set("file", file);
  return request<DocumentVersion>(`/api/kbs/${kbId}/documents`, {
    method: "POST",
    body: form,
  });
}

export async function createResearch(input: ResearchInput): Promise<{ task_id: string }> {
  return request("/api/research", { method: "POST", body: JSON.stringify(input) });
}

export async function listResearch(): Promise<ResearchTask[]> {
  return z.array(taskSchema).parse(await request("/api/research"));
}

export async function getResearchTask(id: string): Promise<ResearchTask> {
  return taskSchema.parse(await request(`/api/research/${id}`));
}

export function getReport(id: string): Promise<string> {
  return request(`/api/research/${id}/report`);
}

export function getSources(id: string): Promise<Array<Record<string, unknown>>> {
  return request(`/api/research/${id}/sources`);
}

export function getTrace(id: string): Promise<Array<Record<string, unknown>>> {
  return request(`/api/research/${id}/trace`);
}

export function getMetrics(id: string): Promise<Record<string, unknown>> {
  return request(`/api/research/${id}/metrics`);
}

export function getProviderStatus(): Promise<ProviderStatus> {
  return request("/api/settings/status");
}

export function listCliTokens(): Promise<CliToken[]> {
  return request("/api/auth/tokens");
}

export function issueCliToken(label: string): Promise<IssuedCliToken> {
  return request("/api/auth/tokens", { method: "POST", body: JSON.stringify({ label }) });
}

export function revokeCliToken(id: string) {
  return request(`/api/auth/tokens/${id}`, { method: "DELETE" });
}

export function createBackup(): Promise<{
  backup_id: string;
  filename: string;
  download_url: string;
}> {
  return request("/api/backups", { method: "POST" });
}

export function createExport(): Promise<{
  export_id: string;
  filename: string;
  download_url: string;
}> {
  return request("/api/exports", { method: "POST" });
}
