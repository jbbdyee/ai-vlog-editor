import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clapperboard, Download, Film, LoaderCircle, Send, Undo2 } from "lucide-react";
import { ApiError } from "@/api/projects";
import { formatDuration } from "@/api/story-direction";
import { editReelDraft, getReelOptions, getReelStatus, getReelVideo, reelVideoSrc, startReelDraft, startReelVideo, undoReelDraft, type ReelOption, type ReelOptions, type ReelTextStyle } from "@/api/reels";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { PreviewRange } from "@/features/projects/source-preview";

const errors: Record<string, string> = {
  NO_SOURCE_VIDEOS: "올린 영상이 없습니다. 먼저 영상을 올려 주세요.",
  NO_SHOTS: "영상에서 장면을 나누지 못했습니다.",
  REEL_DRAFT_FAILED: "릴스 초안을 만들다가 문제가 생겼습니다. 다시 시도해 주세요.",
  REEL_DRAFT_RUNNING: "이미 릴스 초안을 만드는 중입니다.",
};

function errorText(error: unknown): string {
  if (error instanceof ApiError) return (error.code && errors[error.code]) || error.message;
  return "릴스 초안을 만들지 못했습니다.";
}

function Choices({ label, options, value, onChange, disabled }: { label: string; options: ReelOption[]; value: string; onChange: (key: string) => void; disabled?: boolean }) {
  return <div className="space-y-1.5">
    <p className="text-xs font-semibold text-slate-400">{label}</p>
    <div className="flex flex-wrap gap-2" role="group" aria-label={label}>
      {options.map((option) => {
        const on = option.key === value;
        return <button key={option.key} type="button" aria-pressed={on} disabled={disabled} onClick={() => onChange(option.key)}
          className={`rounded-full border px-3 py-1 text-sm transition disabled:opacity-60 ${on ? "border-cyan-300 bg-cyan-300 font-semibold text-slate-950" : "border-white/15 text-slate-200 hover:border-cyan-300/60"}`}>
          {option.label}
        </button>;
      })}
    </div>
  </div>;
}

const videoErrors: Record<string, string> = {
  REEL_DRAFT_MISSING: "먼저 릴스 초안을 만들어 주세요.",
  REEL_DRAFT_RUNNING: "릴스 초안을 만드는 중입니다. 끝난 뒤에 영상을 만들어 주세요.",
  REEL_VIDEO_RUNNING: "이미 세로 영상을 만드는 중입니다.",
  REEL_SOURCE_MISSING: "초안에 쓰인 원본 영상 파일을 찾지 못했습니다.",
  REEL_FONT_MISSING: "글자를 입힐 한글 글꼴(맑은 고딕 굵게)을 찾지 못했습니다.",
  REEL_TEXT_FAILED: "제목·문구를 영상에 입히다가 문제가 생겼습니다.",
};

function videoErrorText(code: string | null | undefined, error?: unknown): string {
  if (error instanceof ApiError) return (error.code && videoErrors[error.code]) || error.message;
  return (code && videoErrors[code]) || "세로 영상을 만들지 못했습니다. 다시 시도해 주세요.";
}

const defaultTextStyle: ReelTextStyle = { template: "clean", color: "auto", position: "auto", size: "normal", motion: "pop" };

