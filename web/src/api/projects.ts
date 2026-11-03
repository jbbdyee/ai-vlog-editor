export type ProjectStatus = "CREATED" | "PROCESSING" | "COMPLETED" | "COMPLETED_WITH_WARNINGS" | "FAILED";
export type SourceStatus = "REGISTERED" | "READY" | "PROCESSING" | "COMPLETED" | "FAILED";
export type SplitPolicy = "SINGLE" | "AUTO_SPLIT" | "USER_CONFIRM_SPLIT";

export interface ProcessingSummary {
  total_sources: number;
  completed_count: number;
  failed_count: number;
  blocked_count: number;
  remaining_count: number;
  progress_ratio: number;
}
export interface Project {
  project_id: string;
  name: string;
  status: ProjectStatus;
  split_policy: SplitPolicy;
  target_duration_seconds: number | null;
  instruction: string | null;
  created_at: string;
  updated_at: string;
  source_count: number;
  processing: ProcessingSummary;
}
export interface ProjectListItem {
  project_id: string;
  name: string | null;
  created_at: string;
  updated_at: string;
  source_count: number;
  has_edit_plan: boolean;
  latest_render_status: string | null;
}
export interface ProjectListPage { items: ProjectListItem[]; next_offset: number | null }
export async function listProjects(offset = 0): Promise<ProjectListPage> {
  const result = await request<ProjectListPage>(`/projects?limit=20&offset=${offset}`);
  if (!result || !Array.isArray(result.items) || result.items.length > 20 ||
      !result.items.every((item) => item && isProjectId(item.project_id) && (item.name === null || typeof item.name === "string") &&
        typeof item.created_at === "string" && Number.isFinite(Date.parse(item.created_at)) &&
        Number.isInteger(item.source_count) && item.source_count >= 0 &&
        typeof item.has_edit_plan === "boolean" &&
        (item.latest_render_status === null || typeof item.latest_render_status === "string")) ||
      (result.next_offset !== null && (!Number.isSafeInteger(result.next_offset) || result.next_offset <= offset))) {
    throw new ApiError("프로젝트 목록 응답을 확인할 수 없습니다.");
  }
  return result;
}
export interface Source {
  source_video_id: string;
  original_filename: string;
  processing_status: SourceStatus;
  stages: Array<{ stage: string; status: string; safe_error_code: string | null }>;
}
export interface ProcessingStatus {
  project_id: string;
  project_status: ProjectStatus;
  total_sources: number;
  completed_count: number;
  failed_count: number;
  blocked_count: number;
  remaining_count: number;
  progress_ratio: number;
  sources: Source[];
}
export interface UploadedSource {
  source_video_id: string;
  project_id: string;
  original_filename: string;
  processing_status: SourceStatus;
  duplicate_fingerprint_in_project: boolean;
}

