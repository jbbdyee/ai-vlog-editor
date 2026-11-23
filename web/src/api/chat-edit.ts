import { request } from "@/api/projects";
import { saveEditPlan, type ClipRange } from "@/api/edit-render";
import { getStoryDirection, type StoryDirection } from "@/api/story-direction";

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
  /** TODO 40: effect saved for the finished video ("zoom" = 확대, "push" = 천천히 줌). */
  zoom?: "zoom" | "push" | null;
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

/** TODO 27: one "다른 장면으로" picture to put in place of a cut. */
export interface ChatChoice {
  candidate_id: string;
  source_video_id: string;
  start_seconds: number;
  end_seconds: number;
  kind: "unused" | "same";
  label: string;
}

export interface ChatMessage {
  id?: string | null;
  role: "user" | "assistant";
  text: string;
  at_seconds: number | null;
  done: string[];
  skipped: string[];
  engine: string | null;
  error: string | null;
  changed: string[];
  undo: boolean;
  undone?: boolean;
  no_change?: boolean;
  choices?: ChatChoice[];
  for_cut?: number | null;
  picked?: number | null;
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
  /** TODO 28: rule candidates found in what I chose in the chat (shared by every project). */
  rule_candidates?: RuleCandidate[];
}

export interface RuleCandidate { key: string; text: string; why: string }

/** TODO 28: [규칙으로] (accept) saves it as a rule, [아니야] hides it. */
export function answerRuleCandidate(id: string, key: string, accept: boolean): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit/rule-candidates`, { method: "POST", headers: json, body: JSON.stringify({ key, accept }) });
}

const json = { "Content-Type": "application/json" };

export function getChatEdit(id: string): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit`);
}

export function sendChatEdit(id: string, message: string, atSeconds: number | null, brain: string | null): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit`, { method: "POST", headers: json, body: JSON.stringify({ message, at_seconds: atSeconds, brain }) });
}

/** TODO 27: put the picked picture in place of the cut (-1 = keep the cut). */
export function pickChatChoice(id: string, messageId: string, choice: number): Promise<ChatEditView> {
  return request<ChatEditView>(`/projects/${id}/chat-edit/pick`, { method: "POST", headers: json, body: JSON.stringify({ message_id: messageId, choice }) });
}

/** TODO 27: a small picture of one moment of a source video. */
export function thumbUrl(projectId: string, sourceId: string, seconds: number): string {
  return `/api/projects/${projectId}/sources/${sourceId}/thumb?at=${seconds.toFixed(3)}`;
}

/** TODO 35: light 720p copies of the sources, so the edit room plays on a phone. */
export interface PreviewState { total: number; ready: string[]; making: string | null; failed: string[] }
export async function ensurePreviews(projectId: string, first: string[]): Promise<PreviewState> {
  const body = await request<Partial<PreviewState>>(`/projects/${projectId}/previews`, { method: "POST", headers: json, body: JSON.stringify({ first }) });
  return { total: Number(body.total) || 0, ready: Array.isArray(body.ready) ? body.ready : [], making: body.making ?? null, failed: Array.isArray(body.failed) ? body.failed : [] };
}
export function previewUrl(projectId: string, sourceId: string): string {
  return `/api/projects/${projectId}/sources/${sourceId}/preview`;
}

/** TODO 27: "내 편집 규칙", shared by every project. */
export interface EditRule { id: string; text: string }

export async function getEditRules(): Promise<EditRule[]> {
  return (await request<{ rules?: EditRule[] }>("/projects/edit-rules")).rules ?? [];
}

export async function addEditRule(text: string): Promise<EditRule[]> {
  return (await request<{ rules: EditRule[] }>("/projects/edit-rules", { method: "POST", headers: json, body: JSON.stringify({ text }) })).rules;
}

export async function deleteEditRule(id: string): Promise<EditRule[]> {
  return (await request<{ rules: EditRule[] }>(`/projects/edit-rules/${encodeURIComponent(id)}`, { method: "DELETE" })).rules;
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

/** TODO 32: ask for a new recommendation (in day order) and put it in place of the plan; undo brings the old one back. */
export async function remakeFromStoryDirection(id: string, minutes?: number): Promise<ChatEditView> {
  // TODO 32-3: with a length, the server leaves out the less important scenes to fit it (no length = AI's choice)
  const direction = minutes
    ? await request<StoryDirection>(`/projects/${id}/story-direction`, { method: "POST", headers: json, body: JSON.stringify({ target_minutes: minutes }) })
    : await getStoryDirection(id);
  const seen = new Set<string>();
  const clips = [];
  for (const chapter of direction.chapters) for (const scene of chapter.scenes) {
    if (seen.has(scene.candidate_id)) continue;
    seen.add(scene.candidate_id);
    clips.push({ candidate_id: scene.candidate_id, start_seconds: scene.clip_start_seconds, end_seconds: scene.clip_end_seconds });
  }
  return request<ChatEditView>(`/projects/${id}/chat-edit/remake`, { method: "POST", headers: json, body: JSON.stringify({ clips }) });
}

/** TODO 32-4: my editing taste in my own words (shared by every project). */
export async function getTasteBrief(): Promise<string> {
  return (await request<{ text: string }>("/projects/edit-taste")).text;
}

export async function saveTasteBrief(text: string): Promise<string> {
  return (await request<{ text: string }>("/projects/edit-taste", { method: "PUT", headers: json, body: JSON.stringify({ text }) })).text;
}

export interface TasteScores {
  scenes: number;
  examples: number;
  model: string;
  input_tokens: number;
  output_tokens: number;
  usd: number;
  ran: boolean;
  counts: Record<string, number>;
  made_at: string | null;
  pictures?: number;  // TODO 32-4b: scene pictures sent with the scenes
}

/** The estimate and the saved scores; no AI call. */
export function getTasteScores(id: string): Promise<TasteScores> {
  return request<TasteScores>(`/projects/${id}/taste-scores`);
}

/** A paid Claude call: scores every scene 0~3 from my taste and my edit's examples. */
export function runTasteScores(id: string): Promise<TasteScores> {
  return request<TasteScores>(`/projects/${id}/taste-scores`, { method: "POST", headers: json, body: JSON.stringify({ run: true }) });
}
