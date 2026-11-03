import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Download, RefreshCw, Sparkles } from "lucide-react";
import { ApiError, type ProcessingStatus } from "@/api/projects";
import { downloadPath, fetchRenderFile, getEditPlan, getRenderHistory, getRendering, renderFileProblem, saveEditPlan, startRendering, subtitleIntegrityNote, suggestEdit, type DownloadKind, type EditSuggestion } from "@/api/edit-render";
import { getSceneCandidates } from "@/api/scenes";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";
import { RenderPreview } from "@/features/edit/render-preview";
import { SceneReasons } from "@/features/scenes/scene-reasons";

const moodLabels: Record<string, string> = { calm: "잔잔함", cozy: "아늑함", lively: "활기참", emotional: "감성적", fun: "재미있음" };
const errorText = (error: unknown) => error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
const renderLabels = { NOT_STARTED: "렌더 실행 기록 없음", QUEUED: "렌더 대기 중", RUNNING: "렌더 진행 중", COMPLETED: "렌더 완료", FAILED: "렌더 실패", INTERRUPTED: "서버 종료로 렌더 중단", RECONCILIATION_REQUIRED: "렌더 파일 확인 필요" };
const subtitleLabels: Record<string, string> = { AVAILABLE: "한국어 하드 자막 사용 가능", FAILED: "하드 자막 생성 실패", MISSING: "하드 자막 파일 누락", SUBTITLE_FAILED: "SRT 생성 실패", NO_SUBTITLES: "자막 없음", NOT_CONFIGURED: "자막 글꼴 환경 미설정", NOT_STARTED: "자막 생성 기록 없음", CORRUPT: "하드 자막 파일 변형 감지 · 제공 중지", UNVERIFIED: "하드 자막 무결성 기록 없음 · 제공 중지", BASE_UNAVAILABLE: "기본 영상 확인 실패로 자막 영상도 제공 중지" };

