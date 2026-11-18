import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { LoaderCircle } from "lucide-react";
import { getTasteBrief, getTasteScores, runTasteScores, saveTasteBrief } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const SCORE_LABELS = ["빼야 함", "빼도 됨", "남기면 좋음", "꼭 남김"];

function errorText(error: unknown) {
  return error instanceof ApiError ? error.message : "요청을 처리하지 못했어요.";
}

/** TODO 32-4: my editing taste in my own words (all projects) and the scene scores made from it. */
export function TasteBriefCard({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const brief = useQuery({ queryKey: ["edit-taste"], queryFn: getTasteBrief });
  const scores = useQuery({ queryKey: ["taste-scores", projectId], queryFn: () => getTasteScores(projectId) });
  const [text, setText] = useState("");
  const [confirming, setConfirming] = useState(false);
  useEffect(() => { if (brief.data !== undefined) setText(brief.data); }, [brief.data]);
  const save = useMutation({ mutationFn: () => saveTasteBrief(text), onSuccess: (value) => {
    client.setQueryData(["edit-taste"], value);
    void client.invalidateQueries({ queryKey: ["taste-scores", projectId] });
  } });
  const run = useMutation({ mutationFn: () => runTasteScores(projectId), onSuccess: (value) => {
    client.setQueryData(["taste-scores", projectId], value);
    setConfirming(false);
  } });
  const info = scores.data;
  const counts = info?.counts ?? {};
  const hasScores = Object.keys(counts).length > 0;
  return <section aria-label="내 편집 취향" className="space-y-2 rounded-xl border border-white/10 p-3 text-sm">
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <h2 className="font-semibold text-slate-100">내 편집 취향</h2>
      <span className="text-[11px] text-slate-500">모든 프로젝트가 같이 써요 · 장면 점수의 기준</span>
    </div>
    <textarea id="taste-brief" aria-label="내 편집 취향 설명" value={text} maxLength={6000} rows={6}
      onChange={(event) => setText(event.target.value)}
      placeholder="꼭 남기는 장면, 거의 빼는 장면, 예쁘다고 느끼는 내 모습, 하루 흐름, 한 컷 길이…"
      className="w-full rounded-lg border border-white/15 bg-[#0b1420] p-2 text-sm text-slate-100 placeholder:text-slate-500" />
    <div className="flex flex-wrap items-center gap-2">
      <Button type="button" size="sm" variant="secondary" disabled={save.isPending || text === (brief.data ?? "")} onClick={() => save.mutate()}>
        {save.isPending ? "저장 중…" : "취향 저장"}</Button>
      {info && <span className="text-xs text-slate-400">장면 {info.scenes}개 · 내 편집 예시 {info.examples}개{info.examples === 0 ? "(다른 프로젝트에서 '내 편집과 비교'를 하면 생겨요)" : ""}</span>}
    </div>
    {hasScores && <p className="text-xs text-slate-300" aria-label="장면 점수">
      장면 점수: {[3, 2, 1, 0].map((value) => `${SCORE_LABELS[value]} ${counts[String(value)] ?? 0}`).join(" · ")}
      <span className="text-slate-500"> · 길이를 고르면 점수 낮은 장면부터 빠져요</span></p>}
    {info && (!confirming
      ? <Button type="button" size="sm" disabled={!text.trim() || run.isPending} onClick={() => setConfirming(true)}>
          {hasScores ? "취향으로 장면 점수 다시 매기기" : "취향으로 장면 점수 매기기"}</Button>
      : <div className="space-y-2 rounded-lg border border-amber-300/40 bg-amber-300/10 p-2 text-xs text-amber-100">
          <p>Claude({info.model})가 장면 {info.scenes}개를 읽어요. 유료 · 예상 약 ${info.usd.toFixed(3)} (입력 {info.input_tokens.toLocaleString()} · 출력 {info.output_tokens.toLocaleString()} 토큰).</p>
          <div className="flex gap-2">
            <Button type="button" size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
              <span className="flex items-center gap-1">{run.isPending && <LoaderCircle size={14} className="animate-spin" />}{run.isPending ? "점수 매기는 중…" : "점수 매기기"}</span></Button>
            <Button type="button" size="sm" variant="secondary" disabled={run.isPending} onClick={() => setConfirming(false)}>그만두기</Button>
          </div>
        </div>)}
    {(save.error || run.error || scores.error) && <Alert>{errorText(save.error ?? run.error ?? scores.error)}</Alert>}
  </section>;
}
