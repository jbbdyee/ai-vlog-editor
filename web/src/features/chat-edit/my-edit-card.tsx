import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, RefreshCw, Upload } from "lucide-react";
import { compareMyEditAgain, getMyEdit, myEditThumbUrl, uploadMyEdit, type MyEditResult, type MyEditStatus } from "@/api/my-edit";
import { clock } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const TAG_LABEL: Record<string, string> = { other_voice: "다른 사람 목소리", my_voice: "내 목소리", talk: "대화", quiet: "말 없음" };
const ERROR_LABEL: Record<string, string> = {
  MY_EDIT_MISSING: "올린 편집 영상이 없어요. 다시 올려 주세요.",
  FRAMES_FAILED: "내 편집 영상을 읽지 못했어요. 다른 형식(mp4)으로 다시 올려 주세요.",
  MY_EDIT_FAILED: "비교하다가 멈췄어요. 서버 기록을 확인해 주세요.",
};
const errorText = (error: unknown) => error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
const seconds = (value: number) => value >= 60 ? clock(value) : `${value.toFixed(1)}초`;

function stepText(status: MyEditStatus): string {
  if (status.step === "sources") return `원본 훑는 중 ${status.done}/${status.total} (처음 한 번만 몇 분 걸려요)`;
  if (status.step === "edit") return "내 편집 영상 훑는 중…";
  if (status.step === "match") return "원본에서 같은 장면 찾는 중…";
  return "준비 중…";
}

/** TODO 29: upload my own edited video and see how it differs from the Cutory plan. */
export function MyEditCard({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const status = useQuery({
    queryKey: ["my-edit", projectId], queryFn: () => getMyEdit(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const running = status.data?.status === "RUNNING";
  const wasRunning = useRef(false);
  useEffect(() => {
    // a finished comparison adds rule candidates to the chat side
    if (wasRunning.current && !running) void client.invalidateQueries({ queryKey: ["chat-edit", projectId] });
    wasRunning.current = running;
  }, [running, client, projectId]);
  const set = (value: MyEditStatus) => client.setQueryData(["my-edit", projectId], value);
  const upload = useMutation({
    mutationFn: (file: File) => uploadMyEdit(projectId, file, setProgress),
    onSuccess: set, onSettled: () => setProgress(null),
  });
  const again = useMutation({ mutationFn: () => compareMyEditAgain(projectId), onSuccess: set });
  const data = status.data;
  const busy = running || upload.isPending || again.isPending;

  return <section aria-label="내 편집과 비교" className="space-y-3 rounded-xl border border-white/10 bg-white/[.03] p-3 text-sm">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold text-slate-100">내 편집과 비교</h2>
      {data?.result && <span className="text-xs text-slate-500">{data.result.filename} · {clock(data.result.edit_duration)}</span>}
    </div>
    {!data?.result && !busy && <p className="text-slate-300">내가 직접 편집한 영상을 올리면 원본 어디를 썼는지 찾아서 지금 Cutory 편집안과 비교해요. 다른 날 찍은 장면은 &lsquo;원본에 없음&rsquo;으로 따로 보여요.</p>}
    <input ref={input} type="file" accept="video/*" className="hidden" aria-label="내 편집 영상 파일"
      onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) upload.mutate(file); }} />
    <div className="flex flex-wrap gap-2">
      <Button type="button" size="sm" disabled={busy} onClick={() => input.current?.click()}><span className="flex items-center gap-1"><Upload size={14} />{data?.has_video ? "다른 편집 영상 올리기" : "내 편집 영상 올리기"}</span></Button>
      {data?.has_video && <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => again.mutate()}><span className="flex items-center gap-1"><RefreshCw size={14} />지금 편집안과 다시 비교</span></Button>}
    </div>
    {progress !== null && <p className="flex items-center gap-2 text-slate-300"><LoaderCircle size={14} className="animate-spin" />올리는 중 {Math.round(progress * 100)}%</p>}
    {running && data && <p className="flex items-center gap-2 text-slate-300"><LoaderCircle size={14} className="animate-spin" />{stepText(data)}</p>}
    {data?.status === "FAILED" && <Alert>{ERROR_LABEL[data.error_code ?? ""] ?? `비교하지 못했어요 (${data.error_code})`}</Alert>}
    {(upload.error || again.error || status.error) && <Alert>{errorText(upload.error ?? again.error ?? status.error)}</Alert>}
    {data?.result && <TasteCard projectId={projectId} result={data.result} />}
  </section>;
}

function Pair({ label, mine, cutory }: { label: string; mine: string; cutory: string }) {
  return <div className="rounded-lg bg-white/[.05] px-3 py-2">
    <p className="text-[11px] text-slate-400">{label}</p>
    <p className="tabular-nums"><span className="font-semibold text-orange-200">나 {mine}</span><span className="text-slate-500"> · </span><span className="font-semibold text-cyan-200">Cutory {cutory}</span></p>
  </div>;
}

function DayBar({ spans, total, color, label }: { spans: [number, number][]; total: number; color: string; label: string }) {
  return <div className="grid grid-cols-[56px_1fr] items-center gap-2 text-[11px] text-slate-400">
    <span>{label}</span>
    <div className="relative h-4 overflow-hidden rounded bg-white/[.06]" aria-label={`${label} 편집이 쓴 곳`}>
      {spans.map(([start, end]) => <i key={`${start}-${end}`} className={`absolute bottom-0 top-0 ${color}`}
        style={{ left: `${(start / total) * 100}%`, width: `max(2px, ${((end - start) / total) * 100}%)` }} />)}
    </div>
  </div>;
}

