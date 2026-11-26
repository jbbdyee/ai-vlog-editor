import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, ListOrdered, LoaderCircle } from "lucide-react";
import { getScenePick, remakeFromScenePick, runScenePick, thumbUrl, type PickedScene } from "@/api/chat-edit";
import { ApiError } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const WON_PER_USD = 1450;
const won = (usd: number) => Math.max(1, Math.round((usd * WON_PER_USD) / 10) * 10).toLocaleString();
const LENGTHS = [5, 8, 12, 20];
const SCORE_NAMES = ["빼야 함", "빼도 됨", "쓰면 좋음", "꼭 씀"];
const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(Math.round(seconds % 60)).padStart(2, "0")}`;
const errorText = (error: unknown) => error instanceof ApiError ? error.message : "요청을 처리하지 못했어요.";

function SceneLine({ projectId, scene }: { projectId: string; scene: PickedScene }) {
  return <li className="flex gap-2 rounded-lg bg-white p-1.5">
    <img alt="" loading="lazy" className="h-12 w-20 shrink-0 rounded object-cover"
      src={thumbUrl(projectId, scene.source_video_id, (scene.clip_start + scene.clip_end) / 2)} />
    <div className="min-w-0 flex-1 text-xs">
      <p className="font-semibold text-slate-800">{scene.number}번 · {scene.clock || "시각 모름"} <span className="font-normal text-slate-500">· {SCORE_NAMES[scene.score]} · {(scene.clip_end - scene.clip_start).toFixed(1)}초 (장면 {(scene.scene_end - scene.scene_start).toFixed(1)}초 중)</span></p>
      <p className="text-slate-700">{scene.what || "-"}</p>
      <p className="text-slate-500">{scene.why}</p>
    </div>
  </li>;
}

/** TODO 43: Claude picks the scenes from pictures and speech — estimate (43-2), one paid run (43-3), use it (43-4). */
export function ScenePickCard({ projectId }: { projectId: string }) {
  const client = useQueryClient();
  const [minutes, setMinutes] = useState(8);
  const [confirming, setConfirming] = useState(false);
  const key = ["scene-pick", projectId, minutes];
  const info = useQuery({ queryKey: key, queryFn: () => getScenePick(projectId, minutes) });
  const run = useMutation({ mutationFn: () => runScenePick(projectId, minutes), onSuccess: (value) => {
    client.setQueryData(key, value);
    setConfirming(false);
  } });
  const data = typeof info.data?.usd_low === "number" ? info.data : undefined;
  const picked = data?.picked ?? undefined;
  const apply = useMutation({ mutationFn: () => remakeFromScenePick(projectId, picked!), onSuccess: (value) => {
    client.setQueryData(["chat-edit", projectId], value);
  } });
  const pickedCount = picked?.chapters.reduce((sum, chapter) => sum + chapter.scenes.length, 0) ?? 0;
  return <section aria-label="Claude 장면 고르기" className="space-y-2 rounded-xl border border-sky-200 bg-sky-50/60 p-3">
    <div className="flex items-center gap-1.5">
      <Clapperboard size={16} className="text-sky-600" />
      <h3 className="font-semibold text-slate-800">Claude 장면 고르기</h3>
      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] text-amber-700">유료</span>
    </div>
    <p className="text-xs text-slate-600">장면 전체를 Claude가 사진·대사로 보고, 쓸 장면과 쓸 구간을 골라 하루 흐름대로 챕터를 짜요.</p>
    <div role="group" aria-label="고를 길이" className="flex flex-wrap gap-1.5">
      {LENGTHS.map((value) => <button key={value} type="button" aria-label={`장면 고르기 ${value}분`} aria-pressed={minutes === value} disabled={run.isPending} onClick={() => setMinutes(value)}
        className={`h-7 rounded-full px-3 text-xs ${minutes === value ? "bg-sky-100 font-bold text-sky-800" : "border border-slate-300 bg-white text-slate-600 hover:border-sky-400"}`}>{value}분</button>)}
    </div>
    {data && <>
      <p aria-label="장면 고르기 예상 금액" className="text-sm font-semibold text-slate-800">
        예상 약 {won(data.usd_low)}~{won(data.usd_high)}원
        <span className="font-normal text-slate-500"> (${data.usd_low.toFixed(2)}~${data.usd_high.toFixed(2)} · {data.model})</span></p>
      <details className="text-xs text-slate-600">
        <summary className="cursor-pointer">함께 보내는 것</summary>
        <ul aria-label="장면 고르기에 보내는 것" className="mt-1 list-disc space-y-0.5 pl-4">
          <li>장면 {data.scenes}개(대사 있는 장면 {data.scenes_with_speech}개) · 장면마다 사진 2장(모두 {data.pictures}장) · {data.chunks}번에 나눠 보낸 뒤, 메모를 모아 한 번 더</li>
          <li>대사는 시각과 함께{data.voice_marked ? ", 나/남 표시 포함" : " (나/남 표시는 아직 없음)"}</li>
          <li>목표 길이 {data.target_minutes}분 · 내 규칙 {data.rules.length}개{data.rules.length ? `: ${data.rules.join(" / ")}` : ""}</li>
          <li>내 편집 취향 글 {data.has_brief ? "있음" : "없음"} · 오늘 있었던 일 {data.has_day_brief ? "있음" : "없음"}</li>
          <li>좋아하는 영상 숫자: {data.reference.length ? data.reference.join(" · ") : "없음"}</li>
        </ul>
        <p className="mt-1 text-[11px] text-slate-500">입력 약 {data.input_tokens.toLocaleString()} · 출력 약 {data.output_tokens.toLocaleString()}~{data.output_tokens_high.toLocaleString()} 토큰</p>
      </details>
      {!confirming
        ? <Button type="button" size="sm" disabled={run.isPending} onClick={() => setConfirming(true)}>{picked ? "다시 고르기" : "장면 고르기 시작"}</Button>
        : <div className="space-y-2 rounded-lg border border-amber-300 bg-amber-100 p-2 text-xs text-amber-700">
            <p>Claude를 부르면 약 {won(data.usd_low)}~{won(data.usd_high)}원이 들어요. 사진을 만들고 답을 받는 데 몇 분 걸려요. 지금 편집은 바뀌지 않아요.</p>
            <div className="flex gap-2">
              <Button type="button" size="sm" disabled={run.isPending} onClick={() => run.mutate()}>
                <span className="flex items-center gap-1">{run.isPending && <LoaderCircle size={14} className="animate-spin" />}{run.isPending ? "고르는 중…" : "부르기"}</span></Button>
              <Button type="button" size="sm" variant="secondary" disabled={run.isPending} onClick={() => setConfirming(false)}>그만두기</Button>
            </div>
          </div>}
    </>}
    {picked && <div aria-label="Claude가 고른 장면" className="space-y-2">
      <div>
        <p className="font-semibold text-slate-900">{picked.title}</p>
        <p className="text-xs text-slate-600">{picked.summary}</p>
        <p className="text-xs text-slate-500 tabular-nums">장면 {pickedCount}개 · 합계 {clock(picked.total_seconds)} (목표 {picked.target_minutes}분) · 뺀 장면 {picked.left_out.length}개 · 든 돈 약 {won(picked.usd)}원(${picked.usd.toFixed(3)})</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" size="sm" disabled={apply.isPending} onClick={() => apply.mutate()}>
          <span className="flex items-center gap-1">{apply.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <ListOrdered size={14} />}이대로 편집안 만들기</span></Button>
        <span className="text-[11px] text-slate-500">무료 · 지금 편집안은 ↶ 되돌리기로 돌아와요</span>
      </div>
      {apply.isSuccess && <p role="status" className="text-xs text-sky-700">Claude가 고른 장면으로 편집안을 바꿨어요.</p>}
      <ol className="max-h-[28rem] space-y-2 overflow-y-auto">
        {picked.chapters.map((chapter, index) => <li key={`${index}:${chapter.title}`} className="space-y-1">
          <p className="text-xs font-semibold text-sky-700">챕터 {index + 1}. {chapter.title} <span className="font-normal text-slate-500">· {chapter.description}</span></p>
          <p className="text-[11px] text-slate-500">이유: {chapter.reason}</p>
          <ul className="space-y-1">{chapter.scenes.map((scene) => <SceneLine key={scene.candidate_id} projectId={projectId} scene={scene} />)}</ul>
        </li>)}
      </ol>
      {picked.left_out.length > 0 && <details className="text-xs text-slate-600">
        <summary className="cursor-pointer">뺀 장면 {picked.left_out.length}개</summary>
        <ul className="mt-1 space-y-1">{picked.left_out.map((scene) => <SceneLine key={scene.candidate_id} projectId={projectId} scene={scene} />)}</ul>
      </details>}
    </div>}
    {info.isLoading && <p className="text-xs text-slate-500">예상 금액 계산 중…</p>}
    {(info.error || run.error || apply.error) && <Alert>{errorText(info.error ?? run.error ?? apply.error)}</Alert>}
  </section>;
}
