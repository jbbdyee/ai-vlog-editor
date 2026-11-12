import { ApiError, request } from "@/api/projects";

export interface ReelOption { key: string; label: string }

export interface ReelOptions {
  formats: ReelOption[];
  modes: ReelOption[];
  paces: ReelOption[];
  lengths: number[];
  default_length: number;
}

export interface ReelScene {
  shot_index: number;
  source_video_id: string;
  source_filename: string;
  start_seconds: number;
  end_seconds: number;
  caption: string;
  /** Item name shown small above the caption (item modes such as try-on and review). */
  label: string;
  is_hook: boolean;
  /** What the screen-reading AI saw in this shot. */
  shot_caption: string;
}

export interface ReelDraft {
  format: string;
  mode: string;
  mode_label: string;
  pace: string;
  pace_label: string;
  target_seconds: number;
  total_seconds: number;
  title: string;
  engine: string;
  scenes: ReelScene[];
  shot_count: number;
  notes: string[];
  fallback_reason: string | null;
}

export interface ReelStatus {
  project_id: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  step: string;
  done: number;
  total: number;
  error_code: string | null;
  draft: ReelDraft | null;
}

export interface ReelRequest { mode: string; pace: string; target_seconds: number }

function unsupported(error: unknown): never {
  if (error instanceof ApiError && (error.status === 404 || error.status === 405) && !error.code) {
    throw new ApiError("실행 중인 서버가 릴스 초안을 아직 지원하지 않습니다. 서버를 다시 시작한 뒤 사용할 수 있습니다.", error.status);
  }
  throw error;
}

function checkOptions(value: ReelOptions): ReelOptions {
  if (!value || ![value.formats, value.modes, value.paces, value.lengths].every(Array.isArray)) throw new ApiError("릴스 선택지 응답을 확인할 수 없습니다.");
  return value;
}

function checkStatus(value: ReelStatus, id: string): ReelStatus {
  if (!value || value.project_id !== id || typeof value.status !== "string" || (value.draft && !Array.isArray(value.draft.scenes))) {
    throw new ApiError("릴스 초안 응답을 확인할 수 없습니다.");
  }
  return value;
}

export async function getReelOptions(): Promise<ReelOptions> {
  try { return checkOptions(await request<ReelOptions>("/projects/reel-options")); } catch (error) { return unsupported(error); }
}

export async function getReelStatus(id: string): Promise<ReelStatus> {
  try { return checkStatus(await request<ReelStatus>(`/projects/${id}/reel-draft`), id); } catch (error) { return unsupported(error); }
}

export async function startReelDraft(id: string, body: ReelRequest): Promise<ReelStatus> {
  try {
    return checkStatus(await request<ReelStatus>(`/projects/${id}/reel-draft`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ format: "short", ...body }),
    }, 202), id);
  } catch (error) { return unsupported(error); }
}