export function TasteCard({ projectId, result }: { projectId: string; result: MyEditResult }) {
  const day = Math.max(result.day_seconds, 1);
  const found = result.edit_duration > 0 ? Math.round((result.found_seconds / result.edit_duration) * 100) : 0;
  const tags = Object.entries(result.tags).sort((a, b) => (b[1].mine + b[1].cutory) - (a[1].mine + a[1].cutory));
  const mineTotal = Math.max(1, tags.reduce((sum, [, value]) => sum + value.mine, 0));
  const cutoryTotal = Math.max(1, tags.reduce((sum, [, value]) => sum + value.cutory, 0));
  const middle = result.sources[Math.floor(result.sources.length / 2)];
  const last = result.sources[result.sources.length - 1];
  return <div className="space-y-3" aria-label="취향 카드">
    <p className="text-xs text-slate-400">내 편집 {clock(result.edit_duration)} 중 {seconds(result.found_seconds)}를 원본에서 찾았어요 (약 {found}%). 원본에 없음 {result.not_found.length}곳 · {seconds(result.not_found_seconds)}.</p>
    <div className="grid grid-cols-2 gap-2">
      <Pair label="컷 수" mine={`${result.mine.cut_count}개`} cutory={`${result.cutory.cut_count}개`} />
      <Pair label="한 컷 길이 (가운데 값)" mine={`${result.mine.median_cut.toFixed(1)}초`} cutory={`${result.cutory.median_cut.toFixed(1)}초`} />
      <Pair label="원본에서 쓴 길이" mine={seconds(result.mine.total_seconds)} cutory={seconds(result.cutory.total_seconds)} />
      <div className="rounded-lg bg-white/[.05] px-3 py-2"><p className="text-[11px] text-slate-400">둘 다 쓴 원본 구간</p><p className="font-semibold tabular-nums text-violet-200">{seconds(result.overlap_seconds)}</p></div>
    </div>
    <div className="space-y-1">
      <p className="text-xs text-slate-300">하루 중 어디를 썼나 <span className="text-slate-500">(촬영 순서, 원본 {result.sources.length}개 {clock(result.day_seconds)})</span></p>
      <DayBar label="나" spans={result.mine_spans} total={day} color="bg-orange-300" />
      <DayBar label="Cutory" spans={result.cutory_spans} total={day} color="bg-cyan-300" />
      <div className="grid grid-cols-[56px_1fr] gap-2 text-[10px] text-slate-500"><span /><div className="flex justify-between"><span>원본 1번</span>{middle && <span>{middle.number}번</span>}{last && <span>{last.number}번</span>}</div></div>
    </div>
    {tags.length > 0 && <div className="space-y-1">
      <p className="text-xs text-slate-300">살린 장면 종류 <span className="text-slate-500">(쓴 시간 비율)</span></p>
      {tags.map(([tag, value]) => <div key={tag} className="grid grid-cols-[96px_1fr_1fr] items-center gap-2 text-[11px] text-slate-400">
        <span>{TAG_LABEL[tag] ?? tag}</span>
        <span className="flex items-center gap-1"><i className="h-2 rounded-sm bg-orange-300" style={{ width: `${(value.mine / mineTotal) * 100}%` }} /><span className="tabular-nums">{Math.round((value.mine / mineTotal) * 100)}%</span></span>
        <span className="flex items-center gap-1"><i className="h-2 rounded-sm bg-cyan-300" style={{ width: `${(value.cutory / cutoryTotal) * 100}%` }} /><span className="tabular-nums">{Math.round((value.cutory / cutoryTotal) * 100)}%</span></span>
      </div>)}
    </div>}
    {result.not_found.length > 0 && <details className="rounded-lg border border-dashed border-white/15 p-2">
      <summary className="cursor-pointer text-xs text-slate-300">원본에 없음 {result.not_found.length}곳 · {seconds(result.not_found_seconds)} <span className="text-slate-500">— 다른 날 찍은 장면이나 글자 화면일 수 있어요. 비교 숫자에서는 뺐어요</span></summary>
      <div className="mt-2 grid grid-cols-3 gap-1.5 sm:grid-cols-4">
        {result.not_found.map((gap) => <figure key={gap.edit_start} className="text-[10px] text-slate-400">
          <img src={myEditThumbUrl(projectId, (gap.edit_start + gap.edit_end) / 2)} alt={`내 편집 ${clock(gap.edit_start)} 장면`} loading="lazy" className="block aspect-video w-full rounded bg-black object-cover" />
          <figcaption className="tabular-nums">{clock(gap.edit_start)}–{clock(gap.edit_end)}</figcaption>
        </figure>)}
      </div>
    </details>}
    <details className="rounded-lg border border-white/10 p-2">
      <summary className="cursor-pointer text-xs text-slate-300">찾은 컷 {result.cuts.length}개 <span className="text-slate-500">· 내 편집 시각 → 원본</span></summary>
      <ol className="mt-2 max-h-60 space-y-0.5 overflow-y-auto text-[11px] tabular-nums text-slate-400">
        {result.cuts.map((cut) => <li key={cut.number}>
          <b className="text-slate-200">{clock(cut.edit_start)}</b> {cut.length.toFixed(1)}초 → 원본 {cut.source_number}번 {cut.source_start.toFixed(1)}–{cut.source_end.toFixed(1)}초
          {cut.in_cutory ? <span className="text-violet-200"> · Cutory도 씀</span> : <span className="text-orange-200"> · 나만 씀</span>}
          <span className="text-slate-500"> · {cut.tags.map((tag) => TAG_LABEL[tag] ?? tag).join(", ")}</span>
        </li>)}
      </ol>
    </details>
    <p className="text-[11px] text-slate-500">비교 결과는 &lsquo;내 선택 기록&rsquo;에 들어가, 오른쪽 위 규칙 후보로 떠요. 다시 비교하면 예전 비교 기록은 바뀌어요.</p>
  </div>;
}
