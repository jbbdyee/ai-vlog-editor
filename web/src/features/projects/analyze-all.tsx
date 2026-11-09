import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, LoaderCircle, Play } from "lucide-react";
import { ApiError, getProcessing, type Source } from "@/api/projects";
import {
  getAnalyzeAll, getSceneCandidates, getSceneDiagnostics, getSceneProcessing, startAnalyzeAll,
  type AnalyzeAllPhase, type SceneCandidate, type SceneDiagnostic, type SceneSourceStatus,
} from "@/api/scenes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Shows the server-side "전체 분석" run (transcript → scenes → vision); the server hands each step to the next. */
type Phase = AnalyzeAllPhase;
type Tone = "ok" | "run" | "warn" | "bad" | "idle";

const phaseLabels: Record<Phase, string> = {
  idle: "아직 전체 분석을 시작하지 않았습니다.",
  transcript: "① 대사 받아쓰는 중",
  scenes: "② 장면 찾는 중",
  vision: "③ 화면 설명 만드는 중",
  done: "전체 분석이 끝났습니다.",
  failed: "전체 분석이 중간에 멈췄습니다.",
};
const stageLabels: Record<string, string> = { PROBE: "영상 정보 읽는", AUDIO_EXTRACTION: "소리 추출", STT: "받아쓰는", MEMO_DETECTION: "메모 찾는" };
const toneClass: Record<Tone, string> = {
  ok: "border-emerald-300/40 text-emerald-200",
  run: "border-cyan-300/50 text-cyan-200",
  warn: "border-amber-300/40 text-amber-200",
  bad: "border-rose-300/40 text-rose-200",
  idle: "border-white/10 text-slate-500",
};
const order: Phase[] = ["transcript", "scenes", "vision"];

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
}

function Chip({ tone, children }: { tone: Tone; children: string }) {
  return <span className={`inline-block whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs tabular-nums ${toneClass[tone]}`}>{children}</span>;
}

function transcriptCell(source: Source, phase: Phase): [Tone, string] {
  switch (source.processing_status) {
    case "COMPLETED": return ["ok", "완료"];
    case "FAILED": return ["bad", "실패"];
    case "PROCESSING": {
      const stage = source.stages.find((item) => item.status === "RUNNING")?.stage;
      return ["run", stage && stageLabels[stage] ? `${stageLabels[stage]} 중` : "진행 중"];
    }
    case "READY": return phase === "transcript" ? ["run", "차례 기다림"] : ["idle", "대기"];
    default: return ["idle", "등록됨"];
  }
}
function sceneCell(source: Source, phase: Phase, result?: SceneSourceStatus, diagnostic?: SceneDiagnostic): [Tone, string] {
  if (result) {
    switch (result.status) {
      case "COMPLETED": return ["ok", `장면 ${result.candidate_count}개`];
      case "ABSTAINED": return ["warn", "근거 부족"];
      case "FAILED": return ["bad", "실패"];
      case "BLOCKED": return ["bad", "차단"];
      default: return ["idle", "건너뜀"];
    }
  }
  if (source.processing_status !== "COMPLETED") return ["idle", source.processing_status === "FAILED" ? "건너뜀" : "—"];
  switch (diagnostic?.status) {
    case "COMPLETED": return ["ok", `장면 ${diagnostic.candidate_count ?? 0}개`];
    case "ABSTAINED": return ["warn", "근거 부족"];
    case "FAILED": return ["bad", "실패"];
    case "RUNNING": return ["run", "분석 중"];
  }
  return phase === "scenes" ? ["run", "차례 기다림"] : ["idle", "대기"];
}
function visionCell(candidates: SceneCandidate[], phase: Phase): [Tone, string] {
  if (candidates.length === 0) return ["idle", "—"];
  const done = candidates.filter((item) => item.visual_caption).length;
  const label = `${done} / ${candidates.length}`;
  if (done === candidates.length) return ["ok", label];
  return phase === "vision" ? ["run", `${label} 진행 중`] : ["idle", label];
}

