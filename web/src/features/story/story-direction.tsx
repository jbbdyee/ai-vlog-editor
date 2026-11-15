import { useEffect, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Compass, ListOrdered, LoaderCircle, NotebookPen } from "lucide-react";
import { ApiError } from "@/api/projects";
import type { ClipRange } from "@/api/edit-render";
import { formatDuration, getDayBrief, getStoryDirection, type StoryDirection } from "@/api/story-direction";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";

function errorText(error: unknown): string {
  return error instanceof ApiError ? error.message : "추천 편집 방향을 만들지 못했습니다.";
}

/** Scene order handed to the edit plan card: chapter by chapter, plus a chapter label per scene. Not saved. */
export interface StoryPlanDraft {
  candidateIds: string[];
  chapterById: Record<string, string>;
  /** Widened clip per scene, fitted to the chosen length (TODO 8: saved and rendered). */
  rangeById?: Record<string, ClipRange>;
  nonce: number;
}

export function toPlanDraft(direction: StoryDirection): StoryPlanDraft {
  const candidateIds: string[] = [];
  const chapterById: Record<string, string> = {};
  const rangeById: Record<string, ClipRange> = {};
  direction.chapters.forEach((chapter, index) => chapter.scenes.forEach((scene) => {
    if (scene.candidate_id in chapterById) return;
    candidateIds.push(scene.candidate_id);
    chapterById[scene.candidate_id] = `챕터 ${index + 1}. ${chapter.title}`;
    rangeById[scene.candidate_id] = { start_seconds: scene.clip_start_seconds, end_seconds: scene.clip_end_seconds };
  }));
  return { candidateIds, chapterById, rangeById, nonce: Date.now() };
}

