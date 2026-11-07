import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ListChecks, LoaderCircle, Play } from "lucide-react";
import { ApiError, getProcessing, startProcessing, type Source } from "@/api/projects";
import {
  getSceneCandidates, getSceneDiagnostics, getSceneProcessing, getSceneVision, startSceneProcessing, startSceneVision,
  type SceneCandidate, type SceneDiagnostic, type SceneSourceStatus, type SceneVisionStatus,
} from "@/api/scenes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

/** Runs the three existing analysis steps (transcript → scenes → vision) one after another from the browser. */
type Phase = "idle" | "transcript" | "scenes" | "vision" | "done" | "failed";
type Tone = "ok" | "run" | "warn" | "bad" | "idle";

const GRACE_MS = 30000;
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

class StepError extends Error {}
const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));
const visionRunning = (status?: string) => status === "QUEUED" || status === "RUNNING";

function errorText(error: unknown): string {
  if (error instanceof StepError) return error.message;
  return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
}
/** A step that is already running on the server answers 409; then we simply wait for it. */
async function accept(start: () => Promise<unknown>) {
  try { await start(); }
  catch (error) { if (!(error instanceof ApiError && error.status === 409)) throw error; }
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
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const runToken = useRef<{ cancelled: boolean } | null>(null);
  useEffect(() => () => { if (runToken.current) runToken.current.cancelled = true; }, []);

  const processing = useQuery({ queryKey: ["processing", projectId], queryFn: () => getProcessing(projectId) });
  const sceneRun = useQuery({ queryKey: ["scene-processing", projectId], queryFn: () => getSceneProcessing(projectId) });
  const diagnostics = useQuery({ queryKey: ["scene-diagnostics", projectId], queryFn: () => getSceneDiagnostics(projectId) });
  const candidates = useQuery({ queryKey: ["scene-candidates", projectId], queryFn: () => getSceneCandidates(projectId) });

  const running = order.includes(phase);
  const sources = processing.data?.sources ?? [];

  async function runAll() {
    const token = { cancelled: false };
    runToken.current = token;
    const alive = () => !token.cancelled;
    // fetchQuery writes into the shared cache, so the other cards on the page update too.
    const load = <T,>(key: string, fn: () => Promise<T>) => client.fetchQuery({ queryKey: [key, projectId], queryFn: fn, staleTime: 0 });
    const loadProcessing = () => load("processing", () => getProcessing(projectId));
    const loadScenes = () => load("scene-processing", () => getSceneProcessing(projectId));
    const loadDiagnostics = () => load("scene-diagnostics", () => getSceneDiagnostics(projectId));
    const loadCandidates = () => load("scene-candidates", () => getSceneCandidates(projectId));
    const loadVision = () => load<SceneVisionStatus>("scene-vision", () => getSceneVision(projectId));
    setError(null);
    try {
      // ① 대사: metadata, audio, transcript
      setPhase("transcript");
      let status = await loadProcessing();
      const pending = (items: Source[]) => items.some((item) => item.processing_status === "READY" || item.processing_status === "PROCESSING");
      if (status.project_status === "PROCESSING" || pending(status.sources)) {
        if (status.project_status !== "PROCESSING") await accept(() => startProcessing(projectId));
        const startedAt = Date.now();
        while (alive()) {
          await sleep(pollMs);
          if (!alive()) return;
          status = await loadProcessing();
          const working = status.project_status === "PROCESSING" || status.sources.some((item) => item.processing_status === "PROCESSING");
          const waiting = status.sources.some((item) => item.processing_status === "READY");
          if (!working && (!waiting || Date.now() - startedAt > GRACE_MS)) break;
        }
        void client.invalidateQueries({ queryKey: ["project", projectId] });
      }
      if (!alive()) return;
      const ready = status.sources.filter((item) => item.processing_status === "COMPLETED");
      if (ready.length === 0) throw new StepError("대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다.");

      // ② 장면
      setPhase("scenes");
      let run = await loadScenes();
      const analyzed = new Set((await loadDiagnostics()).sources.filter((item) => item.status !== "NOT_ANALYZED").map((item) => item.source_video_id));
      const sceneActive = run.run_status === "QUEUED" || run.run_status === "RUNNING";
      if (sceneActive || ready.some((item) => !analyzed.has(item.source_video_id))) {
        if (!sceneActive) await accept(() => startSceneProcessing(projectId));
        const startedAt = Date.now();
        while (alive()) {
          await sleep(pollMs);
          if (!alive()) return;
          [run] = await Promise.all([loadScenes(), loadDiagnostics()]);
          if (["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"].includes(run.run_status)) break;
          if (run.run_status === "NOT_STARTED" && Date.now() - startedAt > GRACE_MS) throw new StepError("장면 분석이 시작됐는지 확인하지 못했습니다. 다시 눌러 주세요.");
        }
        if (!alive()) return;
        if (run.run_status === "FAILED") throw new StepError(`장면 분석이 실패했습니다.${run.safe_error_code ? ` (${run.safe_error_code})` : ""}`);
      }

      // ③ 화면 설명
      setPhase("vision");
      let list = await loadCandidates();
      if (list.candidates.length > 0) {
        let vision = await loadVision();
        if (visionRunning(vision.status) || list.candidates.some((item) => !item.visual_caption)) {
          if (!visionRunning(vision.status)) await accept(() => startSceneVision(projectId));
          while (alive()) {
            await sleep(pollMs);
            if (!alive()) return;
            [vision, list] = await Promise.all([loadVision(), loadCandidates()]);
            if (!visionRunning(vision.status)) break;
          }
          if (!alive()) return;
          if (vision.status === "FAILED") throw new StepError("화면 설명이 실패했습니다. 내 컴퓨터의 Ollama가 켜져 있는지 확인해 주세요.");
        }
      }
      if (!alive()) return;
      setPhase("done");
    } catch (caught) {
      if (!alive()) return;
      setError(errorText(caught));
      setPhase("failed");
    }
  }

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
        <Button onClick={() => void runAll()} disabled={running || sources.length === 0}><span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <Play size={16} />}{running ? "전체 분석 중…" : phase === "idle" ? "전체 분석 시작" : "전체 분석 다시 시작"}</span></Button>
      </div>
      {sources.length === 0 && <p className="text-sm text-slate-400">먼저 영상을 올려 주세요.</p>}
      {running && <p className="text-xs text-slate-500">이 화면이 단계를 이어 줍니다. 페이지를 닫으면 지금 단계까지만 끝나고, 다시 누르면 남은 단계부터 이어서 합니다.</p>}
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
