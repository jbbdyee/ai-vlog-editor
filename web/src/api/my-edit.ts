import { ApiError, request } from "@/api/projects";

/** TODO 29: my own edited video compared with the Cutory plan. */
export interface MyEditStats { cut_count: number; total_seconds: number; median_cut: number; mean_cut: number }

export interface MyEditCut {
  number: number;
  edit_start: number;
  edit_end: number;
  length: number;
  source_id: string;
  source_number: number;
  source_filename: string;
  source_start: number;
  source_end: number;
  score: number;
  tags: string[];
  in_cutory: boolean;
}

export interface MyEditResult {
  filename: string;
  compared_at: string;
  seconds_taken: number;
  edit_duration: number;
  found_seconds: number;
  frames: number;
  found_frames: number;
  mine: MyEditStats;
  cutory: MyEditStats;
  overlap_seconds: number;
  not_found: { edit_start: number; edit_end: number }[];
  not_found_seconds: number;
  day_seconds: number;
  sources: { number: number; filename: string; day_start: number; duration: number }[];
  mine_spans: [number, number][];
  cutory_spans: [number, number][];
  tags: Record<string, { mine: number; cutory: number }>;
  cuts: MyEditCut[];
}

export interface MyEditStatus {
  project_id: string;
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  step: string;
  done: number;
  total: number;
  error_code: string | null;
  has_video: boolean;
  result: MyEditResult | null;
}

export function getMyEdit(id: string): Promise<MyEditStatus> {
  return request<MyEditStatus>(`/projects/${id}/my-edit`);
}

export function compareMyEditAgain(id: string): Promise<MyEditStatus> {
  return request<MyEditStatus>(`/projects/${id}/my-edit/compare`, { method: "POST" }, 202);
}

/** Large files (several GB) go up with progress, so this uses XMLHttpRequest instead of fetch. */
export function uploadMyEdit(id: string, file: File, onProgress: (ratio: number) => void): Promise<MyEditStatus> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/projects/${id}/my-edit`);
    xhr.upload.onprogress = (event) => { if (event.lengthComputable) onProgress(event.loaded / event.total); };
    xhr.onerror = () => reject(new ApiError("서버에 연결할 수 없습니다."));
    xhr.onload = () => {
      let body: unknown = null;
      try { body = JSON.parse(xhr.responseText); } catch { body = null; }
      if (xhr.status === 202 && body) { resolve(body as MyEditStatus); return; }
      const detail = (body as { detail?: { code?: string; message?: string } } | null)?.detail;
      reject(new ApiError(detail?.message ?? "올리지 못했어요.", xhr.status, detail?.code));
    };
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export function myEditThumbUrl(projectId: string, seconds: number): string {
  return `/api/projects/${projectId}/my-edit/thumb?at=${seconds.toFixed(3)}`;
}
