import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, LoaderCircle } from "lucide-react";
import { ApiError } from "@/api/projects";
import { formatDuration } from "@/api/story-direction";
import { getReelOptions, getReelStatus, startReelDraft, type ReelOption } from "@/api/reels";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";

const errors: Record<string, string> = {
  NO_SOURCE_VIDEOS: "올린 영상이 없습니다. 먼저 영상을 올려 주세요.",
  NO_SHOTS: "영상에서 장면을 나누지 못했습니다.",
  REEL_DRAFT_FAILED: "릴스 초안을 만들다가 문제가 생겼습니다. 다시 시도해 주세요.",
  REEL_DRAFT_RUNNING: "이미 릴스 초안을 만드는 중입니다.",
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return (error.code && errors[error.code]) || error.message;
  return "릴스 초안을 만들지 못했습니다.";
}

function Choices({ label, options, value, onChange, disabled }: { label: string; options: ReelOption[]; value: string; onChange: (key: string) => void; disabled?: boolean }) {
  return <div className="space-y-1.5">
    <p className="text-xs font-semibold text-slate-400">{label}</p>
    <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
      {options.map((option) => {
        const on = option.key === value;
        return <button key={option.key} type="button" aria-pressed={on} disabled={disabled} onClick={() => onChange(option.key)}
          className={`rounded-full border px-3 py-1 text-sm transition disabled:opacity-60 ${on ? "border-cyan-300 bg-cyan-300 font-semibold text-slate-950" : "border-white/15 text-slate-200 hover:border-cyan-300/60"}`}>
          {option.label}
        </button>;
      })}
    </div>
  </div>;
}