/** TODO 13: pick the text template, colour, place and size before making the video (TODO 15: and the motion). */
function TextStylePicker({ options, value, onChange, disabled }: { options: ReelOptions; value: ReelTextStyle; onChange: (value: ReelTextStyle) => void; disabled: boolean }) {
  const templates = options.text_templates ?? [];
  if (templates.length === 0) return null;
  return <div className="space-y-3" aria-label="글자 꾸미기">
    <div className="space-y-1.5">
      <p className="text-xs font-semibold text-slate-400">글자 템플릿</p>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3" role="group" aria-label="글자 템플릿">
        {templates.map((template) => {
          const on = template.key === value.template;
          return <button key={template.key} type="button" aria-pressed={on} disabled={disabled} onClick={() => onChange({ ...value, template: template.key })}
            className={`min-w-0 rounded-xl border px-3 py-2 text-left transition disabled:opacity-60 ${on ? "border-cyan-300 bg-cyan-300/10" : "border-white/15 hover:border-cyan-300/60"}`}>
            <span className={`block text-sm font-semibold ${on ? "text-cyan-200" : "text-slate-100"}`}>{template.label}</span>
            <span className="block text-xs text-slate-400">{template.hint}</span>
          </button>;
        })}
      </div>
    </div>
    <Choices label="포인트 색" options={options.text_colors ?? []} value={value.color} onChange={(color) => onChange({ ...value, color })} disabled={disabled} />
    <Choices label="문구 위치" options={options.text_positions ?? []} value={value.position} onChange={(position) => onChange({ ...value, position })} disabled={disabled} />
    <Choices label="글자 크기" options={options.text_sizes ?? []} value={value.size} onChange={(size) => onChange({ ...value, size })} disabled={disabled} />
    {(options.text_motions?.length ?? 0) > 0 && <Choices label="글자 움직임" options={options.text_motions ?? []} value={value.motion ?? "pop"} onChange={(motion) => onChange({ ...value, motion })} disabled={disabled} />}
  </div>;
}

