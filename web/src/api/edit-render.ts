import { ApiError, request } from "@/api/projects";

export interface SceneEditPlan {
  project_id: string;
  candidate_ids: string[];
  invalid_candidate_ids: string[];
}

export interface RenderStatus {
  project_id: string;
  status: "NOT_STARTED" | "QUEUED" | "RUNNING" | "COMPLETED" | "FAILED" | "INTERRUPTED" | "RECONCILIATION_REQUIRED";
  render_id: string | null;
  is_active: boolean;
  succeeded: boolean;
  failed: boolean;
  safe_error_code: string | null;
  download_available: boolean;
  output: { filename: string; duration_seconds: number; video_codec: string | null; audio_codec: string | null; file_size_bytes: number; download_url: string | null } | null;
  hard_subtitle_status: string;
  hard_subtitle_error_code: string | null;
  hard_subtitle_download_available: boolean;
  hard_subtitle_download_url: string | null;
  /** QA-03 per-file SHA-256 check. Optional: older API servers omit these fields. */
  integrity_status?: IntegrityStatus | null;
  subtitle_integrity_status?: IntegrityStatus | null;
  hard_subtitle_integrity_status?: IntegrityStatus | null;
}

export type IntegrityStatus = "VERIFIED" | "MISSING" | "CORRUPT" | "UNVERIFIED";

const baseFileProblems: Record<string, { short: string; detail: string }> = {
  RENDER_FILE_CORRUPT: {
    short: "기본 파일 변형 감지",
    detail: "기본 MP4 파일 내용이 렌더 완료 때 기록한 SHA-256과 다릅니다. 손상됐거나 다른 파일로 바뀌었을 수 있어 재생·다운로드를 막았습니다. 렌더 기록은 삭제하지 않았습니다.",
  },
  RENDER_FILE_UNVERIFIED: {
    short: "무결성 기록 없음",
    detail: "무결성 기록(SHA-256)이 도입되기 전에 완료된 렌더라 파일 내용을 확인할 수 없어 재생·다운로드를 제공하지 않습니다. 렌더 기록은 그대로 보존됩니다.",
  },
  RENDER_FILE_MISSING: {
    short: "기본 파일 누락",
    detail: "기본 MP4 결과 파일을 찾을 수 없습니다. 렌더 기록은 보존되지만 재생·다운로드할 수 없습니다.",
  },
};

/** Why a COMPLETED render cannot be played/downloaded; null when it can (or is not completed). */
export function renderFileProblem(status: RenderStatus): { short: string; detail: string } | null {
  if (status.status !== "COMPLETED" || status.download_available) return null;
  const code = status.integrity_status === "CORRUPT" ? "RENDER_FILE_CORRUPT"
    : status.integrity_status === "UNVERIFIED" ? "RENDER_FILE_UNVERIFIED" : status.safe_error_code;
  return baseFileProblems[code ?? ""] ?? baseFileProblems.RENDER_FILE_MISSING;
}

const subtitleIntegrityNotes: Partial<Record<IntegrityStatus, string>> = {
  CORRUPT: "SRT 파일이 렌더 완료 때와 다릅니다(진단 표시만, SRT 다운로드는 제공하지 않음).",
  MISSING: "SRT 파일을 찾을 수 없습니다(진단 표시만).",
  UNVERIFIED: "SRT 무결성 기록이 없습니다(진단 표시만).",
};

export function subtitleIntegrityNote(status: RenderStatus): string | null {
  return status.subtitle_integrity_status ? subtitleIntegrityNotes[status.subtitle_integrity_status] ?? null : null;
}

const downloadErrorMessages: Record<string, string> = {
  RENDER_FILE_CORRUPT: "기본 MP4 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다.",
  RENDER_FILE_UNVERIFIED: "무결성 기록이 없는 과거 렌더라 다운로드를 제공하지 않습니다.",
  SUBTITLED_RENDER_CORRUPT: "자막 MP4 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다.",
  SUBTITLED_RENDER_UNVERIFIED: "무결성 기록이 없는 자막 MP4라 다운로드를 제공하지 않습니다.",
};

export interface RenderHistory {
  project_id: string;
  items: RenderStatus[];
  next_cursor: string | null;
}

export async function getRenderHistory(id: string): Promise<RenderHistory> {
  const value = await request<RenderHistory>(`/projects/${id}/renders?limit=20`);
  if (!value || value.project_id !== id || !Array.isArray(value.items) ||
      value.items.some((item) => item.project_id !== id || !item.render_id)) {
    throw new ApiError("렌더 기록 응답을 확인할 수 없습니다.");
  }
  return value;
}

