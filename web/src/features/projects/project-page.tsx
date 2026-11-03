import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, CloudUpload, FileVideo2, Folder, LoaderCircle, RefreshCw, RotateCcw } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { ApiError, getProcessing, getProject, isProjectId, startProcessing, uploadSource, validateVideo, type SourceStatus } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";
import { SceneAnalysis } from "@/features/scenes/scene-analysis";
import { EditRender } from "@/features/edit/edit-render";
import { SourcePreview, type PreviewRange } from "@/features/projects/source-preview";

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
}
const sourceLabels: Record<SourceStatus, string> = {
  REGISTERED: "등록됨", READY: "처리 대기", PROCESSING: "처리 중", COMPLETED: "처리 완료", FAILED: "처리 실패",
};
const terminal = new Set(["COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"]);

function Steps() {
  return <nav aria-label="영상 작업 단계" className="grid min-w-0 grid-cols-2 gap-1.5 min-[390px]:grid-cols-3 sm:grid-cols-5 sm:gap-2">
    {[["01", "프로젝트", "project-top"], ["02", "영상 등록", "upload"], ["03", "소스 처리", "processing"], ["04", "장면 분석", "scene-analysis"], ["05", "편집·렌더", "edit-render"]].map(([index, title, target]) =>
      <a key={index} href={`#${target}`} className="flex min-w-0 items-center gap-1.5 rounded-lg border border-white/10 bg-white/[.04] px-2 py-2 text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 sm:gap-3 sm:rounded-xl sm:px-4 sm:py-3">
        <span className="shrink-0 text-[11px] font-bold text-cyan-300 sm:text-xs">{index}</span><span className="min-w-0 break-keep text-xs font-medium sm:text-sm">{title}</span>
      </a>,
    )}
  </nav>;
}

