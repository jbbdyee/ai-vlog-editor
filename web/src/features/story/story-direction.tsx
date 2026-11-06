import { useMutation } from "@tanstack/react-query";
import { Compass, ListOrdered, LoaderCircle } from "lucide-react";
import { ApiError } from "@/api/projects";
import { getStoryDirection, type StoryDirection } from "@/api/story-direction";
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
  nonce: number;
}

export function toPlanDraft(direction: StoryDirection): StoryPlanDraft {
  const candidateIds: string[] = [];
  const chapterById: Record<string, string> = {};
  direction.chapters.forEach((chapter, index) => chapter.scenes.forEach((scene) => {
    if (scene.candidate_id in chapterById) return;
    candidateIds.push(scene.candidate_id);
    chapterById[scene.candidate_id] = `챕터 ${index + 1}. ${chapter.title}`;
  }));
  return { candidateIds, chapterById, nonce: Date.now() };
}

export function StoryDirectionCard({ projectId, onPreview, onApply }: { projectId: string; onPreview?: (range: PreviewRange) => void; onApply?: (draft: StoryPlanDraft) => void }) {
  const direction = useMutation({ mutationFn: () => getStoryDirection(projectId) });
  const value = direction.data;
  const byAi = value?.engine.startsWith("llm:");
  return <Card id="story-direction" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader>
      <CardTitle>추천 편집 방향</CardTitle>
      <CardDescription>올린 영상 전체를 보고 어떤 순서로 어떤 이야기를 만들지 챕터로 추천합니다. 아직 저장되지는 않습니다.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      <Button onClick={() => direction.mutate()} disabled={direction.isPending}>
        <span className="flex items-center gap-2">{direction.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Compass size={16} />}{direction.isPending ? "추천 만드는 중… (최대 1분 30초)" : value ? "다시 추천받기" : "추천 편집 방향 만들기"}</span>
      </Button>
      {direction.isError && <Alert>{errorText(direction.error)}</Alert>}
      {value && <div className="space-y-4" aria-label="추천 결과">
        <div>
          <p className="text-lg font-semibold text-slate-50">{value.title}</p>
          <p className="text-sm text-slate-300">{value.summary}</p>
          <p className="mt-1 text-xs text-slate-500">{byAi ? `AI 추천 (${value.engine.replace("llm:", "")})` : "AI 없이 영상 순서대로 묶은 기본 흐름"}</p>
          {value.notes.map((note) => <p key={note} className="text-xs text-amber-200">{note}</p>)}
        </div>
        <ol className="space-y-3">
          {value.chapters.map((chapter, index) => <li key={`${index}:${chapter.title}`} className="rounded-xl border border-white/10 bg-[#0b1420] p-3">
            <p className="text-sm font-semibold text-cyan-200">챕터 {index + 1}. {chapter.title} <span className="font-normal text-slate-500">· 장면 {chapter.scenes.length}개 · 약 {Math.round(chapter.total_seconds)}초</span></p>
            <p className="mt-1 text-sm text-slate-200">{chapter.description}</p>
            <p className="mt-1 text-xs text-slate-400">이유: {chapter.reason}</p>
            <ul className="mt-2 space-y-1.5">
              {chapter.scenes.map((scene) => <li key={scene.candidate_id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 text-xs text-slate-300">
                <span className="min-w-0 break-all">{scene.source_filename} · {scene.start_seconds.toFixed(1)}–{scene.end_seconds.toFixed(1)}초</span>
                <Button size="sm" variant="secondary" onClick={() => onPreview?.({ candidateId: scene.candidate_id, sourceId: scene.source_video_id, start: scene.start_seconds, end: scene.end_seconds })}>미리보기</Button>
              </li>)}
            </ul>
          </li>)}
        </ol>
        {onApply && <div className="space-y-1 border-t border-white/10 pt-3">
          <Button onClick={() => onApply(toPlanDraft(value))}><span className="flex items-center gap-2"><ListOrdered size={16} />이 방향으로 편집 계획 만들기</span></Button>
          <p className="text-xs text-slate-500">아래 편집 계획에 챕터 순서대로 장면을 채웁니다. 저장은 편집 계획에서 직접 눌러야 합니다.</p>
        </div>}
      </div>}
    </CardContent>
  </Card>;
}
