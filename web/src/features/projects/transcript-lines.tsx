import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, LoaderCircle, Mic, Play } from "lucide-react";
import { ApiError } from "@/api/projects";
import { getAnalyzeAll } from "@/api/scenes";
import { addMyVoice, clearMyVoice, getTranscriptLines, startVoiceScan, type Speaker, type TranscriptLine, type TranscriptLines as Lines } from "@/api/transcript-lines";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";

/** TODO 24: 대사 목록 — mark one line as "이건 내 목소리", then every line shows 나 / 다른 사람. */
function errorText(error: unknown): string {
  if (error instanceof ApiError && error.code === "MY_VOICE_FAILED") return "이 줄로는 목소리를 알아듣기 어렵습니다. 너무 짧지 않은, 나만 말한 줄을 골라 주세요.";
  return error instanceof ApiError ? error.message : "요청을 완료하지 못했습니다.";
}
function clock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  return `${String(Math.floor(whole / 60)).padStart(2, "0")}:${String(whole % 60).padStart(2, "0")}`;
}
const speakerChip: Record<Speaker, [string, string]> = {
  me: ["나", "border-emerald-300/50 bg-emerald-300/10 text-emerald-200"],
  other: ["다른 사람", "border-amber-300/40 bg-amber-300/10 text-amber-200"],
  unknown: ["모름", "border-white/15 text-slate-400"],
};

