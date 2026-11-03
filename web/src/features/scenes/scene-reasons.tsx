import { sceneReasons, type SceneCandidate } from "@/api/scenes";

/** Why a scene was recommended: evidence-derived labels plus the speech heard inside it. */
export function SceneReasons({ candidate, compact = false }: { candidate: Pick<SceneCandidate, "evidence" | "transcript_text" | "visual_caption" | "visual_tags">; compact?: boolean }) {
  const { reasons, cautions } = sceneReasons(candidate);
  const raw = candidate.evidence.map((item) => `${item.modality} · ${item.evidence_type} ${item.count}`).join(", ");
  return <div className={compact ? "mt-1.5 space-y-1" : "mt-3 space-y-2"}>
    <div className="flex flex-wrap gap-1.5" title={raw || undefined} aria-label="추천 이유">
      {reasons.length ? reasons.map((reason) => <span key={reason} className="rounded-lg bg-cyan-300/10 px-2 py-0.5 text-xs text-cyan-100">{reason}</span>)
        : <span className="text-xs text-slate-500">{candidate.evidence.length ? `관측 근거 ${candidate.evidence.length}종` : "연결된 근거 요약 없음"}</span>}
      {cautions.map((caution) => <span key={caution} className="rounded-lg bg-amber-300/10 px-2 py-0.5 text-xs text-amber-200">{caution}</span>)}
    </div>
    {candidate.visual_caption && <p className="flex flex-wrap items-center gap-1.5 text-xs leading-5 text-violet-100" aria-label="AI 화면 분석"><span className="font-semibold text-violet-300">화면</span>{candidate.visual_caption}{(candidate.visual_tags ?? []).map((tag) => <span key={tag} className="rounded-md bg-violet-300/10 px-1.5 py-0.5 text-[11px] text-violet-200">#{tag}</span>)}</p>}
    {candidate.transcript_text && <p className="break-words text-xs leading-5 text-slate-300 [overflow-wrap:anywhere]">“{candidate.transcript_text}”</p>}
  </div>;
}
