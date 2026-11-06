import { ApiError, request } from "@/api/projects";

export interface StoryScene {
  candidate_id: string;
  source_video_id: string;
  source_filename: string;
  start_seconds: number;
  end_seconds: number;
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
}

export async function getStoryDirection(id: string): Promise<StoryDirection> {
  try {
    const value = await request<StoryDirection>(`/projects/${id}/story-direction`, { method: "POST" });
    if (!value || value.project_id !== id || !Array.isArray(value.chapters)) throw new ApiError("추천 편집 방향 응답을 확인할 수 없습니다.");
    return value;
  } catch (error) {
    if (error instanceof ApiError && (error.status === 404 || error.status === 405) && !error.code) throw new ApiError("실행 중인 서버가 추천 편집 방향을 아직 지원하지 않습니다. 서버를 다시 시작한 뒤 사용할 수 있습니다.", error.status);
    if (error instanceof ApiError && error.code === "NO_SCENE_CANDIDATES") throw new ApiError("장면 후보가 없습니다. 먼저 장면 분석을 실행해 주세요.", error.status, error.code);
    throw error;
  }
}
