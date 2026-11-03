import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, Layers3, RefreshCw } from "lucide-react";
import { ApiError, type ProcessingStatus } from "@/api/projects";
import { getSceneCandidates, getSceneDiagnostics, getSceneProcessing, getSceneVision, startSceneProcessing, startSceneVision, type SceneDiagnostic, type SceneRunStatus } from "@/api/scenes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";
import { SceneReasons } from "@/features/scenes/scene-reasons";

const active = new Set<SceneRunStatus>(["QUEUED", "RUNNING"]);
const terminal = new Set<SceneRunStatus>(["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]);
const runLabels: Record<SceneRunStatus, string> = {
  NOT_STARTED: "현재 서버에서 실행 기록 없음",
  QUEUED: "분석 대기 중",
  RUNNING: "분석 중",
  COMPLETED: "분석 실행 완료",
  COMPLETED_WITH_WARNINGS: "분석 완료 · 일부 주의 필요",
  FAILED: "분석 실행 실패",
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
}
function seconds(value: number): string { return `${value.toFixed(2)}초`; }
function sourceName(id: string, processing?: ProcessingStatus): string {
  return processing?.sources.find((source) => source.source_video_id === id)?.original_filename ?? "원본 소스";
}

function DiagnosticCard({ diagnostic, processing }: { diagnostic: SceneDiagnostic; processing?: ProcessingStatus }) {
  const counts = Object.entries(diagnostic.evidence_counts);
  return <li className="min-w-0 rounded-xl border border-white/10 bg-[#0b1420] p-3 sm:p-4">
    <div className="flex min-w-0 flex-wrap items-start justify-between gap-2"><div className="min-w-0 max-w-full"><p className="break-all text-sm font-medium text-white">{sourceName(diagnostic.source_video_id, processing)}</p><p className="mt-1 break-all font-mono text-[11px] text-slate-500">{diagnostic.source_video_id}</p></div><span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">{diagnostic.status}</span></div>
    <p className="mt-3 text-sm text-slate-300">진단 기록 {diagnostic.has_record ? "있음" : "없음"} · 후보 {diagnostic.candidate_count === null ? "미확인" : `${diagnostic.candidate_count}개`}</p>
    {diagnostic.abstain_reason && <p className="mt-2 break-words text-sm text-amber-200 [overflow-wrap:anywhere]">보류 사유: {diagnostic.abstain_reason}</p>}
    {counts.length > 0 ? <div className="mt-3 flex flex-wrap gap-2">{counts.map(([name, count]) => <span key={name} className="rounded-lg bg-white/5 px-2.5 py-1 text-xs text-slate-300">{name}: {count === null ? "미확인" : count}</span>)}</div> : <p className="mt-3 text-xs text-slate-500">근거 집계 없음</p>}
    {diagnostic.warnings.length > 0 && <p className="mt-3 break-words text-xs text-amber-200 [overflow-wrap:anywhere]">주의: {diagnostic.warnings.join(" · ")}</p>}
    <details className="mt-4 border-t border-white/8 pt-3"><summary className="cursor-pointer text-xs text-cyan-200">원본 진단값 보기</summary><pre className="mt-3 max-h-72 overflow-auto whitespace-pre-wrap break-all rounded-lg bg-black/30 p-3 text-[11px] text-slate-300">{JSON.stringify(diagnostic, null, 2)}</pre></details>
  </li>;
}

export function SceneAnalysis({ projectId, processing, onPreview }: { projectId: string; processing?: ProcessingStatus; onPreview?: (range: PreviewRange) => void }) {
  const client = useQueryClient();
  const [awaitingStart, setAwaitingStart] = useState(false);
  const [startedAt, setStartedAt] = useState(0);
  const previousStatus = useRef<SceneRunStatus | undefined>(undefined);
  const status = useQuery({
    queryKey: ["scene-processing", projectId], queryFn: () => getSceneProcessing(projectId),
    refetchInterval: (query) => {
      const current = query.state.data?.run_status;
      if (current && active.has(current)) return 2000;
      if (awaitingStart && Date.now() - startedAt < 30000 && !terminal.has(current ?? "NOT_STARTED")) return 2000;
      return false;
    },
  });
  const candidates = useQuery({ queryKey: ["scene-candidates", projectId], queryFn: () => getSceneCandidates(projectId) });
  const diagnostics = useQuery({ queryKey: ["scene-diagnostics", projectId], queryFn: () => getSceneDiagnostics(projectId) });
  const start = useMutation({
    mutationFn: () => startSceneProcessing(projectId),
    onSuccess: async () => {
      setStartedAt(Date.now()); setAwaitingStart(true);
      await client.invalidateQueries({ queryKey: ["scene-processing", projectId] });
    },
  });
  const vision = useQuery({ queryKey: ["scene-vision", projectId], queryFn: () => getSceneVision(projectId), retry: false,
    refetchInterval: (query) => ["QUEUED", "RUNNING"].includes(query.state.data?.status ?? "") ? 1500 : false });
  const startVision = useMutation({ mutationFn: () => startSceneVision(projectId), onSuccess: () => void client.invalidateQueries({ queryKey: ["scene-vision", projectId] }) });
  const visionStatus = vision.data?.status;
  const visionRunning = visionStatus === "QUEUED" || visionStatus === "RUNNING";
  const previousVision = useRef<string | undefined>(undefined);
  useEffect(() => {
    if (previousVision.current && ["QUEUED", "RUNNING"].includes(previousVision.current) && !visionRunning) void client.invalidateQueries({ queryKey: ["scene-candidates", projectId] });
    previousVision.current = visionStatus;
  }, [visionStatus, visionRunning, client, projectId]);
  const runStatus = status.data?.run_status;
  useEffect(() => {
    if (runStatus && terminal.has(runStatus) && (awaitingStart || (previousStatus.current && active.has(previousStatus.current)))) {
      setAwaitingStart(false);
      void client.invalidateQueries({ queryKey: ["scene-candidates", projectId] });
      void client.invalidateQueries({ queryKey: ["scene-diagnostics", projectId] });
    }
    previousStatus.current = runStatus;
  }, [runStatus, awaitingStart, client, projectId]);

  const readyCount = processing?.sources.filter((source) => source.processing_status === "COMPLETED").length ?? 0;
  const running = !!runStatus && active.has(runStatus);
  const busy = running || awaitingStart || start.isPending;
  const canStart = readyCount > 0 && !busy && processing?.project_status !== "PROCESSING";
  const pendingStatus = awaitingStart && Date.now() - startedAt >= 30000 && !running;

  return <section id="scene-analysis" className="mt-3 scroll-mt-24 space-y-3 sm:mt-6 sm:scroll-mt-3 sm:space-y-6" aria-label="장면 분석">
    <Card><CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-300/10 text-cyan-300 sm:mb-4 sm:h-11 sm:w-11"><Activity size={21} /></div><CardTitle>장면 분석</CardTitle><CardDescription>소스 처리 완료 영상을 바탕으로 관측 근거와 장면 후보를 생성합니다. 접수와 분석 완료는 서로 다른 상태입니다.</CardDescription></CardHeader><CardContent className="space-y-3 sm:space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[.03] p-4"><div><p className="text-xs text-slate-500">서버 실행 상태</p><p className="mt-1 font-medium text-white">{status.data ? runLabels[status.data.run_status] : status.isPending ? "상태 조회 중" : "상태 조회 실패"}</p></div><p className="text-sm text-slate-300">소스 처리 완료 {readyCount} / 등록 {processing?.total_sources ?? "—"}</p></div>
      {status.data && <p className="text-sm text-slate-400">분석한 소스 {status.data.processed_count} / {status.data.total_sources} · 후보 생성 완료 {status.data.completed_count} · 근거 부족 보류 {status.data.abstained_count} · 실패 {status.data.failed_count} · 차단 {status.data.blocked_count} · 소스 처리 미완료로 건너뜀 {status.data.skipped_count}</p>}
      {status.data?.safe_error_code && <Alert>분석 오류 코드: {status.data.safe_error_code}</Alert>}
      {status.data?.sources.map((source) => <div key={source.source_video_id} className="min-w-0 break-words rounded-lg border border-white/8 bg-[#0b1420] px-3 py-2 text-xs text-slate-300 [overflow-wrap:anywhere]">{sourceName(source.source_video_id, processing)} · {source.status} · 후보 {source.candidate_count}개{source.safe_error_code ? ` · ${source.safe_error_code}` : ""}{source.warnings.length ? ` · ${source.warnings.join(" · ")}` : ""}</div>)}
      {runStatus === "NOT_STARTED" && <p className="text-xs text-slate-500">이 상태는 현재 서버 프로세스의 실행 기록입니다. 이전 실행의 후보·진단 데이터는 아래에서 별도로 조회합니다.</p>}
      {readyCount === 0 && <p className="text-sm text-slate-400">먼저 소스 처리를 완료해야 장면 분석을 시작할 수 있습니다.</p>}
      {processing && readyCount < processing.total_sources && readyCount > 0 && <p className="text-sm text-amber-200">처리되지 않은 소스는 이번 장면 분석에서 건너뛸 수 있습니다.</p>}
      {awaitingStart && <p role="status" className="text-sm text-cyan-200">분석 요청이 접수됐습니다. 서버 실행 상태를 확인하는 중입니다…</p>}
      {pendingStatus && <p className="text-sm text-amber-200">접수 후 실행 상태를 확인하지 못했습니다. 상태를 다시 조회해 주세요.</p>}
      {status.isError && <Alert>{errorText(status.error)}</Alert>}
      {start.error && <Alert>{errorText(start.error)}</Alert>}
      <div className="flex flex-wrap gap-3"><Button disabled={!canStart} onClick={() => start.mutate()}>{busy ? "장면 분석 중…" : "장면 분석 시작"}</Button><Button variant="secondary" onClick={() => { void status.refetch(); void candidates.refetch(); void diagnostics.refetch(); }}><RefreshCw size={16} />결과 다시 조회</Button></div>
      <p className="text-xs text-slate-500">분석 퍼센트와 후보 추천 순위는 서버가 제공하지 않아 표시하지 않습니다.</p>
    </CardContent></Card>
    <div className="grid min-w-0 gap-3 sm:gap-6 xl:grid-cols-2">
      <Card><CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-white/8 text-slate-300 sm:mb-4 sm:h-11 sm:w-11"><Layers3 size={21} /></div><CardTitle>AI 추천 장면</CardTitle><CardDescription>말·소리·화면 움직임 근거가 겹치는 구간을 3초 이상의 장면으로 묶어 추천합니다. 근거와 실제 대사를 확인하고 미리 본 뒤 선택하세요. 품질 점수 순위는 아닙니다.</CardDescription></CardHeader><CardContent>
        {candidates.isPending && <p className="text-sm text-slate-400">후보 조회 중…</p>}
        {candidates.isError && <Alert>{errorText(candidates.error)}</Alert>}
        {candidates.data && <p className="mb-3 text-sm font-medium text-cyan-200">추천 장면 {candidates.data.candidates.length}개</p>}
        {(candidates.data?.candidates.length ?? 0) > 0 && <div role="region" aria-label="AI 화면 분석" className="mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-violet-300/20 bg-violet-300/[.05] p-3">
          <Button size="sm" variant="secondary" disabled={visionRunning || startVision.isPending || vision.isError} onClick={() => startVision.mutate()}>{visionRunning ? "화면 분석 중…" : "AI 화면 분석 (VLM)"}</Button>
          <span className="text-xs text-slate-300">{vision.isError ? "현재 서버가 화면 분석을 지원하지 않습니다." : vision.data && vision.data.status !== "NOT_STARTED" ? `${vision.data.model} · 분석 ${vision.data.captioned + vision.data.skipped}/${vision.data.total}${vision.data.failed ? ` · 실패 ${vision.data.failed}` : ""}` : "대표 프레임 3장으로 장면마다 보이는 것을 설명합니다. 시간·선택은 바꾸지 않습니다."}</span>
          {startVision.error && <Alert>{errorText(startVision.error)}</Alert>}
        </div>}
        {candidates.data?.candidates.length === 0 && <p className="text-sm text-slate-400">{runStatus && terminal.has(runStatus) ? "이번 조회에서 장면 후보가 없습니다. 진단을 확인해 주세요." : "현재 저장된 장면 후보가 없습니다."}</p>}
        <ul className="space-y-3" aria-label="장면 후보 목록">{candidates.data?.candidates.map((candidate) => <li key={candidate.candidate_id} className="min-w-0 rounded-xl border border-white/10 bg-[#0b1420] p-3 sm:p-4"><p className="break-all text-sm font-medium text-white">{sourceName(candidate.source_video_id, processing)}</p><p className="mt-1 break-all font-mono text-[11px] text-slate-500">소스 {candidate.source_video_id}<br />후보 {candidate.candidate_id}</p><p className="mt-3 text-lg font-semibold tabular-nums text-cyan-200">{seconds(candidate.start_seconds)} – {seconds(candidate.end_seconds)}</p><p className="mt-1 text-xs text-slate-400">구간 길이 {seconds(candidate.end_seconds - candidate.start_seconds)}</p><SceneReasons candidate={candidate} /><Button className="mt-3" size="sm" variant="secondary" onClick={() => onPreview?.({ candidateId: candidate.candidate_id, sourceId: candidate.source_video_id, start: candidate.start_seconds, end: candidate.end_seconds })}>이 구간 미리보기</Button></li>)}</ul>
      </CardContent></Card>
      <Card><CardHeader><CardTitle>소스별 Evidence 진단</CardTitle><CardDescription>근거 집계와 분석 보류 사유를 확인합니다. 원본 진단값은 각 소스에서 펼쳐 볼 수 있습니다.</CardDescription></CardHeader><CardContent>
        {diagnostics.isPending && <p className="text-sm text-slate-400">진단 조회 중…</p>}
        {diagnostics.isError && <Alert>{errorText(diagnostics.error)}</Alert>}
        {diagnostics.data && <p className="mb-3 text-sm font-medium text-cyan-200">소스 진단 {diagnostics.data.sources.length}건</p>}
        {diagnostics.data?.sources.length === 0 && <p className="text-sm text-slate-400">현재 소스 진단이 없습니다.</p>}
        <ul className="space-y-3" aria-label="Evidence 진단 목록">{diagnostics.data?.sources.map((item) => <DiagnosticCard key={item.source_video_id} diagnostic={item} processing={processing} />)}</ul>
      </CardContent></Card>
    </div>
  </section>;
}
