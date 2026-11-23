import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, LoaderCircle, Upload } from "lucide-react";
import { addEditRule, clock, getEditRules } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { getReferenceStyle, uploadReference, type ReferenceResult, type ReferenceStatus } from "@/api/reference-style";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const ERROR_LABEL: Record<string, string> = {
  REFERENCE_MISSING: "올린 영상이 없어요. 다시 올려 주세요.",
  REFERENCE_NOT_VIDEO: "영상으로 읽을 수 없는 파일이에요.",
  CUTS_FAILED: "컷을 찾지 못했어요. 다른 형식(mp4)으로 다시 올려 주세요.",
  REFERENCE_FAILED: "재다가 멈췄어요. 서버 기록을 확인해 주세요.",
};
const errorText = (error: unknown) => error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";
const percent = (value: number) => `${Math.round(value * 100)}%`;

/** TODO 33-1: upload a reels/vlog I like → its cut rhythm → [규칙으로] makes it a rule chip. */
export function ReferenceStyleCard() {
  const client = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const status = useQuery({
    queryKey: ["reference-style"], queryFn: getReferenceStyle,
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const rules = useQuery({ queryKey: ["edit-rules"], queryFn: getEditRules });
  const upload = useMutation({
    mutationFn: (file: File) => uploadReference(file, setProgress),
    onSuccess: (value: ReferenceStatus) => client.setQueryData(["reference-style"], value),
    onSettled: () => setProgress(null),
  });
  const accept = useMutation({ mutationFn: addEditRule, onSuccess: (value) => client.setQueryData(["edit-rules"], value) });
  const data = status.data;
  const running = data?.status === "RUNNING";
  const busy = running || upload.isPending;
  const saved = new Set((rules.data ?? []).map((rule) => rule.text));

  return <section aria-label="좋아하는 영상 따라 하기" className="space-y-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold text-slate-800">좋아하는 영상 따라 하기</h2>
      {data?.result && <span className="text-xs text-slate-500">{data.result.filename} · {clock(data.result.video_duration)}</span>}
    </div>
    {!data?.result && !busy && <p className="text-slate-600">좋아하는 릴스·브이로그를 올리면 컷이 바뀌는 리듬을 재서 규칙 후보로 보여 줘요. AI·유료 호출은 없어요.</p>}
    <input ref={input} type="file" accept="video/*" className="hidden" aria-label="좋아하는 영상 파일"
      onChange={(event) => { const file = event.target.files?.[0]; event.target.value = ""; if (file) upload.mutate(file); }} />
    <Button type="button" size="sm" disabled={busy} onClick={() => input.current?.click()}>
      <span className="flex items-center gap-1"><Upload size={14} />{data?.result ? "다른 영상 올리기" : "좋아하는 영상 올리기"}</span>
    </Button>
    {progress !== null && <p className="flex items-center gap-2 text-slate-600"><LoaderCircle size={14} className="animate-spin" />올리는 중 {Math.round(progress * 100)}%</p>}
    {running && <p className="flex items-center gap-2 text-slate-600"><LoaderCircle size={14} className="animate-spin" />컷 찾는 중… (8분 4K 영상이면 몇 분 걸려요)</p>}
    {data?.status === "FAILED" && <Alert>{ERROR_LABEL[data.error_code ?? ""] ?? `재지 못했어요 (${data.error_code})`}</Alert>}
    {(upload.error || accept.error || status.error) && <Alert>{errorText(upload.error ?? accept.error ?? status.error)}</Alert>}
    {data?.result && !running && <Rhythm result={data.result} saved={saved} pending={accept.isPending} onAccept={(text) => accept.mutate(text)} />}
  </section>;
}

function Number_({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg bg-white px-3 py-2"><p className="text-[11px] text-slate-500">{label}</p><p className="font-semibold tabular-nums text-slate-800">{value}</p></div>;
}

export function Rhythm({ result, saved, pending, onAccept }: { result: ReferenceResult; saved: Set<string>; pending: boolean; onAccept: (text: string) => void }) {
  const s = result.stats;
  const longest = Math.max(1, ...result.lengths);
  return <div className="space-y-3" aria-label="컷 리듬">
    <div className="grid grid-cols-2 gap-2">
      <Number_ label="컷 수" value={`${s.cut_count}개 · 1분에 ${s.cuts_per_minute}개`} />
      <Number_ label="한 컷 길이 (가운데 값)" value={`${s.median_cut.toFixed(1)}초`} />
      <Number_ label="2초 안 되는 짧은 컷" value={percent(s.short_share)} />
      <Number_ label="8초 넘는 긴 컷" value={percent(s.long_share)} />
    </div>
    {result.lengths.length > 0 && <div aria-label="컷 길이 막대" className="flex h-10 items-end gap-px overflow-hidden rounded bg-white p-1">
      {result.lengths.map((length, index) => <i key={index} title={`${length.toFixed(1)}초`} className={`min-w-px flex-1 rounded-sm ${length < 2 ? "bg-sky-300" : length > 8 ? "bg-slate-500" : "bg-sky-600"}`}
        style={{ height: `${Math.max(6, (length / longest) * 100)}%` }} />)}
    </div>}
    {result.candidates.length > 0 && <div className="space-y-1.5">
      {result.candidates.map((item) => {
        const done = saved.has(item.text);
        return <div key={item.key} className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-dashed border-sky-300 bg-sky-50 px-3 py-2">
          <div className="min-w-0"><p className="font-semibold text-slate-800">{item.text}</p><p className="text-xs text-slate-500">근거: {item.why}</p></div>
          {done ? <span className="flex items-center gap-1 text-xs text-sky-700"><Check size={14} />내 규칙에 있음</span>
            : <Button type="button" size="sm" disabled={pending} onClick={() => onAccept(item.text)}>규칙으로</Button>}
        </div>;
      })}
    </div>}
    <p className="text-[11px] text-slate-500">&lsquo;N초 넘지 않게&rsquo;는 추천을 다시 만들 때 프로그램이 지키고, &lsquo;N초 안팎&rsquo;·&lsquo;짧은 컷 섞기&rsquo;는 AI가 참고해요. 천천히 넘어가는 장면 전환은 컷으로 못 잡을 수 있어요.</p>
  </div>;
}