function validPlan(value: SceneEditPlan, id: string): SceneEditPlan {
  if (!value || value.project_id !== id || !Array.isArray(value.candidate_ids) || !Array.isArray(value.invalid_candidate_ids)) throw new ApiError("편집 계획 응답을 확인할 수 없습니다.");
  return value;
}

export async function getEditPlan(id: string): Promise<SceneEditPlan> {
  return validPlan(await request<SceneEditPlan>(`/projects/${id}/scene-edit-plan`), id);
}

export async function saveEditPlan(id: string, candidateIds: string[]): Promise<SceneEditPlan> {
  const saved = validPlan(await request<SceneEditPlan>(`/projects/${id}/scene-edit-plan`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ candidate_ids: candidateIds }) }), id);
  if (JSON.stringify(saved.candidate_ids) !== JSON.stringify(candidateIds) || saved.invalid_candidate_ids.length > 0) {
    throw new ApiError("서버가 요청한 장면 순서를 저장했는지 확인할 수 없습니다.");
  }
  return saved;
}

export interface EditSuggestion {
  project_id: string;
  candidate_ids: string[];
  scenes: Array<{ candidate_id: string; reasons: string[] }>;
  total_seconds: number;
  target_seconds: number | null;
  max_count: number | null;
  keywords: string[];
  excluded: string[];
  categories: string[];
  order: string;
  notes: string[];
  /** "rule" or "llm:<provider>/<model>" (absent on older servers = rule). */
  engine?: string;
  interpretation?: string | null;
  mood?: string | null;
  fallback_reason?: string | null;
}

/** Natural-language request -> suggested scene order. The server saves nothing. */
export async function suggestEdit(id: string, text: string): Promise<EditSuggestion> {
  try {
    const value = await request<EditSuggestion>(`/projects/${id}/edit-suggestions`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request: text }) });
    if (!value || value.project_id !== id || !Array.isArray(value.candidate_ids) || !Array.isArray(value.scenes)) throw new ApiError("편집 제안 응답을 확인할 수 없습니다.");
    return value;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405) && !error.code) throw new ApiError("실행 중인 서버가 자연어 편집 요청을 아직 지원하지 않습니다. 서버 업데이트 후 사용할 수 있습니다.", error.status);
    if (error instanceof ApiError && error.code === "NO_SCENE_CANDIDATES") throw new ApiError("장면 후보가 없습니다. 먼저 장면 분석을 실행해 주세요.", error.status, error.code);
    throw error;
  }
}

export async function getRendering(id: string): Promise<RenderStatus> {
  const value = await request<RenderStatus>(`/projects/${id}/rendering`);
  if (!value || value.project_id !== id || typeof value.status !== "string") throw new ApiError("렌더 상태 응답을 확인할 수 없습니다.");
  return value;
}

export async function startRendering(id: string): Promise<void> {
  const value = await request<{ project_id: string; accepted: boolean; status_url: string }>(`/projects/${id}/render`, { method: "POST" }, 202);
  if (!value || value.project_id !== id || value.accepted !== true) throw new ApiError("렌더 접수 응답을 확인할 수 없습니다.");
}

export type DownloadKind = "plain" | "subtitled";

export function downloadPath(status: RenderStatus, projectId: string, kind: DownloadKind): string | null {
  if (status.project_id !== projectId || status.status !== "COMPLETED" || !status.succeeded || !status.render_id) return null;
  const hex = status.render_id.replaceAll("-", "").toLowerCase();
  if (!/^[0-9a-f]{32}$/.test(hex)) return null;
  const expected = `/projects/${projectId}/renders/${hex}/${kind === "plain" ? "download" : "subtitled/download"}`;
  const available = kind === "plain" ? status.download_available : status.hard_subtitle_download_available;
  const url = kind === "plain" ? status.output?.download_url : status.hard_subtitle_download_url;
  return available && url === expected ? expected : null;
}

export async function fetchRenderFile(path: string): Promise<Blob> {
  let response: Response;
  try { response = await fetch(`/api${path}`); }
  catch { throw new ApiError("다운로드 중 서버에 연결할 수 없습니다."); }
  if (!response.ok) {
    let code: string | null = null;
    try { const body = await response.json() as { detail?: { code?: string } }; code = body.detail?.code ?? null; } catch { /* Body may not be JSON. */ }
    throw new ApiError(downloadErrorMessages[code ?? ""] ?? "영상 다운로드에 실패했습니다. 렌더 상태를 다시 확인해 주세요.", response.status, code);
  }
  if (response.headers.get("content-type")?.split(";")[0].trim().toLowerCase() !== "video/mp4") throw new ApiError("다운로드 응답이 MP4가 아닙니다.");
  const blob = await response.blob();
  if (!blob.size) throw new ApiError("다운로드 파일이 비어 있습니다.");
  return blob;
}
