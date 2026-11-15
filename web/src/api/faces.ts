import { ApiError, request } from "@/api/projects";

/** TODO 25: my face photos (shared by every project) and the long-form video with other people's faces hidden. */
export interface MyFacePhoto { id: string; filename: string; url: string }
export interface MyFace { photos: MyFacePhoto[]; model_available: boolean; threshold: number }

export interface FaceVideo {
  render_id: string;
  duration_seconds: number;
  file_size_bytes: number;
  frames: number;
  frames_hidden: number;
  faces_hidden: number;
  frames_with_me: number;
  photo_count: number;
  matches_render: boolean;
  url: string;
}
export interface FaceVideoStatus {
  project_id: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  done: number;
  total: number;
  error_code: string | null;
  latest_render_id: string | null;
  photo_count: number;
  model_available: boolean;
  video: FaceVideo | null;
}

function unsupported(error: unknown): never {
  if (error instanceof ApiError && (error.status === 404 || error.status === 405 || error.status === 422) && !error.code) {
    throw new ApiError("실행 중인 서버가 얼굴 가리기를 아직 지원하지 않습니다. 서버를 다시 시작한 뒤 사용할 수 있습니다.", error.status);
  }
  throw error;
}
function checkFace(value: MyFace): MyFace {
  if (!value || !Array.isArray(value.photos)) throw new ApiError("내 얼굴 응답을 확인할 수 없습니다.");
  return value;
}
function checkVideo(value: FaceVideoStatus, id: string): FaceVideoStatus {
  if (!value || value.project_id !== id || typeof value.status !== "string") throw new ApiError("얼굴 가린 영상 응답을 확인할 수 없습니다.");
  return value;
}

export const apiSrc = (url: string) => `/api${url}`;

export async function getMyFace(): Promise<MyFace> {
  try { return checkFace(await request<MyFace>("/projects/my-face")); } catch (error) { return unsupported(error); }
}
export async function addMyFacePhoto(file: File): Promise<MyFace> {
  const form = new FormData();
  form.append("file", file);
  try { return checkFace(await request<MyFace>("/projects/my-face", { method: "POST", body: form })); } catch (error) { return unsupported(error); }
}
export async function removeMyFacePhoto(photoId: string): Promise<MyFace> {
  return checkFace(await request<MyFace>(`/projects/my-face/${encodeURIComponent(photoId)}`, { method: "DELETE" }));
}
export async function getFaceVideo(id: string): Promise<FaceVideoStatus> {
  try { return checkVideo(await request<FaceVideoStatus>(`/projects/${id}/face-video`), id); } catch (error) { return unsupported(error); }
}
export async function startFaceVideo(id: string): Promise<FaceVideoStatus> {
  try { return checkVideo(await request<FaceVideoStatus>(`/projects/${id}/face-video`, { method: "POST" }, 202), id); } catch (error) { return unsupported(error); }
}
