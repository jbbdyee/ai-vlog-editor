import { request } from "@/api/projects";
import { saveEditPlan, type ClipRange } from "@/api/edit-render";
import { getStoryDirection } from "@/api/story-direction";

/** TODO 26: one cut of the saved longform plan, placed on the whole edit's timeline. */
export interface ChatCut {
  number: number;
  candidate_id: string;
  source_video_id: string;
  source_filename: string;
  start_seconds: number;
  end_seconds: number;
  timeline_start: number;
  length: number;
  speech: string;
  caption: string | null;
}

export interface ChatUnused {
  number: number;
  candidate_id: string;
  source_video_id: string;
  source_filename: string;
  start_seconds: number;
  end_seconds: number;
  speech: string;
}

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
  at_seconds: number | null;
  done: string[];
  skipped: string[];
  engine: string | null;
  error: string | null;
  changed: string[];
  undo: boolean;
}

export interface ChatEditView {
  project_id: string;
  cuts: ChatCut[];
  total_seconds: number;
  unused: ChatUnused[];
  messages: ChatMessage[];
  undo_count: number;
  brains: { key: string; label: string }[];
  default_brain: string | null;
  usage: { key: string; calls: number; input_tokens: number; output_tokens: number; usd: number }[];
  dropped: number;
  last: { done: string[]; skipped: string[]; changed: string[]; engine: string } | null;
}

const json = { "Content-Type": "application/json" };

export function getChatEdit(id: string): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit`);
}

export function sendChatEdit(id: string, message: string, atSeconds: number | null, brain: string | null): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit`, { method: "POST", headers: json, body: JSON.stringify({ message, at_seconds: atSeconds, brain }) });
}

export function undoChatEdit(id: string): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit/undo`, { method: "POST" });
}

/** No plan yet: take the recommended story direction (scenes widened to its recommended length) and save it. */
export async function startFromStoryDirection(id: string): Promise<void> {
  const direction = await getStoryDirection(id);
  const ids: string[] = [];
  const ranges: Record<string, ClipRange> = {};
  for (const chapter of direction.chapters) for (const scene of chapter.scenes) {
    if (ids.includes(scene.candidate_id)) continue;
    ids.push(scene.candidate_id);
    ranges[scene.candidate_id] = { start_seconds: scene.clip_start_seconds, end_seconds: scene.clip_end_seconds };
  }
  await saveEditPlan(id, ids, ranges);
}

/** "03:12" for a time on the whole edit. */
export function clock(seconds: number): string {
  const whole = Math.max(0, Math.round(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}

/** Which cut plays at `seconds` on the whole edit (last cut past the end). */
export function cutAt(cuts: ChatCut[], seconds: number): number {
  for (let index = 0; index < cuts.length; index += 1) {
    if (seconds < cuts[index].timeline_start + cuts[index].length) return index;
  }
  return Math.max(0, cuts.length - 1);
}