/** TODO 12: turn the saved draft into a 9:16 video with the title, name tags and lines burned in. */
function ReelVideoPanel({ projectId, draftKey, draftRunning, options }: { projectId: string; draftKey: string; draftRunning: boolean; options?: ReelOptions }) {
  const queryClient = useQueryClient();
  const [textStyle, setTextStyle] = useState<ReelTextStyle>(defaultTextStyle);
  const [styleSynced, setStyleSynced] = useState(false);
  const status = useQuery({
    queryKey: ["reel-video", projectId, draftKey], queryFn: () => getReelVideo(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const start = useMutation({
    mutationFn: () => startReelVideo(projectId, textStyle),
    onSuccess: (value) => queryClient.setQueryData(["reel-video", projectId, draftKey], value),
  });
  const running = status.data?.status === "RUNNING" || start.isPending;
  const video = status.data?.video;
  // Start from the look the last video was made with, once.
  useEffect(() => {
    if (video?.text_style && !styleSynced) { setTextStyle(video.text_style); setStyleSynced(true); }
  }, [video, styleSynced]);
  return <div className="space-y-3 rounded-xl border border-white/10 bg-white/[.03] p-3" aria-label="세로 영상">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-100">세로 영상 (9:16)</p>
        <p className="text-xs text-slate-400">초안 순서대로 이어 붙이고 첫 화면 제목·이름표·문구를 고른 글자 템플릿으로 입힙니다. 30초짜리 릴스는 20초쯤 걸려요. 템플릿만 바꿔 다시 만들어 비교해 보세요.</p>
      </div>
      <Button onClick={() => start.mutate()} disabled={running || draftRunning}>
        <span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <Film size={16} />}{running ? "세로 영상 만드는 중…" : video ? "세로 영상 다시 만들기" : "세로 영상 만들기"}</span>
      </Button>
    </div>
    {options && <TextStylePicker options={options} value={textStyle} onChange={setTextStyle} disabled={running || draftRunning} />}
    {status.data?.status === "RUNNING" && <p role="status" className="text-sm text-cyan-200 tabular-nums">
      {status.data.step}{status.data.total > 0 ? ` · ${status.data.done}/${status.data.total}개` : ""}
    </p>}
    {status.isError && <Alert>{videoErrorText(null, status.error)}</Alert>}
    {start.isError && <Alert>{videoErrorText(null, start.error)}</Alert>}
    {status.data?.status === "FAILED" && <Alert>{videoErrorText(status.data.error_code)}</Alert>}
    {video && <div className="flex flex-wrap items-start gap-4">
      <video key={video.url} controls playsInline preload="metadata" src={reelVideoSrc(video)} aria-label="완성된 세로 영상"
        className="aspect-[9/16] w-full max-w-[260px] rounded-xl bg-black" />
      <div className="min-w-0 space-y-2 text-sm text-slate-300">
        <p className="tabular-nums">길이 <b className="text-slate-50">{formatDuration(video.duration_seconds)}</b> · 장면 {video.scene_count}개 · {(video.file_size_bytes / 1024 / 1024).toFixed(1)}MB</p>
        {video.text_style && options?.text_templates && <p className="text-xs text-slate-400">글자 템플릿: {options.text_templates.find((t) => t.key === video.text_style?.template)?.label ?? video.text_style.template}</p>}
        {!video.matches_draft && <p className="text-xs text-amber-200">초안을 다시 만들어서 이 영상은 예전 초안으로 만든 것입니다. 지금 초안으로 보려면 다시 만들어 주세요.</p>}
        <a href={reelVideoSrc(video)} download="reel.mp4" className="inline-flex items-center gap-1.5 text-cyan-300 underline"><Download size={14} />영상 내려받기</a>
      </div>
    </div>}
  </div>;
}

const editErrors: Record<string, string> = {
  REEL_EDIT_NOT_UNDERSTOOD: "무엇을 고칠지 알아듣지 못했어요. 예: \"3번 더 길게\", \"여기에 자막 '최애템' 추가\", \"4번 빼\"",
  REEL_DRAFT_RUNNING: "초안을 만드는 중이라 끝난 뒤에 고칠 수 있어요.",
  REEL_VIDEO_RUNNING: "세로 영상을 만드는 중이라 끝난 뒤에 고칠 수 있어요.",
  REEL_UNDO_EMPTY: "되돌릴 고치기가 없어요.",
};

const quickEdits = [["더 길게", "여기 더 길게"], ["더 짧게", "여기 더 짧게"], ["자막 새로", "여기 자막 다시 써줘"], ["장면 빼기", "여기 빼"]] as const;

/** TODO 16: change the draft by talking ("3번 더 길게"); "여기" is the scene picked in the list below. */
function ReelChat({ projectId, selected, canUndo, disabled, onChanged }: { projectId: string; selected: number | null; canUndo: boolean; disabled: boolean; onChanged: () => void }) {
  const queryClient = useQueryClient();
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<{ done: string[]; skipped: string[] } | null>(null);
  const edit = useMutation({
    mutationFn: (text: string) => editReelDraft(projectId, text, selected),
    onSuccess: (value) => {
      queryClient.setQueryData(["reel-draft", projectId], value);
      setResult({ done: value.done_edits, skipped: value.skipped_edits });
      if (value.done_edits.length) { setMessage(""); onChanged(); }
    },
    onError: () => setResult(null),
  });
  const undo = useMutation({
    mutationFn: () => undoReelDraft(projectId),
    onSuccess: (value) => { queryClient.setQueryData(["reel-draft", projectId], value); setResult({ done: ["고치기 전 초안으로 되돌렸어요"], skipped: [] }); onChanged(); },
  });
  const busy = disabled || edit.isPending || undo.isPending;
  const send = (text: string) => { if (text.trim() && !busy) edit.mutate(text.trim()); };
  const failure = edit.error ?? undo.error;
  return <div className="space-y-2 rounded-xl border border-fuchsia-300/20 bg-fuchsia-300/[.04] p-3" aria-label="말로 고치기">
    <p className="text-sm font-semibold text-slate-100">말로 고치기</p>
    <p className="text-xs text-slate-400">{selected ? <>고른 장면: <b className="text-fuchsia-200">{selected}번</b> · "여기"는 이 장면이에요</> : "아래 장면을 누르면 \"여기\"로 고를 수 있어요. 번호로 말해도 돼요(예: 3번)."}</p>
    {selected && <div className="flex flex-wrap gap-2">
      {quickEdits.map(([label, text]) => <Button key={label} size="sm" variant="secondary" disabled={busy} onClick={() => send(text)}>{label}</Button>)}
    </div>}
    <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); send(message); }}>
      <input id="reel-chat" aria-label="고칠 내용" value={message} onChange={(event) => setMessage(event.target.value)} disabled={busy} maxLength={300}
        placeholder="예: 3번 더 길게 / 여기에 자막 '최애템' 추가 / 제목을 '여름 꿀템 3가지'로"
        className="min-w-0 flex-1 rounded-lg border border-white/15 bg-[#0b1420] px-3 py-2 text-sm text-slate-100 placeholder:text-slate-500" />
      <Button type="submit" size="sm" disabled={busy || !message.trim()}>
        <span className="flex items-center gap-1">{edit.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}고치기</span>
      </Button>
      {canUndo && <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => undo.mutate()}>
        <span className="flex items-center gap-1"><Undo2 size={14} />되돌리기</span>
      </Button>}
    </form>
    {result && <div role="status" className="space-y-0.5 text-sm">
      {result.done.map((line) => <p key={line} className="text-emerald-200">✓ {line}</p>)}
      {result.skipped.map((line) => <p key={line} className="text-amber-200">· {line}</p>)}
      {result.done.length > 0 && <p className="text-xs text-slate-500">세로 영상에 반영하려면 위에서 세로 영상을 다시 만들어 주세요.</p>}
    </div>}
    {failure && <Alert>{failure instanceof ApiError ? (failure.code && editErrors[failure.code]) || failure.message : "초안을 고치지 못했어요."}</Alert>}
  </div>;
}

