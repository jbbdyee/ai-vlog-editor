import { ApiError, request } from "@/api/projects";

/** TODO 33-1: cut rhythm of a video I like, offered as rule candidates. Shared by every project. */
export interface ReferenceStats {
  cut_count: number;
  duration: number;
  median_cut: number;
  mean_cut: number;
  p90_cut: number;
  short_share: number;
  long_share: number;
  cuts_per_minute: number;
}

export interface ReferenceCandidate { key: string; text: string; why: string }

export interface ReferenceResult {
  filename: string;
  measured_at: string;
  seconds_taken: number;
  video_duration: number;
  stats: ReferenceStats;
  lengths: number[];
  candidates: ReferenceCandidate[];
}

export interface ReferenceStatus {
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  error_code: string | null;
  result: ReferenceResult | null;
}

export function getReferenceStyle(): Promise<ReferenceStatus> {
  return request<ReferenceStatus>("/projects/reference-style");
}

/** Large files go up with progress, so this uses XMLHttpRequest instead of fetch (same as my-edit). */
export function uploadReference(file: File, onProgress: (ratio: number) => void): Promise<ReferenceStatus> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/projects/reference-style");
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded / event.total); };
    xhr.onerror = () => reject(new ApiError("서버에 연결할 수 없습니다."));
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status === 202 && body) { resolve(body as ReferenceStatus); return; }
      const detail = (body as { detail?: { code?: string; message?: string } } | null)?.detail;
      reject(new ApiError(detail?.message ?? "올리지 못했어요.", xhr.status, detail?.code));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
