import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, Sparkles } from "lucide-react";
import { applyFinishing, getFinishing, runFinishing, thumbUrl, type ChatCut, type FinishingSuggestion } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const WON_PER_USD = 1450;
const won = (usd: number) => Math.max(1, Math.round((usd * WON_PER_USD) / 10) * 10).toLocaleString();
const ZOOM_NAMES = { zoom: "🔍 확대", push: "🔍 천천히 줌" } as const;

function chips(item: FinishingSuggestion): string[] {
  return [
    ...(item.zoom ? [ZOOM_NAMES[item.zoom]] : []),
    ...item.texts.map((text) => `💬 ${text.kind === "narr" ? `(${text.text})` : `'${text.text}'`} ${text.at.toFixed(1)}초`),
    ...item.sounds.map((sound) => `🔊 ${sound.name} ${sound.at.toFixed(1)}초`),
  ];
}

/** TODO 41: Claude finishing — the estimate first (41-1), then one paid call whose suggestions are listed (41-2). */
export function FinishingCard({ projectId, cuts }: { projectId: string; cuts: ChatCut[] }) {
  const client = useQueryClient();
  const key = ["finishing", projectId, cuts.length];
  const info = useQuery({ queryKey: key, queryFn: () => getFinishing(projectId) });
  const [confirming, setConfirming] = useState(false);
  const run = useMutation({ mutationFn: () => runFinishing(projectId), onSuccess: (value) => {
    client.setQueryData(key, value);
    setConfirming(false);
  } });
  // TODO 41-3: put suggestions into the edit; the chat view (cut effects + undo) is refreshed
  const apply = useMutation({ mutationFn: (ids?: string[]) => applyFinishing(projectId, ids), onSuccess: (value) => {
    client.setQueryData(["chat-edit", projectId], value);
    void client.invalidateQueries({ queryKey: ["finishing", projectId] });
  } });
  const data = typeof info.data?.usd_low === "number" ? info.data : undefined;
  const suggestions = data?.suggestions ?? [];
  const byId = new Map(cuts.map((cut) => [cut.candidate_id, cut]));
  const decorated = (cut?: ChatCut) => Boolean(cut && (cut.zoom || cut.texts?.length || cut.sounds?.length));
  const waiting = suggestions.filter((item) => byId.has(item.candidate_id) && !decorated(byId.get(item.candidate_id)));
  return <section aria-label="Claude 마무리 손질" className="space-y-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3">
    <div className="flex items-center gap-1.5">
      <Sparkles size={16} className="text-sky-600" />
      <h3 className="font-semibold text-slate-800">Claude 마무리 손질</h3>
      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">유료</span>
    </div>
    <p className="text-xs text-slate-600">고른 컷은 그대로 두고, Claude가 사진·대사를 보고 웃긴 순간에 확대·리액션 글자·괄호 내레이션·효과음을 제안해요.</p>
    {data && <>
      <p aria-label="예상 금액" className="text-sm font-semibold text-slate-800">
        예상 약 {won(data.usd_low)}~{won(data.usd_high)}원
        <span className="font-normal text-slate-500"> (${data.usd_low.toFixed(2)}~${data.usd_high.toFixed(2)} · {data.model})</span></p>
      <details className="text-xs text-slate-600">
        <summary className="cursor-pointer">함께 보내는 것</summary>
        <ul aria-label="함께 보내는 것" className="mt-1 list-disc space-y-0.5 pl-4">
          <li>컷 {data.cuts}개 · 컷마다 사진 3장(모두 {data.pictures}장) · 대사·장면 설명{data.chunks > 1 ? ` · ${data.chunks}번에 나눠 보냄` : ""}</li>
          <li>내 규칙 {data.rules.length}개{data.rules.length ? `: ${data.rules.join(" / ")}` : ""}</li>
          <li>내 편집 취향 글 {data.has_brief ? "있음" : "없음"}</li>
          <li>좋아하는 영상 숫자: {data.reference.length ? data.reference.join(" · ") : "없음(내 취향 칸에서 레퍼런스 영상을 재면 생겨요)"}</li>
          {data.cuts_with_effects > 0 && <li>내가 이미 효과를 넣은 컷 {data.cuts_with_effects}개는 그대로 둬요</li>}
        </ul>
        <p className="mt-1 text-[11px] text-slate-500">입력 약 {data.input_tokens.toLocaleString()} · 출력 약 {data.output_tokens.toLocaleString()}~{data.output_tokens_high.toLocaleString()} 토큰</p>
      </details>
      {!confirming
        ? <Button type="button" size="sm" disabled={run.isPending} onClick={() => setConfirming(true)}>{data.made_at ? "다시 손질 받기" : "손질 시작"}</Button>
        : <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-100 p-2 text-xs text-amber-700">
            <p>Claude를 부르면 약 {won(data.usd_low)}~{won(data.usd_high)}원이 들어요. 사진을 만들고 답을 받는 데 몇 분 걸려요. 지금 편집은 바뀌지 않아요.</p>
            <div className="flex gap-2">
              <Button type="button" size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
                <span className="flex items-center gap-1">{run.isPending && <LoaderCircle size={14} className="animate-spin" />}{run.isPending ? "손질 받는 중…" : "부르기"}</span></Button>
              <Button type="button" size="sm" variant="secondary" disabled={run.isPending} onClick={() => setConfirming(false)}>그만두기</Button>
            </div>
          </div>}
      {data.made_at && <div aria-label="Claude 제안" className="space-y-2">
        <p className="text-xs text-slate-600">제안 {suggestions.length}컷{typeof data.spent_usd === "number" ? ` · 든 돈 약 ${won(data.spent_usd)}원($${data.spent_usd.toFixed(3)})` : ""} · {waiting.length ? `넣을 수 있는 컷 ${waiting.length}개` : "모두 편집에 들어갔어요"}</p>
        {waiting.length > 0 && <div className="flex items-center gap-2">
          <Button type="button" size="sm" disabled={apply.isPending} onClick={() => apply.mutate(undefined)}>
            <span className="flex items-center gap-1">{apply.isPending && <LoaderCircle size={14} className="animate-spin" />}모두 넣기 ({waiting.length}컷)</span></Button>
          <span className="text-[11px] text-slate-500">무료 · 편집실 ↶ 되돌리기 한 번이면 빠져요</span>
        </div>}
        {apply.isSuccess && <p role="status" className="text-xs text-sky-700">넣었어요. 영상 만들기를 하면 완성 영상에서 보여요.</p>}
        {(data.titles ?? []).length > 0 && <div aria-label="훅 제목 후보" className="flex flex-wrap gap-1.5">
          {(data.titles ?? []).map((title) => <span key={title} className="rounded-full border border-sky-300 bg-white px-2 py-0.5 text-xs font-semibold text-sky-800">{title}</span>)}
        </div>}
        <ol className="max-h-80 space-y-1.5 overflow-y-auto">
          {suggestions.map((item) => {
            const cut = byId.get(item.candidate_id);
            return <li key={item.candidate_id} className="flex gap-2 rounded-lg bg-white p-1.5">
              {cut && <img alt="" loading="lazy" className="h-12 w-20 shrink-0 rounded object-cover"
                src={thumbUrl(projectId, cut.source_video_id, cut.start_seconds + cut.length / 2)} />}
              <div className="min-w-0 flex-1 text-xs">
                <p className="font-semibold text-slate-800">{item.number}번 컷 <span className="font-normal text-slate-500">· {item.why}</span></p>
                <p className="text-slate-700">{chips(item).join("  ")}</p>
              </div>
              {cut && (decorated(cut)
                ? <span className="shrink-0 self-center rounded-full bg-sky-100 px-2 py-0.5 text-[11px] text-sky-700">효과 있음</span>
                : <Button type="button" size="sm" variant="secondary" disabled={apply.isPending} className="shrink-0 self-center"
                    onClick={() => apply.mutate([item.candidate_id])}>넣기</Button>)}
            </li>;
          })}
        </ol>
      </div>}
    </>}
    {info.isLoading && <p className="text-xs text-slate-500">예상 금액 계산 중…</p>}
    {(info.error || run.error || apply.error) && <Alert>{(info.error ?? run.error ?? apply.error) instanceof ApiError ? ((info.error ?? run.error ?? apply.error) as ApiError).message : "요청을 처리하지 못했어요."}</Alert>}
  </section>;
}