export class ApiError extends Error {
  constructor(message: string, public readonly status: number | null = null, public readonly code: string | null = null) {
    super(message);
    this.name = "ApiError";
  }
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
export function isProjectId(value: string): boolean { return UUID.test(value); }
export function sourceMediaUrl(projectId: string, sourceId: string): string {
  if (!isProjectId(projectId) || !isProjectId(sourceId)) throw new ApiError("올바르지 않은 영상 식별자입니다.");
  return `/api/projects/${projectId}/sources/${sourceId}/media`;
}

function errorFromResponse(status: number, body: unknown): ApiError {
  const detail = typeof body === "object" && body !== null && "detail" in body ? (body as { detail: unknown }).detail : null;
  const record = typeof detail === "object" && detail !== null ? detail as Record<string, unknown> : null;
  const code = typeof record?.code === "string" && /^[A-Z0-9_]{1,80}$/.test(record.code) ? record.code : null;
  const fallback = status === 404 ? "프로젝트를 찾을 수 없습니다." : status === 409 ? "현재 상태와 요청이 충돌합니다. 상태를 다시 확인해 주세요." : "요청을 완료하지 못했습니다.";
  return new ApiError(fallback, status, code);
}

async function readResponse<T>(response: Response): Promise<T> {
  let body: unknown;
  try { body = await response.json(); }
  catch { throw new ApiError(response.status >= 500 ? "서버에 연결할 수 없습니다." : "서버 응답을 읽을 수 없습니다.", response.status); }
  if (!response.ok) throw errorFromResponse(response.status, body);
  return body as T;
}

export async function request<T>(url: string, init?: RequestInit, expectedStatus = 200): Promise<T> {
  try {
    const response = await fetch(`/api${url}`, init);
    const body = await readResponse<T>(response);
    if (response.status !== expectedStatus) throw new ApiError("예상하지 못한 서버 응답입니다.", response.status);
    return body;
  }
  catch (error) {
    if (error instanceof ApiError) throw error;
    throw new ApiError("서버에 연결할 수 없습니다.");
  }
}

export async function createProject(name: string): Promise<Project> {
  const result = await request<Project>("/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, split_policy: "SINGLE" }) }, 201);
  if (!result || !isProjectId(result.project_id)) throw new ApiError("프로젝트 생성 응답을 확인할 수 없습니다.");
  return result;
}
export async function getProject(id: string): Promise<Project> {
  const result = await request<Project>(`/projects/${id}`);
  if (!result || result.project_id !== id) throw new ApiError("프로젝트 조회 응답을 확인할 수 없습니다.");
  return result;
}
export async function getProcessing(id: string): Promise<ProcessingStatus> {
  const result = await request<ProcessingStatus>(`/projects/${id}/processing`);
  if (!result || result.project_id !== id || !Array.isArray(result.sources)) throw new ApiError("처리 상태 응답을 확인할 수 없습니다.");
  return result;
}
export async function startProcessing(id: string): Promise<{ project_id: string; accepted: boolean; status_url: string }> {
  const result = await request<{ project_id: string; accepted: boolean; status_url: string }>(`/projects/${id}/process`, { method: "POST" }, 202);
  if (!result || result.project_id !== id || result.accepted !== true) throw new ApiError("처리 접수 응답을 확인할 수 없습니다.");
  return result;
}

export const MAX_FILE_BYTES = 4 * 1024 * 1024 * 1024;
export function validateVideo(file: File): string | null {
  const ext = file.name.split(".").pop()?.toLowerCase();
  if (ext !== "mov" && ext !== "mp4") return "MOV 또는 MP4 파일을 선택해 주세요.";
  const allowed = ext === "mov" ? ["video/quicktime"] : ["video/mp4", "application/mp4"];
  if (file.type && !allowed.includes(file.type)) return "파일 확장자와 형식이 일치하지 않습니다.";
  if (file.size === 0) return "빈 파일은 업로드할 수 없습니다.";
  if (file.size > MAX_FILE_BYTES) return "이 화면에서는 4 GiB 이하 파일만 업로드할 수 있습니다.";
  return null;
}

export function uploadSource(id: string, file: File, signal: AbortSignal, onProgress: (percent: number | null) => void): Promise<UploadedSource> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${id}/sources`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (event) => onProgress(event.lengthComputable ? Math.round(event.loaded / event.total * 100) : null);
    xhr.onload = () => {
      if (xhr.status !== 201) { reject(errorFromResponse(xhr.status, xhr.response)); return; }
      const body = xhr.response as Partial<UploadedSource> | null;
      if (!body || body.project_id !== id || !body.source_video_id) { reject(new ApiError("서버의 등록 응답을 확인할 수 없습니다.")); return; }
      resolve(body as UploadedSource);
    };
    xhr.onerror = () => reject(new ApiError("업로드 중 서버 연결이 끊겼습니다."));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    const abort = () => xhr.abort();
    signal.addEventListener("abort", abort, { once: true });
    xhr.onloadend = () => signal.removeEventListener("abort", abort);
    if (signal.aborted) { reject(new DOMException("Upload cancelled", "AbortError")); signal.removeEventListener("abort", abort); return; }
    const form = new FormData();
    form.append("file", file, file.name);
    xhr.send(form);
  });
}