export function ProjectPage() {
  const { projectId = "" } = useParams();
  const validId = isProjectId(projectId);
  const queryClient = useQueryClient();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId), enabled: validId });
  const [awaitingStart, setAwaitingStart] = useState(false);
  const [previewRange, setPreviewRange] = useState<PreviewRange | null>(null);
  useEffect(() => setPreviewRange(null), [projectId]);
  function preview(candidate: PreviewRange) {
    setPreviewRange(candidate);
    document.getElementById("source-preview")?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }
  const [startedAt, setStartedAt] = useState(0);
  const processing = useQuery({
    queryKey: ["processing", projectId], queryFn: () => getProcessing(projectId), enabled: validId && project.isSuccess,
    refetchInterval: (query) => {
      const status = query.state.data?.project_status;
      if (status === "PROCESSING") return 2000;
      if (awaitingStart && Date.now() - startedAt < 30000 && !terminal.has(status ?? "")) return 2000;
      return false;
    },
  });
  useEffect(() => {
    if (processing.data && terminal.has(processing.data.project_status)) setAwaitingStart(false);
  }, [processing.data]);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState("");
  const [uploadError, setUploadError] = useState("");
  const [uploadMessage, setUploadMessage] = useState("");
  const [uploadProgress, setUploadProgress] = useState<number | null>(null);
  const [uploading, setUploading] = useState(false);
  const [waitingForRegistration, setWaitingForRegistration] = useState(false);
  const controller = useRef<AbortController | null>(null);

  const process = useMutation({
    mutationFn: () => startProcessing(projectId),
    onSuccess: async () => {
      setStartedAt(Date.now()); setAwaitingStart(true);
      await queryClient.invalidateQueries({ queryKey: ["processing", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    },
  });

  async function onUpload() {
    if (!file) { setFileError("업로드할 영상을 선택해 주세요."); return; }
    const invalid = validateVideo(file);
    if (invalid) { setFileError(invalid); return; }
    const abort = new AbortController();
    controller.current = abort;
    setUploadError(""); setUploadMessage(""); setUploadProgress(0); setUploading(true); setWaitingForRegistration(false);
    try {
      const registered = await uploadSource(projectId, file, abort.signal, (percent) => {
        setUploadProgress(percent);
        if (percent === 100) setWaitingForRegistration(true);
      });
      setUploadMessage(`서버 등록 완료 · ${registered.original_filename} · 소스 ID ${registered.source_video_id}`);
      setFile(null);
    } catch (error) {
      setUploadError(error instanceof DOMException && error.name === "AbortError"
        ? "업로드를 취소했습니다. 서버 등록 여부는 아래 소스 목록을 다시 확인해 주세요."
        : errorText(error));
    } finally {
      controller.current = null; setUploading(false); setWaitingForRegistration(false);
      await queryClient.invalidateQueries({ queryKey: ["processing", projectId] });
      await queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    }
  }

  if (!validId) return <div className="mx-auto max-w-2xl py-24"><Alert>올바른 프로젝트 ID가 아닙니다.</Alert><Link className="mt-5 inline-block text-cyan-300" to="/">처음으로 돌아가기</Link></div>;
  if (project.isPending) return <p className="py-24 text-slate-400">프로젝트를 불러오는 중입니다…</p>;
  if (project.isError) return <div className="mx-auto max-w-2xl py-24"><Alert>{errorText(project.error)}</Alert><Button className="mt-5" variant="secondary" onClick={() => void project.refetch()}>다시 조회</Button></div>;

  const status = processing.data;
  const busy = status?.project_status === "PROCESSING" || status?.sources.some((source) => source.processing_status === "PROCESSING") || process.isPending || awaitingStart;
  return <>
    <div id="project-top" className="scroll-mt-3 py-5 sm:py-10 lg:py-14">
      <Link to="/" className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white"><ArrowLeft size={16} /> 프로젝트 진입</Link>
      <div className="mt-4 flex min-w-0 flex-wrap items-end justify-between gap-3 sm:mt-7 sm:gap-5">
        <div className="min-w-0 max-w-full"><p className="text-[11px] font-semibold uppercase tracking-[.12em] text-cyan-300 sm:text-xs sm:tracking-[.2em]">Project workspace / local</p><h1 className="mt-2 break-words text-2xl font-semibold tracking-[-.035em] text-white sm:mt-3 sm:text-5xl [overflow-wrap:anywhere]">{project.data.name}</h1><p className="mt-2 break-all font-mono text-[11px] text-slate-500 sm:mt-3 sm:text-xs">{project.data.project_id}</p></div>
        <div className="max-w-full min-w-0 break-all rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs text-slate-300 sm:rounded-full sm:px-4">서버 상태 · {status?.project_status ?? project.data.status}</div>
      </div>
    </div>
    <div className="sticky top-0 z-20 min-w-0 bg-[#080e17]/95 py-2 backdrop-blur sm:static sm:mb-10 sm:bg-transparent sm:py-0 sm:backdrop-blur-none"><Steps /></div>
    <div className="grid min-w-0 gap-3 sm:gap-6 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,.95fr)]">
      <Card id="upload" className="scroll-mt-24 sm:scroll-mt-3"><CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-cyan-300/10 text-cyan-300 sm:mb-4 sm:h-11 sm:w-11"><CloudUpload size={20} /></div><CardTitle>촬영 영상 등록</CardTitle><CardDescription>MOV·MP4 등록. 전송과 서버 처리는 별도 단계입니다.</CardDescription></CardHeader><CardContent className="space-y-3 sm:space-y-5">
        <div><Label htmlFor="video-file">영상 파일</Label><Input id="video-file" type="file" accept=".mov,.mp4,video/quicktime,video/mp4" disabled={uploading} onChange={(event) => { const next = event.target.files?.[0] ?? null; setFile(next); setFileError(next ? validateVideo(next) ?? "" : ""); setUploadMessage(""); event.target.value = ""; }} /></div>
        {file && <div className="min-w-0 rounded-xl border border-white/10 bg-white/[.03] px-3 py-2 sm:px-4 sm:py-3"><p className="flex min-w-0 items-start gap-2 break-all text-sm text-slate-200"><FileVideo2 size={16} className="mt-0.5 shrink-0 text-cyan-300" />{file.name}</p><p className="mt-1 pl-6 text-xs text-slate-500">{(file.size / 1024 / 1024).toFixed(1)} MiB · 최대 4 GiB</p></div>}
        {fileError && <Alert>{fileError}</Alert>}
        {uploadError && <Alert>{uploadError}</Alert>}
        {uploadMessage && <p role="status" className="break-all rounded-xl border border-cyan-300/20 bg-cyan-300/6 px-3 py-2 text-sm text-cyan-100 sm:px-4 sm:py-3">{uploadMessage}</p>}
        {uploading && <div role="status" className="space-y-2"><div className="flex justify-between text-xs text-slate-300"><span>{waitingForRegistration ? "전송 완료 · 서버 등록 응답 대기" : "파일 바이트 전송 중"}</span><span>{uploadProgress === null ? "측정 중" : `${uploadProgress}%`}</span></div><Progress value={uploadProgress} /></div>}
        <div className="flex flex-wrap gap-2 sm:gap-3"><Button onClick={() => void onUpload()} disabled={!file || !!fileError || uploading}>파일 등록</Button>{uploading && <Button variant="secondary" onClick={() => controller.current?.abort()}>업로드 취소</Button>}</div>
        <p className="text-xs leading-5 text-slate-500">파일 형식·크기를 브라우저에서 먼저 확인합니다. 최종 유효성은 서버가 판단합니다.</p>
      </CardContent></Card>
      <Card id="processing" className="scroll-mt-24 sm:scroll-mt-3"><CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-white/8 text-slate-300 sm:mb-4 sm:h-11 sm:w-11"><Folder size={20} /></div><CardTitle>소스 처리</CardTitle><CardDescription>메타데이터·오디오·전사를 처리합니다. 진행률은 서버가 제공하지 않습니다.</CardDescription></CardHeader><CardContent className="space-y-3 sm:space-y-5">
        {processing.isPending && <p className="text-sm text-slate-400">서버 상태를 불러오는 중입니다…</p>}
        {processing.isError && <Alert>{errorText(processing.error)}</Alert>}
        {status && <><div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[.03] px-4 py-4"><div><p className="text-xs text-slate-500">서버 처리 상태</p><p className="mt-1 text-lg font-semibold text-white">{status.project_status}</p></div><p className="text-sm text-slate-300">완료 {status.completed_count} / 등록 {status.total_sources} · 실패 {status.failed_count} · 차단 {status.blocked_count}</p></div>
          {status.project_status === "COMPLETED_WITH_WARNINGS" && <p className="text-sm text-amber-200">일부 소스가 실패하거나 차단됐습니다. 소스별 상태를 확인해 주세요.</p>}
          {status.project_status === "FAILED" && <Alert>처리가 실패했습니다. 소스별 상태를 확인하고 다시 요청할 수 있습니다.</Alert>}
          {status.total_sources === 0 && <p className="text-sm text-slate-400">등록된 소스가 없습니다. 먼저 영상을 추가해 주세요.</p>}
          <ul className="space-y-2" aria-label="등록된 소스">{status.sources.map((source) => <li key={source.source_video_id} className="flex min-w-0 flex-wrap items-center justify-between gap-2 rounded-xl border border-white/8 bg-[#0b1420] px-3 py-2 sm:gap-3 sm:px-4 sm:py-3"><span className="min-w-0 max-w-full"><span className="block break-all text-sm text-slate-100">{source.original_filename}</span><span className="block break-all font-mono text-[11px] text-slate-500">{source.source_video_id}</span></span><span className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300">{sourceLabels[source.processing_status]}</span></li>)}</ul>
        </>}
        {awaitingStart && <p role="status" className="text-sm text-cyan-200">처리 요청이 접수됐습니다. 서버 상태를 확인하는 중입니다…</p>}
        {process.error && <Alert>{errorText(process.error)}</Alert>}
        <div className="flex flex-wrap gap-3"><Button onClick={() => process.mutate()} disabled={busy || !status?.total_sources}><span className="flex items-center gap-2">{busy ? <LoaderCircle size={16} className="animate-spin" /> : status?.project_status === "FAILED" ? <RotateCcw size={16} /> : <Check size={16} />}{status?.project_status === "FAILED" ? "처리 다시 요청" : "영상 처리 시작"}</span></Button><Button variant="secondary" onClick={() => { void processing.refetch(); void project.refetch(); }}><RefreshCw size={16} />상태 다시 조회</Button></div>
        {awaitingStart && Date.now() - startedAt >= 30000 && status?.project_status !== "PROCESSING" && <p className="text-xs text-amber-200">접수 후 실행 상태를 확인하지 못했습니다. 상태를 다시 조회해 주세요.</p>}
      </CardContent></Card>
    </div>
    <SourcePreview key={`preview:${projectId}`} projectId={projectId} sources={status?.sources ?? []} range={previewRange?.sourceId && status?.sources.some((source) => source.source_video_id === previewRange.sourceId) ? previewRange : null} onClearRange={() => setPreviewRange(null)} />
    <SceneAnalysis key={`scene:${projectId}`} projectId={projectId} processing={status} onPreview={preview} />
    <EditRender key={`edit:${projectId}`} projectId={projectId} processing={status} onPreview={preview} previewCandidateId={previewRange?.candidateId ?? null} />
  </>;
}