export function EditRender({ projectId, processing, onPreview, previewCandidateId }: { projectId: string; processing?: ProcessingStatus; onPreview?: (range: PreviewRange) => void; previewCandidateId?: string | null }) {
  const client = useQueryClient();
  const candidates = useQuery({ queryKey: ["scene-candidates", projectId], queryFn: () => getSceneCandidates(projectId) });
  const plan = useQuery({ queryKey: ["scene-edit-plan", projectId], queryFn: () => getEditPlan(projectId) });
  const [draft, setDraft] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [awaitingRender, setAwaitingRender] = useState(false);
  const [renderStartedAt, setRenderStartedAt] = useState(0);
  const [downloadError, setDownloadError] = useState("");
  const [downloading, setDownloading] = useState<DownloadKind | null>(null);
  const lastServerPlan = useRef<string | null>(null);
  const [requestSeen, setRequestSeen] = useState(false);
  const [renderUnconfirmed, setRenderUnconfirmed] = useState(false);
  const [selectedRenderId, setSelectedRenderId] = useState<string | null>(null);
  const [requestText, setRequestText] = useState("");
  const [suggestion, setSuggestion] = useState<EditSuggestion | null>(null);
  const suggest = useMutation({ mutationFn: (text: string) => suggestEdit(projectId, text), onSuccess: (value) => setSuggestion(value), onError: () => setSuggestion(null) });

  useEffect(() => { setSelectedRenderId(null); }, [projectId]);

  useEffect(() => {
    if (!plan.data) return;
    const signature = JSON.stringify(plan.data.candidate_ids);
    if (lastServerPlan.current !== signature) {
      if (!dirty) setDraft(plan.data.candidate_ids);
      lastServerPlan.current = signature;
    }
  }, [plan.data, dirty]);

  const rendering = useQuery({
    queryKey: ["rendering", projectId], queryFn: () => getRendering(projectId),
    refetchInterval: (query) => {
      if (query.state.data?.is_active) return 2000;
      if (awaitingRender && Date.now() - renderStartedAt < 30000 && !requestSeen) return 2000;
      return false;
    },
  });
  const history = useQuery({
    queryKey: ["render-history", projectId], queryFn: () => getRenderHistory(projectId),
    enabled: rendering.isSuccess,
  });
  useEffect(() => {
    if (!awaitingRender || !rendering.data || rendering.dataUpdatedAt < renderStartedAt) return;
    if (rendering.data.is_active) setRequestSeen(true);
    if (requestSeen && rendering.data.status === "NOT_STARTED") { setAwaitingRender(false); setRequestSeen(false); setRenderUnconfirmed(true); }
    if (["COMPLETED", "FAILED", "INTERRUPTED", "RECONCILIATION_REQUIRED"].includes(rendering.data.status)) {
      setAwaitingRender(false);
      setRequestSeen(false);
      void client.invalidateQueries({ queryKey: ["render-history", projectId] });
    }
  }, [awaitingRender, rendering.data, rendering.dataUpdatedAt, renderStartedAt, requestSeen, client, projectId]);
  useEffect(() => {
    if (!awaitingRender) return;
    const timeout = setTimeout(() => { if (!requestSeen) { setAwaitingRender(false); setRenderUnconfirmed(true); } }, 30000);
    return () => clearTimeout(timeout);
  }, [awaitingRender, requestSeen]);

  const save = useMutation({
    mutationFn: (ids: string[]) => saveEditPlan(projectId, ids),
    onSuccess: async (saved) => {
      client.setQueryData(["scene-edit-plan", projectId], saved);
      setDraft(saved.candidate_ids);
      setDirty(false);
      await client.invalidateQueries({ queryKey: ["scene-edit-plan", projectId] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        void client.invalidateQueries({ queryKey: ["scene-candidates", projectId] });
        void client.invalidateQueries({ queryKey: ["scene-edit-plan", projectId] });
      }
    },
  });
  const start = useMutation({
    mutationFn: () => startRendering(projectId),
    onSuccess: async () => {
      setSelectedRenderId(null);
      setRenderStartedAt(Date.now());
      setAwaitingRender(true);
      setRequestSeen(false);
      setRenderUnconfirmed(false);
      setDownloadError("");
      client.setQueryData(["rendering", projectId], undefined);
      await client.invalidateQueries({ queryKey: ["rendering", projectId] });
    },
    onError: () => { void client.invalidateQueries({ queryKey: ["rendering", projectId] }); void client.invalidateQueries({ queryKey: ["scene-edit-plan", projectId] }); },
  });

  const available = candidates.data?.candidates ?? [];
  const byId = new Map(available.map((candidate) => [candidate.candidate_id, candidate]));
  const invalid = draft.filter((id) => plan.data?.invalid_candidate_ids.includes(id) || !byId.has(id));
  const serverInvalid = plan.data?.invalid_candidate_ids ?? [];
  const canSave = plan.isSuccess && candidates.isSuccess && invalid.length === 0 && !save.isPending && dirty;
  const renderBusy = !!rendering.data?.is_active || awaitingRender || start.isPending;
  const savedIds = plan.data?.candidate_ids ?? [];
  const draftMatchesSaved = JSON.stringify(draft) === JSON.stringify(savedIds);
  const savedScenes = savedIds.map((id) => byId.get(id));
  const validSavedScenes = savedScenes.every((candidate) => candidate && Number.isFinite(candidate.start_seconds) && Number.isFinite(candidate.end_seconds) && candidate.end_seconds > candidate.start_seconds);
  const estimatedDuration = validSavedScenes ? savedScenes.reduce((sum, candidate) => sum + candidate!.end_seconds - candidate!.start_seconds, 0) : null;
  const reviewReady = plan.isSuccess && candidates.isSuccess && savedIds.length > 0 && validSavedScenes && serverInvalid.length === 0 && invalid.length === 0 && draftMatchesSaved && !dirty && !save.isPending && !save.isError;
  const canRender = reviewReady && rendering.isSuccess && !renderBusy;
  const run = rendering.data;
  const selectedRun = selectedRenderId ? history.data?.items.find((item) => item.render_id === selectedRenderId) : undefined;
  const displayRun = selectedRenderId ? selectedRun : run;
  const showResult = !awaitingRender && !start.isPending && !run?.is_active && displayRun?.status === "COMPLETED" && displayRun.succeeded;
  const plainPath = showResult ? downloadPath(displayRun, projectId, "plain") : null;
  const subtitledPath = showResult ? downloadPath(displayRun, projectId, "subtitled") : null;
  function preview(candidate: (typeof available)[number]) {
    onPreview?.({ candidateId: candidate.candidate_id, sourceId: candidate.source_video_id, start: candidate.start_seconds, end: candidate.end_seconds });
  }

  function change(next: string[]) { setDraft(next); setDirty(JSON.stringify(next) !== JSON.stringify(plan.data?.candidate_ids ?? [])); save.reset(); }
  function move(index: number, direction: -1 | 1) {
    const next = [...draft];
    [next[index], next[index + direction]] = [next[index + direction], next[index]];
    change(next);
  }
  async function download(kind: DownloadKind, path: string | null) {
    if (!path || downloading) return;
    setDownloading(kind); setDownloadError("");
    try {
      const blob = await fetchRenderFile(path);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = kind === "plain" ? "final.mp4" : "final-subtitled.mp4";
      document.body.append(anchor); anchor.click(); anchor.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) {
      setDownloadError(errorText(error));
      refreshRenderState();
    } finally { setDownloading(null); }
  }
  /** Re-read current availability after a blocked download/playback; never deletes records. */
  function refreshRenderState() {
    void rendering.refetch();
    void client.invalidateQueries({ queryKey: ["render-history", projectId] });
  }

  return <section id="edit-render" className="mt-3 grid min-w-0 scroll-mt-24 gap-3 sm:mt-6 sm:scroll-mt-3 sm:gap-6 xl:grid-cols-2" aria-label="편집 및 렌더링">
    <Card id="scene-selection" className="scroll-mt-24"><CardHeader><CardTitle>편집 계획</CardTitle><CardDescription>추천 장면을 미리 본 뒤 직접 고르거나, 원하는 편집을 말로 요청해 제안을 받으세요. 아래 목록에서 재생 순서를 정하고 저장합니다.</CardDescription></CardHeader><CardContent className="space-y-4">
      {plan.isPending && <p className="text-sm text-slate-400">저장된 계획 조회 중…</p>}
      {plan.isError && <Alert>{errorText(plan.error)}</Alert>}
      {candidates.isError && <Alert>{errorText(candidates.error)}</Alert>}
      {candidates.isSuccess && <p className="text-sm font-medium text-cyan-200" aria-live="polite">선택한 장면 {draft.length}개 / 후보 {available.length}개</p>}
      {available.length === 0 && candidates.isSuccess && <p className="text-sm text-slate-400">선택할 장면 후보가 없습니다. 장면 분석 결과를 확인해 주세요.</p>}
      {available.length > 0 && <div role="region" aria-label="자연어 편집 요청" className="min-w-0 space-y-3 rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3 sm:p-4">
        <label htmlFor="edit-request" className="flex items-center gap-2 text-sm font-semibold text-white"><Sparkles size={16} className="text-cyan-300" />원하는 편집을 말로 요청하기</label>
        <textarea id="edit-request" value={requestText} maxLength={300} rows={2} onChange={(event) => setRequestText(event.target.value)} placeholder="예: 춤추는 장면 위주로 20초 이내, 광고는 빼고" className="w-full resize-y rounded-lg border border-white/10 bg-[#0b1420] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300" />
        <div className="flex flex-wrap items-center gap-2"><Button size="sm" disabled={!requestText.trim() || suggest.isPending || save.isPending} onClick={() => suggest.mutate(requestText.trim())}>{suggest.isPending ? "제안 만드는 중…" : "장면 제안 받기"}</Button><span className="text-xs text-slate-500">AI가 장면의 대사와 화면 분석(VLM) 결과로 의미를 해석하고, 길이·개수·제외·순서와 글자 그대로 맞는 조건은 규칙으로 보장합니다. 제안은 저장되지 않습니다.</span></div>
        {suggest.error && <Alert>{errorText(suggest.error)}</Alert>}
        {suggestion && <div className="space-y-2 border-t border-white/10 pt-3" aria-label="편집 제안">
          <p className="flex flex-wrap items-center gap-2 text-xs"><span className={`rounded-full px-2 py-0.5 font-semibold ${suggestion.engine?.startsWith("llm:") ? "bg-violet-300/15 text-violet-200" : "bg-white/10 text-slate-300"}`}>{suggestion.engine?.startsWith("llm:") ? `AI 해석 · ${suggestion.engine.slice(4)}` : "규칙 기반 해석"}</span>{suggestion.mood && suggestion.mood !== "any" && <span className="text-slate-400">분위기 {moodLabels[suggestion.mood] ?? suggestion.mood}</span>}{suggestion.fallback_reason && <span className="text-amber-200">AI 해석 실패({suggestion.fallback_reason})</span>}</p>
          {suggestion.interpretation && <p className="text-xs text-slate-300">해석: {suggestion.interpretation}</p>}
          <p className="text-sm text-slate-200">제안 장면 {suggestion.scenes.length}개 · 합계 {suggestion.total_seconds.toFixed(1)}초{suggestion.target_seconds ? ` (목표 ${suggestion.target_seconds}초)` : ""}</p>
          <ol className="space-y-1.5">{suggestion.scenes.map((scene, index) => { const item = byId.get(scene.candidate_id); return <li key={scene.candidate_id} className="rounded-lg border border-white/10 bg-[#0b1420] px-3 py-2 text-xs text-slate-300"><span className="font-semibold text-cyan-200">{index + 1}.</span> {item ? `${item.start_seconds.toFixed(1)}–${item.end_seconds.toFixed(1)}초` : "현재 목록에 없는 장면"} · {scene.reasons.join(" · ")}</li>; })}</ol>
          {suggestion.notes.map((note) => <p key={note} className="text-xs text-amber-200">{note}</p>)}
          <div className="flex flex-wrap gap-2"><Button size="sm" disabled={!suggestion.candidate_ids.length || suggestion.candidate_ids.some((id) => !byId.has(id)) || save.isPending} onClick={() => { change([...suggestion.candidate_ids]); setSuggestion(null); }}>제안을 선택 목록에 적용</Button><Button size="sm" variant="secondary" onClick={() => setSuggestion(null)}>제안 닫기</Button></div>
          <p className="text-xs text-slate-500">적용 후 순서를 고치고 &lsquo;편집 계획 저장&rsquo;을 눌러야 렌더에 반영됩니다.</p>
        </div>}
      </div>}
      <ul className="space-y-2" aria-label="선택 가능한 장면">{available.map((candidate) => <li key={candidate.candidate_id} className={`flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border bg-[#0b1420] p-3 ${draft.includes(candidate.candidate_id) ? "border-cyan-300/50" : "border-white/10"}`}><div className="min-w-0 max-w-full"><p className="break-all text-sm text-slate-100">{processing?.sources.find((source) => source.source_video_id === candidate.source_video_id)?.original_filename ?? candidate.source_video_id} · {candidate.start_seconds.toFixed(2)}–{candidate.end_seconds.toFixed(2)}초 · {(candidate.end_seconds - candidate.start_seconds).toFixed(1)}초</p><SceneReasons candidate={candidate} compact /><p className="break-all font-mono text-[11px] text-slate-500">{candidate.candidate_id}</p>{draft.includes(candidate.candidate_id) && <span className="mt-1 inline-block rounded-full bg-cyan-300/10 px-2 py-0.5 text-xs font-semibold text-cyan-200">선택됨</span>}</div><div className="flex flex-wrap gap-2"><Button size="sm" variant="secondary" onClick={() => preview(candidate)}>미리보기</Button><Button size="sm" aria-pressed={draft.includes(candidate.candidate_id)} variant={draft.includes(candidate.candidate_id) ? "secondary" : "default"} disabled={!plan.isSuccess || save.isPending} onClick={() => change(draft.includes(candidate.candidate_id) ? draft.filter((id) => id !== candidate.candidate_id) : [...draft, candidate.candidate_id])}>{draft.includes(candidate.candidate_id) ? "선택 해제" : "장면 선택"}</Button></div></li>)}</ul>
      <div className="border-t border-white/10 pt-4"><p className="mb-3 text-sm font-medium text-white">선택한 장면 · 재생 순서</p><ol className="space-y-2" aria-label="선택한 장면 순서">{draft.map((id, index) => { const candidate = byId.get(id); const broken = invalid.includes(id); return <li key={id} className={`grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)] gap-2 rounded-xl border p-3 ${broken ? "border-rose-400/40 bg-rose-400/5" : previewCandidateId === id ? "border-cyan-300/40 bg-cyan-300/5" : "border-white/10 bg-white/[.03]"}`}><span className="text-sm text-cyan-200">{index + 1}</span><span className="min-w-0 break-all text-sm text-slate-200">{candidate ? `${processing?.sources.find((source) => source.source_video_id === candidate.source_video_id)?.original_filename ?? candidate.source_video_id} · ${candidate.start_seconds.toFixed(2)}–${candidate.end_seconds.toFixed(2)}초 · 길이 ${(candidate.end_seconds - candidate.start_seconds).toFixed(2)}초` : `무효 후보 · ${id}`}</span><div className="col-span-2 flex flex-wrap gap-2 sm:justify-end">{candidate && <Button size="sm" variant="secondary" onClick={() => preview(candidate)}>미리보기</Button>}<Button size="sm" variant="ghost" className="min-h-11 min-w-11" aria-label={`${index + 1}번 위로`} disabled={index === 0 || save.isPending} onClick={() => move(index, -1)}><ArrowUp size={15} /></Button><Button size="sm" variant="ghost" className="min-h-11 min-w-11" aria-label={`${index + 1}번 아래로`} disabled={index === draft.length - 1 || save.isPending} onClick={() => move(index, 1)}><ArrowDown size={15} /></Button>{candidate && <Button size="sm" variant="secondary" disabled={save.isPending} onClick={() => change(draft.filter((item) => item !== id))}>선택 해제</Button>}{broken && <Button size="sm" variant="secondary" disabled={save.isPending} onClick={() => change(draft.filter((item) => item !== id))}>무효 후보 제외</Button>}</div></li>; })}</ol>{draft.length === 0 && <p className="text-sm text-slate-500">아직 선택한 장면이 없습니다.</p>}</div>
      {invalid.length > 0 && <Alert>무효 후보 {invalid.length}개가 있습니다. 저장·렌더링 전에 이 후보를 직접 제외하고 유효한 장면을 다시 선택해 주세요. 기존 계획은 자동 변경하지 않습니다.</Alert>}
      {dirty && <p role="status" className="text-sm text-amber-200">저장되지 않은 변경사항이 있습니다.</p>}
      {save.isPending && <p role="status" className="text-sm text-cyan-200">편집 계획 저장 중…</p>}
      {!dirty && plan.isSuccess && (draft.length > 0 || save.isSuccess) && <p role="status" className="text-sm text-cyan-200">{save.isSuccess ? "편집 계획 저장 완료." : "저장된 편집 계획입니다."}</p>}
      {save.error && <Alert>{errorText(save.error)} 선택 내용은 화면에 유지됩니다.</Alert>}
      <div className="flex flex-wrap gap-3"><Button disabled={!canSave} onClick={() => save.mutate([...draft])}>{save.isPending ? "저장 중…" : "편집 계획 저장"}</Button><Button variant="secondary" onClick={() => { void plan.refetch(); void candidates.refetch(); }}>계획·후보 다시 조회</Button></div>
    </CardContent></Card>
    <Card><CardHeader><CardTitle>최종 영상 렌더링</CardTitle><CardDescription>저장된 장면 순서로 MP4를 만들고, 가능한 경우 한국어 하드 자막 MP4를 별도로 생성합니다.</CardDescription></CardHeader><CardContent className="space-y-4">
      <div role="region" className="min-w-0 rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3 sm:p-4" aria-label="렌더 전 편집 계획 검토">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 className="text-sm font-semibold text-white">렌더 전 계획 검토</h3><a href="#scene-selection" className="text-sm font-medium text-cyan-200 underline underline-offset-4">장면 선택·순서 수정</a></div>
        {reviewReady ? <>
          <p className="mt-3 text-sm text-slate-200">저장된 장면 {savedIds.length}개 · 예상 길이 {estimatedDuration!.toFixed(2)}초</p>
          <ol className="mt-3 space-y-2" aria-label="저장된 최종 장면 순서">{savedScenes.map((candidate, index) => <li key={savedIds[index]} className="grid min-w-0 grid-cols-[1.5rem_minmax(0,1fr)] gap-2 rounded-lg border border-white/10 bg-[#0b1420] p-2 text-sm sm:p-3"><span className="font-semibold text-cyan-200">{index + 1}</span><div className="min-w-0"><p className="break-all text-slate-100">{processing?.sources.find((source) => source.source_video_id === candidate!.source_video_id)?.original_filename ?? candidate!.source_video_id}</p><p className="mt-1 break-words text-xs text-slate-400">{candidate!.start_seconds.toFixed(2)}–{candidate!.end_seconds.toFixed(2)}초 · 길이 {(candidate!.end_seconds - candidate!.start_seconds).toFixed(2)}초</p></div></li>)}</ol>
        </> : <p className="mt-3 text-sm text-amber-200" role="status">{save.isPending ? "편집 계획 저장 중입니다. 완료 후 검토할 수 있습니다." : save.isError ? "편집 계획 저장에 실패했습니다. 선택한 순서를 유지한 채 다시 저장해 주세요." : dirty || !draftMatchesSaved ? "현재 순서를 저장한 뒤 렌더 전 계획을 검토해 주세요." : !plan.isSuccess || !candidates.isSuccess ? "저장된 편집 계획과 후보를 조회한 뒤 검토할 수 있습니다." : savedIds.length === 0 ? "저장된 장면이 없습니다. 장면을 선택하고 계획을 저장해 주세요." : "저장된 계획에 무효 후보나 잘못된 구간이 있습니다. 장면과 계획을 확인해 주세요."}</p>}
        <p className="mt-3 text-xs leading-5 text-slate-400">예상 길이는 저장된 장면 구간 길이의 합계입니다. 실제 렌더 결과 길이와 정확히 일치한다고 보장하지 않으며 영상 재생 미리보기는 아닙니다.</p>
        <p className="mt-1 text-xs text-slate-500">아래 렌더 기록과 결과는 이전 실행의 산출물이며 현재 계획의 예상 결과가 아닙니다.</p>
      </div>
      <div className="min-w-0 rounded-xl border border-white/10 bg-white/[.03] p-3 sm:p-4"><p className="text-xs text-slate-500">현재 서버의 렌더 실행 상태</p><p className="mt-1 break-words text-base font-semibold text-white [overflow-wrap:anywhere] sm:text-lg">{run ? renderLabels[run.status] ?? run.status : rendering.isPending ? "상태 조회 중" : "상태 조회 실패"}</p></div>
      {rendering.isError && <Alert>{errorText(rendering.error)}</Alert>}
      {run?.status === "NOT_STARTED" && <p className="text-sm text-amber-200">서버의 현재 실행 기록이 없습니다. 이전 파일이 남아 있어도 이 상태만으로 다운로드할 수 없습니다.</p>}
      {awaitingRender && <p role="status" className="text-sm text-cyan-200">렌더 요청이 접수됐습니다. 완료 여부를 확인하는 중입니다…</p>}
      {renderUnconfirmed && <Alert>접수 후 실행 상태를 확인하지 못했거나 서버가 재시작됐습니다. 상태를 다시 조회해 주세요.</Alert>}
      {run?.status === "FAILED" && <Alert>렌더링에 실패했습니다.{run.safe_error_code ? ` 오류 코드: ${run.safe_error_code}` : ""}</Alert>}
      {run?.status === "INTERRUPTED" && <Alert>이전 렌더 작업이 중단됐습니다. 자동으로 다시 실행하지 않습니다.</Alert>}
      {run?.status === "RECONCILIATION_REQUIRED" && <Alert>렌더 파일이 남아 있을 수 있지만 완료 여부를 확인할 수 없습니다. 자동으로 제공하거나 재실행하지 않습니다.</Alert>}
      {start.error && <Alert>{errorText(start.error)}</Alert>}
      {dirty && <p className="text-sm text-amber-200">렌더링 전에 변경된 편집 계획을 저장해 주세요.</p>}
      <div className="flex flex-wrap gap-3"><Button disabled={!canRender} onClick={() => start.mutate()}>{renderBusy ? "렌더링 중…" : "저장된 계획으로 렌더링"}</Button><Button variant="secondary" onClick={() => { void rendering.refetch(); void plan.refetch(); }}><RefreshCw size={16} />상태 다시 조회</Button></div>
      <p className="text-xs text-slate-500">렌더 접수와 완료는 다릅니다. 서버는 실제 진행률 퍼센트를 제공하지 않습니다.</p>
      {history.isPending && <p role="status" className="text-sm text-slate-400">렌더 기록 조회 중…</p>}
      {history.isError && <Alert>{errorText(history.error)} 이전 렌더 기록을 표시할 수 없습니다.</Alert>}
      {history.data && <div className="space-y-2 border-t border-white/10 pt-4"><p className="text-sm font-medium text-white">이 프로젝트의 렌더 기록</p>{history.data.items.length === 0 && <p className="text-sm text-slate-400">저장된 렌더 기록이 없습니다. 이전 서버에서 만든 파일은 자동 등록되지 않습니다.</p>}{history.data.items.map((item) => <div key={item.render_id} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 p-3"><span className="min-w-0 break-all text-xs text-slate-300">{renderLabels[item.status]} · {item.render_id?.slice(0, 8)}{renderFileProblem(item) ? ` · ${renderFileProblem(item)!.short}` : ""}</span><Button size="sm" variant="secondary" disabled={item.status !== "COMPLETED" || !item.download_available || !!run?.is_active} onClick={() => setSelectedRenderId(item.render_id)}>이 결과 보기</Button></div>)}{history.data.next_cursor && <p className="text-xs text-slate-500">최근 20건만 표시됩니다.</p>}</div>}
      {selectedRenderId && !selectedRun && <Alert>선택한 렌더 기록을 찾을 수 없습니다. 목록을 다시 조회해 주세요.</Alert>}
      {showResult && displayRun && <div className="space-y-4 border-t border-white/10 pt-5"><p className="text-xs text-slate-400">{selectedRenderId ? "선택한 과거 렌더 결과입니다." : "현재 서버의 마지막 완료 렌더 결과입니다."} 편집 계획을 변경했다면 이 결과는 이전 계획으로 만든 영상일 수 있습니다.</p><p className="break-all text-xs text-slate-500">렌더 ID · {displayRun.render_id}</p><p className="text-sm text-slate-300">{displayRun.output ? `${displayRun.output.duration_seconds.toFixed(2)}초 · ${displayRun.output.video_codec ?? "영상 코덱 미확인"} / ${displayRun.output.audio_codec ?? "오디오 없음"}` : "결과 메타데이터 없음"}</p><p className="text-sm text-slate-300">자막 상태 · {subtitleLabels[displayRun.hard_subtitle_status] ?? displayRun.hard_subtitle_status}{displayRun.hard_subtitle_error_code ? ` (${displayRun.hard_subtitle_error_code})` : ""}</p>{plainPath && displayRun.render_id && <RenderPreview key={`${projectId}:${displayRun.render_id}`} projectId={projectId} renderId={displayRun.render_id} plainPath={plainPath} subtitledPath={subtitledPath} onUnavailable={refreshRenderState} />}{!plainPath && <Alert>기본 MP4 결과를 미리 보거나 다운로드할 수 없습니다. 결과 파일과 서버 상태를 확인해 주세요.{renderFileProblem(displayRun) ? ` ${renderFileProblem(displayRun)!.detail}` : ""}</Alert>}{subtitleIntegrityNote(displayRun) && <p className="text-sm text-amber-200">{subtitleIntegrityNote(displayRun)}</p>}<div className="flex flex-wrap gap-3"><Button disabled={!plainPath || downloading !== null} onClick={() => void download("plain", plainPath)}><Download size={16} />자막 없는 MP4 다운로드</Button><Button variant="secondary" disabled={!subtitledPath || downloading !== null} onClick={() => void download("subtitled", subtitledPath)}><Download size={16} />한국어 하드 자막 MP4 다운로드</Button></div>{!subtitledPath && <p className="text-sm text-amber-200">자막 적용 영상은 현재 다운로드할 수 없습니다. 기본 영상이 제공되면 별도로 받을 수 있습니다.</p>}</div>}
      {downloadError && <Alert>{downloadError}</Alert>}
    </CardContent></Card>
  </section>;
}