/** TODO 10: pick short/long, mode, pace and length, then the AI drafts a reel (order, length per shot, title, lines). */
export function ReelDraftCard({ projectId, onPreview }: { projectId: string; onPreview?: (range: PreviewRange) => void }) {
  const queryClient = useQueryClient();
  const options = useQuery({ queryKey: ["reel-options"], queryFn: getReelOptions, staleTime: Infinity });
  const status = useQuery({
    queryKey: ["reel-draft", projectId], queryFn: () => getReelStatus(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const [format, setFormat] = useState("short");
  const [mode, setMode] = useState("auto");
  const [pace, setPace] = useState("normal");
  const [seconds, setSeconds] = useState(30);
  // Show the saved draft's choices once, so "다시 만들기" starts from what produced it.
  const saved = status.data?.draft;
  const [synced, setSynced] = useState(false);
  useEffect(() => {
    if (saved && !synced) { setPace(saved.pace); setSeconds(saved.target_seconds); setSynced(true); }
  }, [saved, synced]);
  const start = useMutation({
    mutationFn: () => startReelDraft(projectId, { mode, pace, target_seconds: seconds }),
    onSuccess: (value) => queryClient.setQueryData(["reel-draft", projectId], value),
  });
  const running = status.data?.status === "RUNNING" || start.isPending;
  const draft = status.data?.draft;
  const byAi = draft?.engine.startsWith("llm:");
  // TODO 16: the scene "여기" means. Cleared when a scene is added or removed, since the numbers move.
  const [selected, setSelected] = useState<number | null>(null);
  const sceneCount = draft?.scenes.length ?? 0;
  useEffect(() => { setSelected(null); }, [sceneCount]);
  const picked = selected !== null && selected <= sceneCount ? selected : null;
  return <Card id="reel-draft" className="mt-3 scroll-mt-24 sm:mt-6 sm:scroll-mt-3">
    <CardHeader>
      <CardTitle>숏폼·롱폼 만들기</CardTitle>
      <CardDescription>무엇을 만들지 먼저 고르세요. 숏폼은 AI가 장면 순서, 장면별 길이, 첫 화면 제목, 장면 문구를 짠 초안을 보여줍니다. 초안이 나오면 바로 세로 영상으로 만들 수 있습니다.</CardDescription>
    </CardHeader>
    <CardContent className="space-y-4">
      {options.isError && <Alert>{errorText(options.error)}</Alert>}
      {options.data && <div className="space-y-3">
        <Choices label="만들 영상" options={options.data.formats} value={format} onChange={setFormat} disabled={running} />
        {format === "long" ? <div className="rounded-xl border border-white/10 bg-white/[.03] p-3 text-sm text-slate-300">
          롱폼(유튜브)은 아래 <a href="#story-direction" className="text-cyan-300 underline">추천 편집 방향</a>에서 길이를 고르고 편집 계획을 만듭니다. 모드·속도 고르기는 다음 단계에서 롱폼에도 붙입니다.
        </div> : <>
          <Choices label="모드" options={options.data.modes} value={mode} onChange={setMode} disabled={running} />
          <Choices label="속도" options={options.data.paces} value={pace} onChange={setPace} disabled={running} />
          <Choices label="길이" options={options.data.lengths.map((value) => ({ key: String(value), label: `${value}초` }))}
            value={String(seconds)} onChange={(key) => setSeconds(Number(key))} disabled={running} />
          <Button onClick={() => start.mutate()} disabled={running}>
            <span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <Clapperboard size={16} />}{running ? "릴스 초안 만드는 중…" : draft ? "릴스 초안 다시 만들기" : "릴스 초안 만들기"}</span>
          </Button>
          {status.data?.status === "RUNNING" && <p role="status" className="text-sm text-cyan-200 tabular-nums">
            {status.data.step}{status.data.total > 0 ? ` · ${status.data.done}/${status.data.total}개` : ""}
            <span className="block text-xs text-slate-500">처음에는 장면마다 화면을 읽느라 몇 분 걸립니다. 같은 영상으로 다시 만들면 빨라요.</span>
          </p>}
          {start.isError && <Alert>{errorText(start.error)}</Alert>}
          {status.data?.status === "FAILED" && <Alert>{errors[status.data.error_code ?? ""] ?? "릴스 초안을 만들지 못했습니다."}</Alert>}
        </>}
      </div>}
      {format === "short" && draft && <div className="space-y-3" aria-label="릴스 초안">
        <div className="rounded-xl border border-cyan-300/20 bg-cyan-300/[.04] p-3">
          <p className="text-xs text-slate-400">첫 화면 제목</p>
          {draft.title_lead && <p className="text-sm text-slate-300">{draft.title_lead}</p>}
          <p className="text-xl font-semibold text-slate-50">{draft.title}</p>
          <p className="mt-1 text-sm text-slate-300 tabular-nums">{draft.mode_label} · {draft.pace_label} · 합계 <b className="text-slate-50">{formatDuration(draft.total_seconds)}</b> (목표 {draft.target_seconds}초) · 장면 {draft.scenes.length}개 / 나눈 장면 {draft.shot_count}개</p>
          <p className="mt-1 text-xs text-slate-500">{byAi ? `AI 초안 (${draft.engine.replace("llm:", "")})` : "AI 없이 촬영 순서대로 만든 기본 초안"}</p>
          {draft.notes.map((note) => <p key={note} className="text-xs text-amber-200">{note}</p>)}
        </div>
        <ReelVideoPanel projectId={projectId} draftRunning={running} options={options.data}
          draftKey={`${draft.mode}|${draft.title_lead ?? ""}|${draft.title}|${draft.total_seconds}|${draft.scenes.map((s) => `${s.shot_index}:${s.caption}`).join(",")}`} />
        <ReelChat projectId={projectId} selected={picked} canUndo={Boolean(status.data?.can_undo)} disabled={running} onChanged={() => undefined} />
        <ol className="space-y-2">
          {draft.scenes.map((scene, index) => <li key={`${scene.shot_index}:${index}`} className={`flex min-w-0 flex-wrap items-start justify-between gap-2 rounded-xl border p-3 ${picked === index + 1 ? "border-fuchsia-300/60 bg-fuchsia-300/[.06]" : "border-white/10 bg-[#0b1420]"}`}>
            <button type="button" aria-pressed={picked === index + 1} aria-label={`${index + 1}번 장면 고르기`} onClick={() => setSelected(picked === index + 1 ? null : index + 1)} className="min-w-0 flex-1 text-left">
              <p className="text-xs text-slate-500 tabular-nums">{index + 1}. {scene.is_hook ? <span className="mr-1 rounded-full bg-amber-300/15 px-2 py-0.5 font-semibold text-amber-200">맨 앞 장면</span> : null}{scene.source_filename} · {scene.start_seconds.toFixed(1)}–{scene.end_seconds.toFixed(1)}초 ({(scene.end_seconds - scene.start_seconds).toFixed(1)}초)</p>
              {scene.label && <p className="mt-1 text-xs font-semibold text-cyan-200">{scene.label}</p>}
              <p className="mt-0.5 text-base font-semibold text-slate-50">{scene.caption || <span className="text-slate-500">(문구 없음)</span>}</p>
              {scene.shot_caption && <p className="mt-0.5 text-xs text-slate-400">AI가 본 화면: {scene.shot_caption}</p>}
            </button>
            <Button size="sm" variant="secondary" onClick={() => onPreview?.({ candidateId: `reel:${scene.shot_index}`, sourceId: scene.source_video_id, start: scene.start_seconds, end: scene.end_seconds })}>미리보기</Button>
          </li>)}
        </ol>
      </div>}
    </CardContent>
  </Card>;
}
