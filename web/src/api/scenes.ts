import { ApiError, request } from "@/api/projects";

export type SceneRunStatus = "NOT_STARTED" | "QUEUED" | "RUNNING" | "COMPLETED" | "COMPLETED_WITH_WARNINGS" | "FAILED";
export type SceneSourceOutcome = "COMPLETED" | "ABSTAINED" | "FAILED" | "BLOCKED" | "SKIPPED_V1_INCOMPLETE";

export interface SceneSourceStatus {
  source_video_id: string;
  status: SceneSourceOutcome;
  candidate_count: number;
  safe_error_code: string | null;
  warnings: string[];
}
export interface SceneProcessingStatus {
  project_id: string;
  run_status: SceneRunStatus;
  total_sources: number;
  processed_count: number;
  completed_count: number;
  abstained_count: number;
  failed_count: number;
  blocked_count: number;
  skipped_count: number;
  safe_error_code: string | null;
  sources: SceneSourceStatus[];
}
export interface SceneCandidate {
  candidate_id: string;
  source_video_id: string;
  start_seconds: number;
  end_seconds: number;
  evidence: Array<{ modality: string; evidence_type: string; count: number }>;
  /** STT text heard inside the scene; absent on servers older than promotion v0.4. */
  transcript_text?: string | null;
  /** VLM description of what is visible (non-authoritative); absent until scene vision has run. */
  visual_caption?: string | null;
  visual_tags?: string[];
}

const reasonLabels: Record<string, string> = {
  TRANSCRIPT_REACTION_CUE: "감탄·리액션 발화",
  TRANSCRIPT_STRUCTURE: "말하는 구간",
  AUDIO_ACTIVITY: "소리가 살아나는 구간",
  VISUAL_ACTIVITY: "화면 움직임",
  VLM_SCENE_CAPTION: "AI 화면 분석",
};
const cautionLabels: Record<string, string> = { STATIC_INTERVAL: "정지 화면 포함" };

/** Korean "why this scene" labels derived from the observed evidence types (works with any server version). */
export function sceneReasons(candidate: Pick<SceneCandidate, "evidence">): { reasons: string[]; cautions: string[] } {
  const types = new Set(candidate.evidence.map((item) => item.evidence_type));
  const cautions = Object.keys(cautionLabels).filter((type) => types.has(type)).map((type) => cautionLabels[type]);
  if (types.has("LONG_SILENCE") || types.has("SILENCE")) {
    cautions.push(types.has("CONFIRMED_SILENCE")
      ? (types.has("LONG_SILENCE") ? "긴 무음 포함" : "무음 포함")
      : "상대적 오디오 활동 감소 · 실제 무음 미확인");
  }
  return {
    reasons: Object.keys(reasonLabels).filter((type) => types.has(type)).map((type) => reasonLabels[type]),
    cautions,
  };
}
export interface SceneCandidates {
  project_id: string;
  candidates: SceneCandidate[];
}
export interface SceneDiagnostic {
  source_video_id: string;
  status: string;
  has_record: boolean;
  candidate_count: number | null;
  abstain_reason: string | null;
  evidence_counts: Record<string, number | null>;
  evidence_type_counts: Record<string, number>;
  evidence_intervals: Array<{ modality: string; evidence_type: string; start_seconds: number; end_seconds: number }>;
  warnings: string[];
}
export interface SceneDiagnostics {
  project_id: string;
  sources: SceneDiagnostic[];
}

function checkList<T>(value: T, id: string, key: "sources" | "candidates", label: string): T {
  const record = value as Record<string, unknown> | null;
  if (!record || record.project_id !== id || !Array.isArray(record[key])) {
    throw new ApiError(`${label} 응답을 확인할 수 없습니다.`);
  }
  return value;
}

export async function getSceneProcessing(id: string): Promise<SceneProcessingStatus> {
  const value = await request<SceneProcessingStatus>(`/projects/${id}/scene-processing`);
  if (!value || value.project_id !== id || !Array.isArray(value.sources) || typeof value.run_status !== "string") {
    throw new ApiError("장면 분석 상태 응답을 확인할 수 없습니다.");
  }
  return value;
}
export async function startSceneProcessing(id: string): Promise<void> {
  const value = await request<{ project_id: string; accepted: boolean; status_url: string }>(`/projects/${id}/scene-process`, { method: "POST" }, 202);
  if (!value || value.project_id !== id || value.accepted !== true) throw new ApiError("장면 분석 접수 응답을 확인할 수 없습니다.");
}
export async function getSceneCandidates(id: string): Promise<SceneCandidates> {
  return checkList(await request<SceneCandidates>(`/projects/${id}/scene-candidates`), id, "candidates", "장면 후보");
}
export interface SceneVisionStatus { project_id: string; status: string; model: string; total: number; captioned: number; skipped: number; failed: number; error_codes: string[] }
export async function getSceneVision(id: string): Promise<SceneVisionStatus> {
  const value = await request<SceneVisionStatus>(`/projects/${id}/scene-vision`);
  if (!value || value.project_id !== id || typeof value.status !== "string") throw new ApiError("화면 분석 상태 응답을 확인할 수 없습니다.");
  return value;
}
export async function startSceneVision(id: string): Promise<SceneVisionStatus> {
  return request<SceneVisionStatus>(`/projects/${id}/scene-vision`, { method: "POST" }, 202);
}
export async function getSceneDiagnostics(id: string): Promise<SceneDiagnostics> {
  return checkList(await request<SceneDiagnostics>(`/projects/${id}/scene-diagnostics`), id, "sources", "장면 진단");
}
