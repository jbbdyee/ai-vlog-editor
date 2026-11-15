import { ApiError, request } from "@/api/projects";

export interface StoryScene {
  candidate_id: string;
  source_video_id: string;
  source_filename: string;
  /** The found moment (a few seconds). */
  start_seconds: number;
  end_seconds: number;
  /** The moment widened to fit the target length. */
  clip_start_seconds: number;
  clip_end_seconds: number;
}

export interface StoryChapter {
  title: string;
  description: string;
  reason: string;
  scenes: StoryScene[];
  total_seconds: number;
}

export interface StoryDirection {
  project_id: string;
  title: string;
  summary: string;
  chapters: StoryChapter[];
  engine: string;
  notes: string[];
  fallback_reason: string | null;
  target_minutes: number;
  recommended_minutes: number;
  length_reason: string;
  length_options: number[];
  total_seconds: number;
  max_seconds: number;
  footage_seconds: number;
  /** TODO 23: the "오늘 있었던 일" note this recommendation used ("" when none, or when only the length changed). */
  day_brief?: string;
}

/** TODO 23: the saved "오늘 있었던 일" note. An old server without it gives "" instead of an error. */
export async function getDayBrief(id: string): Promise<string> {
  try {
    const value = await request<{ text?: unknown }>(`/projects/${id}/day-brief`);
    return typeof value?.text === "string" ? value.text : "";
  } catch {
    return "";
  }
}

/** Without a target the server (AI) recommends the length; with `from` only the length changes, the chapters stay.
 * A fresh recommendation can carry the day note (`dayBrief`), which the server also saves for the project. */
export async function getStoryDirection(id: string, change?: { targetMinutes: number; from: StoryDirection }, dayBrief?: string): Promise<StoryDirection> {
  const init: RequestInit = { method: "POST" };
  if (!change && dayBrief !== undefined) {
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify({ day_brief: dayBrief.trim() });
  }
  if (change) {
    const { from } = change;
    init.headers = { "Content-Type": "application/json" };
    init.body = JSON.stringify({
      target_minutes: change.targetMinutes,
      reuse: {
        title: from.title, summary: from.summary, engine: from.engine,
        recommended_minutes: from.recommended_minutes, length_reason: from.length_reason,
        chapters: from.chapters.map((chapter) => ({ title: chapter.title, description: chapter.description, reason: chapter.reason, candidate_ids: chapter.scenes.map((scene) => scene.candidate_id) })),
      },
    });
  }
  try {
    const value = await request<StoryDirection>(`/projects/${id}/story-direction`, init);
    if (!value || value.project_id !== id || !Array.isArray(value.chapters)) throw new ApiError("추천 편집 방향 응답을 확인할 수 없습니다.");
    return value;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405) && !error.code) throw new ApiError("실행 중인 서버가 추천 편집 방향을 아직 지원하지 않습니다. 서버를 다시 시작한 뒤 사용할 수 있습니다.", error.status);
    if (error instanceof ApiError && error.code === "NO_SCENE_CANDIDATES") throw new ApiError("장면 후보가 없습니다. 먼저 장면 분석을 실행해 주세요.", error.status, error.code);
    if (error instanceof ApiError && error.code === "STORY_SCENES_GONE") throw new ApiError("이전 추천의 장면이 모두 사라졌습니다. 추천을 다시 받아 주세요.", error.status, error.code);
    throw error;
  }
}

/** 472 -> "7분 52초" */
export function formatDuration(seconds: number): string {
  const total = Math.round(seconds);
  const minutes = Math.floor(total / 60);
  const rest = total % 60;
  if (!minutes) return `${rest}초`;
  return rest ? `${minutes}분 ${rest}초` : `${minutes}분`;
}
