import { ApiError, request } from "@/api/projects";

/** TODO 21: the long-form video with the spoken lines (and a few inner thoughts) burned in. */
export interface CaptionedVideo {
  render_id: string;
  duration_seconds: number;
  file_size_bytes: number;
  line_count: number;
  thoughts: string[];
  thought_engine: string;
  matches_render: boolean;
  url: string;
}

export interface CaptionedVideoStatus {
  project_id: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  step: string;
  done: number;
  total: number;
  error_code: string | null;
  latest_render_id: string | null;
  video: CaptionedVideo | null;
}

function check(value: CaptionedVideoStatus, id: string): CaptionedVideoStatus {
  if (!value || value.project_id !== id || typeof value.status !== "string" || (value.video && typeof value.video.url !== "string")) {
    throw new ApiError("자막 영상 응답을 확인할 수 없습니다.");
  }
  return value;
}

function unsupported(error: unknown): never {
  if (error instanceof ApiError && (error.status === 404 || error.status === 405) && !error.code) {
    throw new ApiError("실행 중인 서버가 자막 입히기를 아직 지원하지 않습니다. 서버를 다시 시작한 뒤 사용할 수 있습니다.", error.status);
  }
  throw error;
}

export function captionedVideoSrc(video: CaptionedVideo): string {
  return `/api${video.url}`;
}

export async function getCaptionedVideo(id: string): Promise<CaptionedVideoStatus> {
  try { return check(await request<CaptionedVideoStatus>(`/projects/${id}/captioned-video`), id); } catch (error) { return unsupported(error); }
}

export async function startCaptionedVideo(id: string): Promise<CaptionedVideoStatus> {
  try { return check(await request<CaptionedVideoStatus>(`/projects/${id}/captioned-video`, { method: "POST" }, 202), id); } catch (error) { return unsupported(error); }
}