/** TODO 10: pick short/long, mode, pace and length, then the AI drafts a reel (order, length per shot, title, lines). */
export function ReelDraftCard({ projectId, onPreview }: { projectId: string; onPreview?: (range: PreviewRange) => void }) {
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: ["reel-options"], queryFn: getReelOptions, staleTime: Infinity });
  const status = useQuery({
    queryKey: ["reel-draft", projectId], queryFn: () => getReelStatus(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const [format, setFormat] = useState("short");
  const [mode, setMode] = useState("auto");
  const [pace, setPace] = useState("normal");
  const [seconds, setSeconds] = useState(30);
  // Show the saved draft's choices once, so "다시 만들기" starts from what produced it.
  const saved = status.data?.draft;
  const [synced, setSynced] = useState(false);
  useEffect(() => {
    if (saved && !synced) { setPace(saved.pace); setSeconds(saved.target_seconds); setSynced(true); }
  }, [saved, synced]);
  const start = useMutation({
    mutationFn: () => startReelDraft(projectId, { mode, pace, target_seconds: seconds }),
    onSuccess: (value) => queryClient.setQueryData(["reel-draft", projectId], value),
  });
  const running = status.data?.status === "RUNNING" || start.isPending;
  const draft = status.data?.draft;
  const byAi = draft?.engine.startsWith("llm:");
  return <Card id="reel-draft" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader>
      <CardTitle>숏폼·롱폼 만들기</CardTitle>
      <CardDescription>무엇을 만들지 먼저 고르세요. 숏폼은 AI가 장면 순서, 장면별 길이, 첫 화면 제목, 장면 문구를 짠 초안을 보여줍니다. 영상 파일은 다음 단계에서 만듭니다.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      {options.isError && <Alert>{errorText(options.error)}</Alert>}
      {options.data && <div className="space-y-3">
        <Choices label="만들 영상" options={options.data.formats} value={format} onChange={setFormat} disabled={running} />
        {format === "long" ? <div className="rounded-xl border border-white/10 bg-white/[.03] p-3 text-sm text-slate-300">
          롱폼(유튜브)은 아래 <a href="#story-direction" className="text-cyan-300 underline">추천 편집 방향</a>에서 길이를 고르고 편집 계획을 만듭니다. 모드·속도 고르기는 다음 단계에서 롱폼에도 붙입니다.
        </div> : <>
          <Choices label="모드" options={options.data.modes} value={mode} onChange={setMode} disabled={running} />
          <Choices label="속도" options={options.data.paces} value={pace} onChange={setPace} disabled={running} />
          <Choices label="길이" options={options.data.lengths.map((value) => ({ key: String(value), label: `${value}초` }))}
            value={String(seconds)} onChange={(key) => setSeconds(Number(key))} disabled={running} />
          <Button onClick={() => start.mutate()} disabled={running}>
            <span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <Clapperboard size={16} />}{running ? "릴스 초안 만드는 중…" : draft ? "릴스 초안 다시 만들기" : "릴스 초안 만들기"}</span>
          </Button>
          {status.data?.status === "RUNNING" && <p role="status" className="text-sm text-cyan-200 tabular-nums">
            {status.data.step}{status.data.total > 0 ? ` · ${status.data.done}/${status.data.total}개` : ""}
            <span className="block text-xs text-slate-500">처음에는 장면마다 화면을 읽느라 몇 분 걸립니다. 같은 영상으로 다시 만들면 빨라요.</span>
          </p>}
          {start.isError && <Alert>{errorText(start.error)}</Alert>}
          {status.data?.status === "FAILED" && <Alert>{errors[status.data.error_code ?? ""] ?? "릴스 초안을 만들지 못했습니다."}</Alert>}
        </>}
      </div>}
      {format === "short" && draft && <div className="space-y-3" aria-label="릴스 초안">
        <div className="rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3">
          <p className="text-xs text-slate-400">첫 화면 제목</p>
          <p className="text-xl font-semibold text-slate-50">{draft.title}</p>
          <p className="mt-1 text-sm text-slate-300 tabular-nums">{draft.mode_label} · {draft.pace_label} · 합계 <b className="text-slate-50">{formatDuration(draft.total_seconds)}</b> (목표 {draft.target_seconds}초) · 장면 {draft.scenes.length}개 / 나눈 장면 {draft.shot_count}개</p>
          <p className="mt-1 text-xs text-slate-500">{byAi ? `AI 초안 (${draft.engine.replace("llm:", "")})` : "AI 없이 촬영 순서대로 만든 기본 초안"}</p>
          {draft.notes.map((note) => <p key={note} className="text-xs text-amber-200">{note}</p>)}
        </div>
        <ol className="space-y-2">
          {draft.scenes.map((scene, index) => <li key={`${scene.shot_index}:${index}`} className="flex min-w-0 flex-wrap items-start justify-between gap-2 rounded-xl border border-white/10 bg-[#0b1420] p-3">
            <div className="min-w-0 flex-1">
              <p className="text-xs text-slate-500 tabular-nums">{index + 1}. {scene.is_hook ? <span className="mr-1 rounded-full bg-amber-300/15 px-2 py-0.5 font-semibold text-amber-200">맨 앞 장면</span> : null}{scene.source_filename} · {scene.start_seconds.toFixed(1)}–{scene.end_seconds.toFixed(1)}초 ({(scene.end_seconds - scene.start_seconds).toFixed(1)}초)</p>
              {scene.label && <p className="mt-1 text-xs font-semibold text-cyan-200">{scene.label}</p>}
              <p className="mt-0.5 text-base font-semibold text-slate-50">{scene.caption || <span className="text-slate-500">(문구 없음)</span>}</p>
              {scene.shot_caption && <p className="mt-0.5 text-xs text-slate-400">AI가 본 화면: {scene.shot_caption}</p>}
            </div>
            <Button size="sm" variant="secondary" onClick={() => onPreview?.({ candidateId: `reel:${scene.shot_index}`, sourceId: scene.source_video_id, start: scene.start_seconds, end: scene.end_seconds })}>미리보기</Button>
          </li>)}
        </ol>
      </div>}
    </CardContent>
  </Card>;
}