export function TranscriptLines({ projectId, onPreview, pollMs = 2000 }: { projectId: string; onPreview?: (range: PreviewRange) => void; pollMs?: number }) {
  const client = useQueryClient();
  // While "전체 분석" is running, new lines keep arriving: look again every few seconds.
  const analyzing = useQuery({ queryKey: ["analyze-all", projectId], queryFn: () => getAnalyzeAll(projectId) }).data?.running ?? false;
  const data = useQuery({
    queryKey: ["transcript-lines", projectId], queryFn: () => getTranscriptLines(projectId),
    refetchInterval: (query) => (query.state.data?.voice_run.status === "RUNNING" ? pollMs : analyzing ? pollMs * 5 : false),
  });
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [onlyMe, setOnlyMe] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const set = (value: Lines) => client.setQueryData(["transcript-lines", projectId], value);
  const register = useMutation({
    mutationFn: (line: TranscriptLine & { source_video_id: string }) => addMyVoice(projectId, {
      source_video_id: line.source_video_id, start_seconds: line.start_seconds, end_seconds: line.end_seconds, text: line.text,
    }),
    onSuccess: (value) => { set(value); setMessage(null); },
    onError: (error) => setMessage(errorText(error)),
  });
  const clear = useMutation({ mutationFn: () => clearMyVoice(projectId), onSuccess: (value) => { set(value); setMessage(null); }, onError: (error) => setMessage(errorText(error)) });
  const scan = useMutation({
    mutationFn: () => startVoiceScan(projectId),
    onSuccess: () => { setMessage(null); void data.refetch(); },
    onError: (error) => { if (!(error instanceof ApiError && error.status === 409)) setMessage(errorText(error)); void data.refetch(); },
  });

  const value = data.data;
  const sources = useMemo(() => (value?.sources ?? []).filter((item) => item.lines.length > 0), [value]);
  const active = sources.find((item) => item.source_video_id === sourceId) ?? sources[0];
  const run = value?.voice_run;
  const running = run?.status === "RUNNING";
  const registered = value?.my_voice.length ?? 0;
  const stale = registered > 0 && sources.some((item) => !item.voice_current);

  // When a voice run ends, the analyze-all card may want to show it too.
  const wasRunning = useRef(false);
  useEffect(() => {
    if (wasRunning.current && !running) void client.invalidateQueries({ queryKey: ["analyze-all", projectId] });
    wasRunning.current = running;
  }, [running, client, projectId]);

  const all = sources.flatMap((item) => item.lines);
  const count = (speaker: Speaker) => all.filter((line) => line.speaker === speaker).length;
  const lines = (active?.lines ?? []).filter((line) => !onlyMe || line.speaker === "me");

  return <Card id="transcript-lines" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader><div className="mb-2 flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-300/10 text-emerald-300 sm:mb-4 sm:h-11 sm:w-11"><AudioLines size={20} /></div><CardTitle>대사 목록</CardTitle><CardDescription>받아쓴 대사를 영상마다 줄 단위로 봅니다. 내가 말한 줄 하나에 [이건 내 목소리]를 누르고 목소리 분석을 하면, 줄마다 나 / 다른 사람이 붙습니다. 목소리 비교는 내 컴퓨터에서만 돌아갑니다.</CardDescription></CardHeader>
    <CardContent className="space-y-3 sm:space-y-4">
      {data.isError && <Alert>{errorText(data.error)}</Alert>}
      {value && !value.model_available && <Alert>목소리 모델 파일(assets/models/wespeaker_resnet34.onnx)이 없어 목소리 분석을 할 수 없습니다.</Alert>}
      {value && sources.length === 0 && <p className="text-sm text-slate-400">아직 받아쓴 대사가 없습니다. 전체 분석의 ① 대사가 끝나면 여기에 보입니다.</p>}
      {sources.length > 0 && <>
        <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[.03] p-4">
          <div className="min-w-0 space-y-1">
            <p className="text-xs text-slate-500">내 목소리</p>
            <p role="status" className="font-medium text-white">{registered === 0 ? "아직 등록 안 함" : `등록한 줄 ${registered}개`}{registered > 0 && <span className="ml-2 text-sm font-normal text-slate-300">나 {count("me")}줄 · 다른 사람 {count("other")}줄 · 모름 {count("unknown")}줄</span>}</p>
            {running && <p className="text-xs text-cyan-200">목소리 분석 중… 영상 {run?.done ?? 0} / {run?.total ?? 0}</p>}
            {!running && stale && <p className="text-xs text-amber-200">아직 목소리 분석을 안 한 영상이 있습니다. [목소리 분석]을 눌러 주세요.</p>}
            {run?.status === "FAILED" && run.error && <p className="text-xs text-rose-200">{run.error}</p>}
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" onClick={() => scan.mutate()} disabled={registered === 0 || running || scan.isPending}><span className="flex items-center gap-2">{running ? <LoaderCircle size={14} className="animate-spin" /> : <Mic size={14} />}목소리 분석</span></Button>
            {registered > 0 && <Button size="sm" variant="secondary" onClick={() => clear.mutate()} disabled={running || clear.isPending}>등록 지우기</Button>}
          </div>
        </div>
        {message && <Alert>{message}</Alert>}
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex min-w-0 items-center gap-2 text-sm text-slate-300">영상
            <select aria-label="대사를 볼 영상" className="max-w-[16rem] rounded-lg border border-white/15 bg-[#0d1520] px-2 py-1 text-sm text-white" value={active?.source_video_id ?? ""} onChange={(event) => setSourceId(event.target.value)}>
              {sources.map((item) => <option key={item.source_video_id} value={item.source_video_id}>{item.original_filename} ({item.lines.length}줄)</option>)}
            </select>
          </label>
          <label className="flex items-center gap-2 text-sm text-slate-300"><input type="checkbox" checked={onlyMe} onChange={(event) => setOnlyMe(event.target.checked)} />내 말만 보기</label>
        </div>
        <ol aria-label="대사 줄" className="max-h-[28rem] space-y-1 overflow-y-auto pr-1">
          {lines.length === 0 && <li className="text-sm text-slate-400">{onlyMe ? "이 영상에는 '나'로 표시된 줄이 없습니다." : "대사가 없습니다."}</li>}
          {lines.map((line) => {
            const chip = line.speaker ? speakerChip[line.speaker] : null;
            return <li key={line.start_seconds} className="grid grid-cols-[3.2rem_1fr] items-center gap-x-2 gap-y-1 rounded-lg border border-white/8 px-2 py-1.5 sm:grid-cols-[3.2rem_1fr_auto]">
              <button type="button" className="flex items-center gap-1 text-xs tabular-nums text-cyan-300 hover:text-cyan-100" aria-label={`${clock(line.start_seconds)}부터 미리보기`}
                onClick={() => active && onPreview?.({ candidateId: `line:${active.source_video_id}:${line.start_seconds}`, sourceId: active.source_video_id, start: line.start_seconds, end: Math.max(line.end_seconds, line.start_seconds + 1) })}><Play size={11} />{clock(line.start_seconds)}</button>
              <span className="min-w-0 break-keep text-sm text-slate-100">{line.text}</span>
              <span className="col-start-2 flex flex-wrap items-center gap-1.5 sm:col-start-3">
                {line.my_voice && <span className="rounded-full border border-emerald-300/60 px-2 text-[11px] text-emerald-200">등록한 줄</span>}
                {chip && <span className={`whitespace-nowrap rounded-full border px-2 text-xs ${chip[1]}`} title={line.score === null ? "너무 짧아서 알아듣기 어려움" : `내 목소리와 닮은 정도 ${line.score.toFixed(2)} (기준 ${value?.threshold ?? ""})`}>{chip[0]}{line.score !== null && <span className="ml-1 tabular-nums opacity-70">{line.score.toFixed(2)}</span>}</span>}
                {!line.my_voice && line.speaker !== "me" && <button type="button" className="whitespace-nowrap rounded-md border border-white/15 px-1.5 text-[11px] text-slate-300 hover:border-emerald-300/60 hover:text-emerald-200 disabled:opacity-50" disabled={register.isPending || running}
                  onClick={() => active && register.mutate({ ...line, source_video_id: active.source_video_id })}>이건 내 목소리</button>}
              </span>
            </li>;
          })}
        </ol>
      </>}
    </CardContent>
  </Card>;
}