export function StoryDirectionCard({ projectId, onPreview, onApply }: { projectId: string; onPreview?: (range: PreviewRange) => void; onApply?: (draft: StoryPlanDraft) => void }) {
  // Keep the last result on screen while a new length is being fitted.
  const [value, setValue] = useState<StoryDirection>();
  // TODO 23: the user's own "오늘 있었던 일" note, loaded once and sent (and saved) with each fresh recommendation.
  const [brief, setBrief] = useState("");
  const [briefTouched, setBriefTouched] = useState(false);
  const saved = useQuery({ queryKey: ["day-brief", projectId], queryFn: () => getDayBrief(projectId), staleTime: Infinity });
  useEffect(() => { if (!briefTouched && saved.data) setBrief(saved.data); }, [saved.data, briefTouched]);
  const direction = useMutation({
    mutationFn: (change?: { targetMinutes: number; from: StoryDirection }) => getStoryDirection(projectId, change, change ? undefined : brief),
    // A length change keeps the earlier chapters, so it keeps the note they were made with too.
    onSuccess: (next, change) => setValue(change ? { ...next, day_brief: change.from.day_brief } : next),
  });
  const usedBrief = value?.day_brief;
  const fresh = direction.isPending && !direction.variables;
  const refitting = direction.isPending && !!direction.variables;
  const byAi = value?.engine.startsWith("llm:");
  return <Card id="story-direction" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader>
      <CardTitle>추천 편집 방향</CardTitle>
      <CardDescription>올린 영상 전체를 보고 어떤 순서로 어떤 이야기를 만들지 챕터로 추천합니다. 아직 저장되지는 않습니다.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      <div className="space-y-1.5">
        <label htmlFor="day-brief" className="flex items-center gap-2 text-sm font-semibold text-slate-100"><NotebookPen size={15} />오늘 있었던 일</label>
        <textarea id="day-brief" value={brief} maxLength={1000} rows={3} disabled={direction.isPending}
          onChange={(event) => { setBriefTouched(true); setBrief(event.target.value); }}
          placeholder="예: 아침엔 교실에서 친구들과 수다, 오후엔 팀 회의에서 내 아이디어 발표, 저녁은 치킨. 제일 재밌었던 건 아침 수다."
          className="w-full rounded-xl border border-white/15 bg-[#0b1420] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:border-cyan-300 focus:outline-none disabled:opacity-60" />
        <p className="text-xs text-slate-500">몇 줄만 적어도 AI가 이 순서와 사건을 이야기의 뼈대로 삼습니다. 추천을 누르면 이 프로젝트에 저장됩니다.</p>
      </div>
      <Button onClick={() => direction.mutate(undefined)} disabled={direction.isPending}>
        <span className="flex items-center gap-2">{fresh ? <LoaderCircle size={16} className="animate-spin" /> : <Compass size={16} />}{fresh ? "추천 만드는 중… (최대 1분 30초)" : value ? "다시 추천받기" : "추천 편집 방향 만들기"}</span>
      </Button>
      {direction.isError && <Alert>{errorText(direction.error)}</Alert>}
      {value && <div className="space-y-4" aria-label="추천 결과">
        <div>
          <p className="text-lg font-semibold text-slate-50">{value.title}</p>
          <p className="text-sm text-slate-300">{value.summary}</p>
          <p className="mt-1 text-xs text-slate-500">{byAi ? `AI 추천 (${value.engine.replace("llm:", "")})` : "AI 없이 영상 순서대로 묶은 기본 흐름"}</p>
          {byAi && usedBrief && <p className="mt-1 text-xs text-cyan-200">'오늘 있었던 일'을 반영한 추천입니다.</p>}
          {value.notes.map((note) => <p key={note} className="text-xs text-amber-200">{note}</p>)}
        </div>
        <div className="space-y-2 rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3" aria-label="목표 길이">
          <p className="text-sm text-slate-200"><span className="font-semibold text-cyan-200">목표 길이</span> · 추천 {value.recommended_minutes}분 <span className="text-slate-400">({value.length_reason})</span></p>
          <div className="flex flex-wrap gap-2" role="group" aria-label="목표 길이 고르기">
            {value.length_options.map((minutes) => {
              const on = minutes === value.target_minutes;
              return <button key={minutes} type="button" aria-pressed={on} disabled={direction.isPending}
                onClick={() => { if (!on) direction.mutate({ targetMinutes: minutes, from: value }); }}
                className={`rounded-full border px-3 py-1 text-sm tabular-nums transition disabled:opacity-60 ${on ? "border-cyan-300 bg-cyan-300 font-semibold text-slate-950" : "border-white/15 text-slate-200 hover:border-cyan-300/60"}`}>
                {minutes}분{minutes === value.recommended_minutes ? " · 추천" : ""}
              </button>;
            })}
          </div>
          <p role="status" className="text-sm text-slate-300 tabular-nums">
            {refitting ? <span className="inline-flex items-center gap-2"><LoaderCircle size={14} className="animate-spin" />길이에 맞추는 중…</span>
              : <>합계 <b className="text-slate-50">{formatDuration(value.total_seconds)}</b> · 챕터 {value.chapters.length}개 · 장면 {value.chapters.reduce((sum, chapter) => sum + chapter.scenes.length, 0)}개 · 원본 {formatDuration(value.footage_seconds)}</>}
          </p>
          <p className="text-xs text-slate-500">찾은 장면(몇 초짜리 순간)을 가운데 두고 앞뒤를 넓혀 길이를 맞춥니다. 말이 끊기지 않게 문장 끝에 맞춥니다.</p>
        </div>
        <ol className="space-y-3">
          {value.chapters.map((chapter, index) => <li key={`${index}:${chapter.title}`} className="rounded-xl border border-white/10 bg-[#0b1420] p-3">
            <p className="text-sm font-semibold text-cyan-200">챕터 {index + 1}. {chapter.title} <span className="font-normal text-slate-500">· 장면 {chapter.scenes.length}개 · 약 {formatDuration(chapter.total_seconds)}</span></p>
            <p className="mt-1 text-sm text-slate-200">{chapter.description}</p>
            <p className="mt-1 text-xs text-slate-400">이유: {chapter.reason}</p>
            <ul className="mt-2 space-y-1.5">
              {chapter.scenes.map((scene) => <li key={scene.candidate_id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-slate-300">
                <span className="min-w-0 break-all tabular-nums">{scene.source_filename} · {scene.clip_start_seconds.toFixed(1)}–{scene.clip_end_seconds.toFixed(1)}초 <span className="text-slate-500">({(scene.clip_end_seconds - scene.clip_start_seconds).toFixed(1)}초, 찾은 순간 {scene.start_seconds.toFixed(1)}–{scene.end_seconds.toFixed(1)}초)</span></span>
                <Button size="sm" variant="secondary" onClick={() => onPreview?.({ candidateId: scene.candidate_id, sourceId: scene.source_video_id, start: scene.clip_start_seconds, end: scene.clip_end_seconds })}>미리보기</Button>
              </li>)}
            </ul>
          </li>)}
        </ol>
        {onApply && <div className="space-y-1 border-t border-white/10 pt-3">
          <Button onClick={() => onApply(toPlanDraft(value))}><span className="flex items-center gap-2"><ListOrdered size={16} />이 방향으로 편집 계획 만들기</span></Button>
          <p className="text-xs text-slate-500">아래 편집 계획에 챕터 순서대로, 고른 길이에 맞춰 넓힌 구간 그대로 장면을 채웁니다. 저장은 편집 계획에서 직접 눌러야 합니다.</p>
        </div>}
      </div>}
    </CardContent>
  </Card>;
}
