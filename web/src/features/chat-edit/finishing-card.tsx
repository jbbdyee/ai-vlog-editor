import { useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { getFinishing } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";

const WON_PER_USD = 1450;
const won = (usd: number) => Math.max(1, Math.round((usd * WON_PER_USD) / 10) * 10).toLocaleString();

/** TODO 41-1: Claude finishing — what would be sent and what it would cost. Nothing is called from here yet. */
export function FinishingCard({ projectId, cutCount }: { projectId: string; cutCount: number }) {
  const info = useQuery({ queryKey: ["finishing", projectId, cutCount], queryFn: () => getFinishing(projectId) });
  const data = typeof info.data?.usd_low === "number" ? info.data : undefined;
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
      <ul aria-label="함께 보내는 것" className="list-disc space-y-0.5 pl-4 text-xs text-slate-600">
        <li>컷 {data.cuts}개 · 컷마다 사진 3장(모두 {data.pictures}장) · 대사·장면 설명{data.chunks > 1 ? ` · ${data.chunks}번에 나눠 보냄` : ""}</li>
        <li>내 규칙 {data.rules.length}개{data.rules.length ? `: ${data.rules.join(" / ")}` : ""}</li>
        <li>내 편집 취향 글 {data.has_brief ? "있음" : "없음"}</li>
        <li>좋아하는 영상 숫자: {data.reference.length ? data.reference.join(" · ") : "없음(내 취향 칸에서 레퍼런스 영상을 재면 생겨요)"}</li>
        {data.cuts_with_effects > 0 && <li>내가 이미 효과를 넣은 컷 {data.cuts_with_effects}개는 그대로 둬요</li>}
      </ul>
      <p className="text-[11px] text-slate-500">입력 약 {data.input_tokens.toLocaleString()} · 출력 약 {data.output_tokens.toLocaleString()}~{data.output_tokens_high.toLocaleString()} 토큰. 손질 시작 버튼은 다음 단계에서 생겨요.</p>
    </>}
    {info.isLoading && <p className="text-xs text-slate-500">예상 금액 계산 중…</p>}
    {info.error && <Alert>{info.error instanceof ApiError ? info.error.message : "예상 금액을 계산하지 못했어요."}</Alert>}
  </section>;
}