export function AnalyzeAll({ projectId, pollMs = 2000 }: { projectId: string; pollMs?: number }) {
  const client = useQueryClient();
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // The server owns the run; this card only asks "where are we?" — also right after the page is (re)opened.
  const run = useQuery({
    queryKey: ["analyze-all", projectId], queryFn: () => getAnalyzeAll(projectId),
    refetchInterval: (query) => (query.state.data?.running ? pollMs : false),
  });
  const phase: Phase = run.data?.phase ?? "idle";
  const running = order.includes(phase);
  const live = running ? pollMs : false;
  const processing = useQuery({ queryKey: ["processing", projectId], queryFn: () => getProcessing(projectId), refetchInterval: live });
  const sceneRun = useQuery({ queryKey: ["scene-processing", projectId], queryFn: () => getSceneProcessing(projectId), refetchInterval: live });
  const diagnostics = useQuery({ queryKey: ["scene-diagnostics", projectId], queryFn: () => getSceneDiagnostics(projectId), refetchInterval: live });
  const candidates = useQuery({ queryKey: ["scene-candidates", projectId], queryFn: () => getSceneCandidates(projectId), refetchInterval: live });
  const sources = processing.data?.sources ?? [];

  // When the server finishes, refresh the other cards on the page once.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) {
      for (const key of ["project", "processing", "scene-processing", "scene-diagnostics", "scene-candidates", "scene-vision"]) void client.invalidateQueries({ queryKey: [key, projectId] });
    }
    wasRunning.current = running;
  }, [running, client, projectId]);

  async function runAll() {
    setStartError(null);
    setStarting(true);
    try {
      client.setQueryData(["analyze-all", projectId], await startAnalyzeAll(projectId));
    } catch (caught) {
      if (!(caught instanceof ApiError && caught.status === 409)) setStartError(errorText(caught));
      void client.invalidateQueries({ queryKey: ["analyze-all", projectId] });
    } finally {
      setStarting(false);
    }
  }
  const error = startError ?? (phase === "failed" ? run.data?.error ?? "전체 분석이 중간에 멈췄습니다." : null);

  const completed = sources.filter((item) => item.processing_status === "COMPLETED").length;
  const byScene = new Map((sceneRun.data?.sources ?? []).map((item) => [item.source_video_id, item]));
  const byDiagnostic = new Map((diagnostics.data?.sources ?? []).map((item) => [item.source_video_id, item]));
  const candidateList = candidates.data?.candidates ?? [];
  const stepTone = (step: Phase): Tone => {
    if (phase === step) return "run";
    if (phase === "done" || (running && order.indexOf(phase) > order.indexOf(step))) return "ok";
    return "idle";
  };

  return <Card id="analyze-all" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-300/10 text-cyan-300 sm:mb-4 sm:h-11 sm:w-11"><ListChecks size={20} /></div><CardTitle>전체 분석</CardTitle><CardDescription>버튼 한 번으로 올린 영상 전체를 ① 대사 → ② 장면 → ③ 화면 설명 순서로 분석합니다. 이미 끝난 단계는 건너뜁니다. 모두 내 컴퓨터에서 돌아갑니다.</CardDescription></CardHeader>
    <CardContent className="space-y-3 sm:space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[.03] p-4">
        <div className="min-w-0"><p className="text-xs text-slate-500">지금 단계</p><p role="status" className="mt-1 font-medium text-white">{phaseLabels[phase]}</p></div>
        <div className="flex flex-wrap gap-2">{order.map((step, index) => <Chip key={step} tone={stepTone(step)}>{["① 대사", "② 장면", "③ 화면 설명"][index]}</Chip>)}</div>
      </div>
      <p className="text-sm text-slate-300">영상 {sources.length}개 중 대사 완료 {completed}개 · 추천 장면 {candidateList.length}개 · 화면 설명 {candidateList.filter((item) => item.visual_caption).length}개</p>
      {error && <Alert>{error}</Alert>}
      {processing.isError && <Alert>{errorText(processing.error)}</Alert>}
      <div className="flex flex-wrap gap-3">
        <Button onClick={() => void runAll()} disabled={running || starting || sources.length === 0}><span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}{running ? "전체 분석 중…" : phase === "idle" ? "전체 분석 시작" : "전체 분석 다시 시작"}</span></Button>
      </div>
      {sources.length === 0 && <p className="text-sm text-slate-400">먼저 영상을 올려 주세요.</p>}
      {running && <p className="text-xs text-slate-500">서버가 단계를 이어 줍니다. 이 페이지를 닫거나 다른 탭을 봐도 계속 진행되고, 다시 열면 지금 단계가 보입니다.</p>}
      {sources.length > 0 && <div className="overflow-x-auto rounded-xl border border-white/10">
        <table className="w-full min-w-[520px] text-left text-sm" aria-label="영상별 분석 진행">
          <thead><tr className="text-xs text-slate-500"><th className="px-3 py-2 font-normal">영상</th><th className="px-3 py-2 font-normal">① 대사</th><th className="px-3 py-2 font-normal">② 장면</th><th className="px-3 py-2 font-normal">③ 화면 설명</th></tr></thead>
          <tbody>{sources.map((source) => {
            const cells = [
              transcriptCell(source, phase),
              sceneCell(source, phase, byScene.get(source.source_video_id), byDiagnostic.get(source.source_video_id)),
              visionCell(candidateList.filter((item) => item.source_video_id === source.source_video_id), phase),
            ];
            return <tr key={source.source_video_id} className="border-t border-white/8">
              <td className="max-w-[16rem] break-all px-3 py-2 text-slate-100">{source.original_filename}</td>
              {cells.map(([tone, label], index) => <td key={index} className="px-3 py-2"><Chip tone={tone}>{label}</Chip></td>)}
            </tr>;
          })}</tbody>
        </table>
      </div>}
    </CardContent>
  </Card>;
}
