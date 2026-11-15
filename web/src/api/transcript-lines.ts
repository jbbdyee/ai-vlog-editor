import { ApiError, request } from "@/api/projects";

/** TODO 24: every transcript line, with 나/다른 사람 once the voice step scored it against my registered voice. */
export type Speaker = "me" | "other" | "unknown";
export interface TranscriptLine {
  start_seconds: number;
  end_seconds: number;
  text: string;
  speaker: Speaker | null;
  score: number | null;
  my_voice: boolean;
}
export interface TranscriptSourceLines {
  source_video_id: string;
  original_filename: string;
  lines: TranscriptLine[];
  voice_current: boolean;
}
export interface VoiceRun {
  status: "IDLE" | "RUNNING" | "COMPLETED" | "FAILED";
  done: number;
  total: number;
  error: string | null;
}
export interface TranscriptLines {
  project_id: string;
  sources: TranscriptSourceLines[];
  my_voice: { source_video_id: string; start_seconds: number; text: string }[];
  threshold: number;
  model_available: boolean;
  voice_run: VoiceRun;
}

function checked(value: TranscriptLines, id: string): TranscriptLines {
  if (!value || value.project_id !== id || !Array.isArray(value.sources)) throw new ApiError("대사 목록 응답을 확인할 수 없습니다.");
  return value;
}
export async function getTranscriptLines(id: string): Promise<TranscriptLines> {
  return checked(await request<TranscriptLines>(`/projects/${id}/transcript-lines`), id);
}
export async function addMyVoice(id: string, line: { source_video_id: string; start_seconds: number; end_seconds: number; text: string }): Promise<TranscriptLines> {
  return checked(await request<TranscriptLines>(`/projects/${id}/my-voice`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(line),
  }), id);
}
export async function clearMyVoice(id: string): Promise<TranscriptLines> {
  return checked(await request<TranscriptLines>(`/projects/${id}/my-voice`, { method: "DELETE" }), id);
}
export async function startVoiceScan(id: string): Promise<VoiceRun> {
  return request<VoiceRun>(`/projects/${id}/voice-scan`, { method: "POST" }, 202);
}
