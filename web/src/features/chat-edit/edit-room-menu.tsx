import { useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle, RefreshCw, Wrench, X } from "lucide-react";
import { Link } from "react-router-dom";
import { answerRuleCandidate, deleteEditRule, getEditRules, type ChatEditView } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { FinishingCard } from "@/features/chat-edit/finishing-card";
import { MyEditCard } from "@/features/chat-edit/my-edit-card";
import { ReferenceStyleCard } from "@/features/chat-edit/reference-style-card";
import { ScenePickCard } from "@/features/chat-edit/scene-pick-card";
import { TasteBriefCard } from "@/features/chat-edit/taste-brief-card";

const WON_PER_USD = 1450;
const errorText = (error: unknown) => error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";

type Props = {
  projectId: string;
  data: ChatEditView;
  busy: boolean;
  brain: string | null;
  onBrain: (key: string) => void;
  remakeMinutes: number;
  onRemakeMinutes: (minutes: number) => void;
  onRemake: () => void;
  remaking: boolean;
  previewStatus: string | null;
  openTaste: boolean;
  onClose: () => void;
};

/** TODO 37: everything that is not "watch and fix" lives behind ⋯ (bottom sheet on phones, right drawer on computers). */
export function EditRoomMenu({ projectId, data, busy, brain, onBrain, remakeMinutes, onRemakeMinutes, onRemake, remaking, previewStatus, openTaste, onClose }: Props) {
  const client = useQueryClient();
  const rules = useQuery({ queryKey: ["edit-rules"], queryFn: getEditRules });
  const removeRule = useMutation({ mutationFn: deleteEditRule, onSuccess: (value) => client.setQueryData(["edit-rules"], value) });
  // TODO 28: candidates found in what I chose; accepting one makes it a rule chip
  const answer = useMutation({
    mutationFn: ({ key, accept }: { key: string; accept: boolean }) => answerRuleCandidate(projectId, key, accept),
    onSuccess: (value) => { client.setQueryData(["chat-edit", projectId], value); void client.invalidateQueries({ queryKey: ["edit-rules"] }); },
    onError: () => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] }),
  });
  const candidates = data.rule_candidates ?? [];
  const claude = data.usage.find((item) => item.key === "claude");
  const local = data.usage.find((item) => item.key === "ollama");

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  useEffect(() => {
    if (openTaste) window.setTimeout(() => document.getElementById("taste-brief")?.scrollIntoView?.({ block: "center" }), 400);
  }, [openTaste]);

  return <div className="fixed inset-0 z-40">
    <button type="button" aria-label="메뉴 닫기" onClick={onClose} className="absolute inset-0 bg-slate-900/30" />
    <div role="dialog" aria-label="더 보기 메뉴"
      className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-2xl bg-white p-4 pb-[max(1rem,env(safe-area-inset-bottom))] shadow-xl lg:inset-y-0 lg:left-auto lg:right-0 lg:max-h-none lg:w-[420px] lg:rounded-none lg:rounded-l-2xl">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-base font-bold text-slate-900">더 보기</h2>
        <button type="button" aria-label="닫기" onClick={onClose} className="rounded-full p-1.5 text-slate-500 hover:bg-slate-100"><X size={18} /></button>
      </div>
      <div className="space-y-4 text-sm">
        {candidates.length > 0 && <section aria-label="규칙 후보" className="space-y-1.5">
          {candidates.map((item) => <div key={item.key} className="rounded-xl border border-dashed border-sky-300 bg-sky-50 px-3 py-2">
            <p className="text-[11px] text-sky-700">규칙 후보 · {item.key.startsWith("my_edit") || item.why.includes("내 편집본") ? "내 편집본과 비교해서 찾음" : "내 선택 기록에서 찾음"}</p>
            <p className="mt-0.5 font-semibold text-slate-800">{item.text}</p>
            <p className="mt-0.5 text-xs text-slate-500">근거: {item.why}</p>
            <div className="mt-1.5 flex gap-2">
              <Button type="button" size="sm" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: true })}>규칙으로</Button>
              <Button type="button" size="sm" variant="secondary" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: false })}>아니야</Button>
            </div>
          </div>)}
        </section>}

        <ScenePickCard projectId={projectId} />
        <FinishingCard projectId={projectId} cuts={data.cuts} />

        <section className="space-y-2">
          <h3 className="font-semibold text-slate-800">길이 바꿔 다시 만들기</h3>
          <div role="group" aria-label="다시 만들 길이" className="flex flex-wrap gap-1.5">
            {[0, 5, 8, 12, 20].map((minutes) => <button key={minutes} type="button" aria-pressed={remakeMinutes === minutes} disabled={busy} onClick={() => onRemakeMinutes(minutes)}
              className={`h-8 rounded-full px-3 text-[13px] ${remakeMinutes === minutes ? "bg-sky-100 font-bold text-sky-800" : "border border-slate-300 bg-white text-slate-600 hover:border-sky-400"}`}>{minutes ? `${minutes}분` : "AI 추천"}</button>)}
          </div>
          <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={onRemake}>{remaking ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}{remaking ? "만드는 중…" : "이 길이로 다시 만들기"}</Button>
          <p className="text-[11px] text-slate-500">지금 편집안은 ↶ 되돌리기로 다시 가져올 수 있어요.</p>
        </section>

        <section aria-label="내 규칙" className="space-y-1.5">
          <h3 className="font-semibold text-slate-800">내 규칙</h3>
          <div className="flex flex-wrap gap-1.5">
            {(rules.data ?? []).map((rule) => <span key={rule.id} className="flex items-center gap-1 rounded-full border border-sky-300 px-2 py-0.5 text-xs text-sky-700">
              {rule.text}<button type="button" aria-label={`규칙 지우기: ${rule.text}`} disabled={removeRule.isPending} onClick={() => removeRule.mutate(rule.id)}><X size={12} /></button>
            </span>)}
            {rules.data?.length === 0 && <span className="text-xs text-slate-500">아직 없어요. 대화에서 &lsquo;규칙으로 저장&rsquo;을 누르면 생겨요.</span>}
          </div>
        </section>
        {(removeRule.error || answer.error) && <Alert>{errorText(removeRule.error ?? answer.error)}</Alert>}

        {data.unused.length > 0 && <details className="rounded-xl border border-slate-200 p-3">
          <summary className="cursor-pointer text-slate-700">안 쓴 장면 {data.unused.length}개 <span className="text-xs text-slate-500">· &ldquo;안 쓴 장면 2 넣어 줘&rdquo;</span></summary>
          <ol className="mt-2 space-y-1 text-xs text-slate-500">{data.unused.map((scene) => <li key={scene.candidate_id}><b className="text-slate-700">장면 {scene.number}</b> · {scene.source_filename} · {(scene.end_seconds - scene.start_seconds).toFixed(1)}초 · {scene.speech}</li>)}</ol>
        </details>}

        <details open={openTaste} className="rounded-xl border border-slate-200 p-3">
          <summary className="cursor-pointer text-slate-700">내 취향 · 내 편집본과 비교</summary>
          <div className="mt-3 space-y-4"><TasteBriefCard projectId={projectId} /><ReferenceStyleCard /><MyEditCard projectId={projectId} /></div>
        </details>

        <section className="space-y-1.5">
          <h3 className="font-semibold text-slate-800">AI</h3>
          {data.brains.length > 0 && <label className="flex items-center gap-2 text-xs text-slate-600">어려운 말 담당
            <select aria-label="편집 두뇌" value={brain ?? ""} onChange={(event) => onBrain(event.target.value)} className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs text-slate-700">
              {data.brains.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
            </select></label>}
          <p className="text-[11px] text-slate-500">{data.brains.length === 0 ? "AI가 꺼져 있어 간단한 말만 알아들어요." : "간단한 말은 바로(무료), 나머지는 AI가 읽어요."}
            {claude && ` · Claude ${claude.calls}번 $${claude.usd.toFixed(4)} (약 ${Math.max(1, Math.round(claude.usd * WON_PER_USD))}원)`}{local && ` · 로컬 AI ${local.calls}번`}</p>
          {previewStatus && <p role="status" aria-label="휴대폰용 미리보기" className="text-[11px] text-slate-500">{previewStatus}</p>}
        </section>

        <Link to={`/projects/${projectId}/tools`} className="flex items-center gap-2 rounded-xl border border-slate-200 px-3 py-2.5 text-slate-700 hover:border-sky-400"><Wrench size={16} />모든 도구</Link>
      </div>
    </div>
  </div>;
}
