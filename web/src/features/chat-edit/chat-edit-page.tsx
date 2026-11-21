import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Clapperboard, LoaderCircle, RefreshCw, Send, Undo2, X } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { addEditRule, answerRuleCandidate, clock, cutAt, deleteEditRule, ensurePreviews, getChatEdit, getEditRules, pickChatChoice, previewUrl, remakeFromStoryDirection, sendChatEdit, startFromStoryDirection, thumbUrl, undoChatEdit, type ChatCut, type ChatEditView, type ChatMessage } from "@/api/chat-edit";
import { ApiError, getProject, isProjectId, sourceMediaUrl } from "@/api/projects";
import { startRendering } from "@/api/edit-render";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { MyEditCard } from "@/features/chat-edit/my-edit-card";
import { TasteBriefCard } from "@/features/chat-edit/taste-brief-card";

const WON_PER_USD = 1450;
const errorText = (error: unknown) => error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다.";

function engineLabel(engine: string | null): string | null {
  if (!engine) return null;
  if (engine === "rule") return "규칙으로 바로";
  if (engine.startsWith("llm:claude/")) return `Claude · ${engine.slice(11)}`;
  if (engine.startsWith("llm:ollama/")) return `로컬 AI · ${engine.slice(11)}`;
  return engine;
}

/** TODO 26: the longform plan as one video + cut strip, and a chat that changes it. */
export function ChatEditPage() {
  const { projectId = "" } = useParams();
  const valid = isProjectId(projectId);
  const client = useQueryClient();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId), enabled: valid });
  const view = useQuery({ queryKey: ["chat-edit", projectId], queryFn: () => getChatEdit(projectId), enabled: valid });
  if (!valid) return <div className="mx-auto max-w-2xl py-24"><Alert>올바른 프로젝트 ID가 아닙니다.</Alert></div>;
  return <div className="py-4 sm:py-6">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={16} /> 홈</Link>
      <h1 className="text-xl font-bold tracking-[-.02em] text-slate-900 sm:text-2xl">{project.data?.name ?? "프로젝트"} · 편집실</h1>
      <span className="text-xs text-slate-500">고치면 바로 저장돼요</span>
    </div>
    {view.isPending && <p className="mt-6 text-sm text-slate-500">편집안을 불러오는 중…</p>}
    {view.isError && <div className="mt-6"><Alert>{errorText(view.error)}</Alert></div>}
    {view.data && (view.data.cuts.length === 0
      ? <NoPlan projectId={projectId} onDone={() => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] })} />
      : <Editor projectId={projectId} data={view.data} />)}
  </div>;
}

function NoPlan({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const start = useMutation({ mutationFn: () => startFromStoryDirection(projectId), onSuccess: onDone });
  return <div className="mt-6 max-w-xl space-y-3 rounded-2xl border border-slate-200 bg-slate-50 p-5">
    <p className="text-sm text-slate-700">아직 저장된 편집안이 없어요. 추천 편집 방향(&lsquo;오늘 있었던 일&rsquo;을 적었다면 그 설명대로)으로 첫 편집안을 만들고 여기서 고쳐요.</p>
    <Button disabled={start.isPending} onClick={() => start.mutate()}><span className="flex items-center gap-2">{start.isPending && <LoaderCircle size={16} className="animate-spin" />}{start.isPending ? "추천 편집 방향 만드는 중…" : "추천 편집 방향으로 첫 편집안 만들기"}</span></Button>
    {start.error && <Alert>{errorText(start.error)}</Alert>}
  </div>;
}

function Editor({ projectId, data }: { projectId: string; data: ChatEditView }) {
  const client = useQueryClient();
  const cuts = data.cuts;
  const total = data.total_seconds;
  const video = useRef<HTMLVideoElement>(null);
  const pending = useRef<{ offset: number; play: boolean } | null>(null);
  const loadedSrc = useRef<string>("");
  const [playing, setPlaying] = useState(0);
  const [time, setTime] = useState(0);
  const [stamp, setStamp] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [brain, setBrain] = useState<string | null>(data.default_brain);
  const [playError, setPlayError] = useState("");
  const list = useRef<HTMLDivElement>(null);
  const timeRef = useRef(0);
  timeRef.current = time;

  const changed = useMemo(() => {
    const last = [...data.messages].reverse().find((item) => item.role === "assistant");
    return new Set(last?.changed ?? []);
  }, [data.messages]);

  // TODO 35: play the light 720p copy when it is made (phones can't play the 4K originals)
  const order = [...new Set(cuts.map((cut) => cut.source_video_id))];
  const previews = useQuery({
    queryKey: ["previews", projectId, order.join(",")],
    queryFn: () => ensurePreviews(projectId, order),
    refetchInterval: (query) => { const state = query.state.data; return state && state.ready.length + state.failed.length < state.total ? 5000 : false; },
  });
  const ready = useMemo(() => new Set(previews.data?.ready ?? []), [previews.data]);
  const sourceSrc = (sourceId: string) => ready.has(sourceId) ? previewUrl(projectId, sourceId) : sourceMediaUrl(projectId, sourceId);

  function goTo(index: number, offset: number, play: boolean) {
    const player = video.current;
    const cut = cuts[index];
    if (!player || !cut) return;
    setPlaying(index);
    setTime(cut.timeline_start + offset);
    const src = sourceSrc(cut.source_video_id);
    if (loadedSrc.current !== src) {
      loadedSrc.current = src;
      pending.current = { offset, play };
      player.src = src;
      player.load();
    } else {
      player.currentTime = cut.start_seconds + offset;
      if (play) void player.play().catch(() => setPlayError("자동 재생이 막혔어요. 재생 버튼을 눌러 주세요."));
    }
  }

  // A new plan (after an edit or undo): stay at the same moment of the edit, paused.
  const signature = cuts.map((cut) => `${cut.candidate_id}:${cut.start_seconds}:${cut.end_seconds}`).join("|");
  useEffect(() => {
    const at = Math.min(timeRef.current, Math.max(0, total - 0.05));
    const index = cutAt(cuts, at);
    video.current?.pause();
    goTo(index, Math.max(0, at - cuts[index].timeline_start), false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  // the copy of the source on screen just got made: switch to it at the same moment, paused
  const currentSource = cuts[playing]?.source_video_id;
  const currentReady = currentSource ? ready.has(currentSource) : false;
  useEffect(() => {
    const player = video.current;
    const cut = cuts[playing];
    if (!currentReady || !player || !cut || loadedSrc.current === previewUrl(projectId, cut.source_video_id)) return;
    if (!player.paused) return;
    setPlayError("");
    goTo(playing, Math.max(0, timeRef.current - cut.timeline_start), false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentReady, currentSource]);

  useEffect(() => { list.current?.scrollTo?.({ top: list.current.scrollHeight }); }, [data.messages.length]);

  function onLoaded() {
    const player = video.current;
    const cut = cuts[playing];
    const wanted = pending.current;
    pending.current = null;
    if (!player || !cut || !wanted) return;
    player.currentTime = cut.start_seconds + wanted.offset;
    if (wanted.play) void player.play().catch(() => setPlayError("자동 재생이 막혔어요. 재생 버튼을 눌러 주세요."));
  }

  function onTime() {
    const player = video.current;
    const cut = cuts[playing];
    if (!player || !cut || pending.current) return;
    const offset = Math.min(Math.max(player.currentTime - cut.start_seconds, 0), cut.length);
    setTime(cut.timeline_start + offset);
    if (player.currentTime >= cut.end_seconds - 0.04 && !player.paused) {
      if (playing < cuts.length - 1) goTo(playing + 1, 0, true);
      else player.pause();
    }
  }

  function onPlay() {
    setStamp(null);
    setPlayError("");
    const player = video.current;
    const cut = cuts[playing];
    if (player && cut && (player.currentTime < cut.start_seconds - 0.1 || player.currentTime >= cut.end_seconds - 0.04)) {
      if (player.currentTime >= cut.end_seconds - 0.04 && playing === cuts.length - 1) goTo(0, 0, true);
      else player.currentTime = cut.start_seconds;
    }
  }

  const refresh = (value: ChatEditView) => client.setQueryData(["chat-edit", projectId], value);
  const send = useMutation({
    mutationFn: ({ text, at }: { text: string; at: number | null }) => sendChatEdit(projectId, text, at, brain),
    onSuccess: (value) => { refresh(value); setMessage(""); setStamp(null); },
    onError: () => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] }),
  });
  const undo = useMutation({ mutationFn: () => undoChatEdit(projectId), onSuccess: refresh });
  // TODO 32: a fresh recommendation (the day in order) in place of the plan; undo brings this plan back
  const [remakeMinutes, setRemakeMinutes] = useState(0);  // TODO 32-3: 0 = the length the AI recommends
  const remake = useMutation({ mutationFn: () => remakeFromStoryDirection(projectId, remakeMinutes || undefined), onSuccess: refresh });
  // TODO 36: the 4K video from the saved plan, right from the edit room (it is watched on the home and in 모든 도구)
  const render = useMutation({ mutationFn: () => startRendering(projectId) });
  const pick = useMutation({
    mutationFn: ({ messageId, choice }: { messageId: string; choice: number }) => pickChatChoice(projectId, messageId, choice),
    onSuccess: refresh,
    onError: () => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] }),
  });
  const busy = send.isPending || undo.isPending || pick.isPending || remake.isPending;
  // TODO 27: sentences saved as rules, shared by every project
  const rules = useQuery({ queryKey: ["edit-rules"], queryFn: getEditRules });
  const setRules = (value: Awaited<ReturnType<typeof getEditRules>>) => client.setQueryData(["edit-rules"], value);
  const addRule = useMutation({ mutationFn: addEditRule, onSuccess: setRules });
  const removeRule = useMutation({ mutationFn: deleteEditRule, onSuccess: setRules });
  // TODO 28: candidates found in what I chose; accepting one makes it a rule chip
  const answer = useMutation({
    mutationFn: ({ key, accept }: { key: string; accept: boolean }) => answerRuleCandidate(projectId, key, accept),
    onSuccess: (value) => { refresh(value); void client.invalidateQueries({ queryKey: ["edit-rules"] }); },
    onError: () => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] }),
  });
  const candidates = data.rule_candidates ?? [];
  const ruleTexts = new Set((rules.data ?? []).map((rule) => rule.text));
  const plain = (text: string) => text.replace(/^\s*\[\d{1,3}:\d{2}\]\s*/, "").replace(/\s+/g, " ").trim();

  function submit() {
    const text = message.trim();
    if (!text || busy) return;
    send.mutate({ text: stamp !== null ? `[${clock(stamp)}] ${text}` : text, at: stamp });
  }

  // TODO 36: one-tap requests about the cut on screen (the same words the chat already understands)
  function quick(text: string) {
    if (busy || !current) return;
    const at = stamp ?? current.timeline_start;
    send.mutate({ text: `[${clock(at)}] ${text}`, at });
  }
  // after a fresh recommendation every cut is "new"; marking all of them says nothing
  const marked = changed.size * 2 <= cuts.length ? changed : new Set<string>();
  const { hash } = useLocation();
  const openTaste = hash === "#taste-brief";
  useEffect(() => {
    if (openTaste) window.setTimeout(() => document.getElementById("taste-brief")?.scrollIntoView?.({ block: "center" }), 600);
  }, [openTaste]);

  const claude = data.usage.find((item) => item.key === "claude");
  const local = data.usage.find((item) => item.key === "ollama");
  const current = cuts[playing];

  return <div className="mt-4 space-y-3">
    <div className="flex flex-wrap items-center justify-end gap-2">
      {previews.data && previews.data.total > 0 && <span role="status" aria-label="휴대폰용 미리보기" className="mr-auto text-xs text-slate-500">
        {`휴대폰용 미리보기 ${previews.data.ready.length + previews.data.failed.length >= previews.data.total ? "준비됨" : "만드는 중"} ${previews.data.ready.length}/${previews.data.total}${previews.data.failed.length ? ` · 못 만든 영상 ${previews.data.failed.length}개` : ""}`}
      </span>}
      {render.isSuccess && <span role="status" className="text-sm text-sky-700">4K 영상을 만들기 시작했어요. 홈에서 확인해요.</span>}
      {render.error && <span className="text-sm text-rose-700">{errorText(render.error)}</span>}
      <Button type="button" variant="secondary" disabled={busy || data.undo_count === 0} onClick={() => undo.mutate()}><Undo2 size={16} />되돌리기{data.undo_count > 0 ? ` (${data.undo_count})` : ""}</Button>
      <Button type="button" disabled={render.isPending || render.isSuccess} onClick={() => render.mutate()}>{render.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Clapperboard size={16} />}4K 영상 만들기</Button>
    </div>
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
    <section aria-label="편집안 미리보기" className="min-w-0 space-y-3">
      <div className="relative">
        <video ref={video} aria-label="편집안 재생" className="block aspect-video w-full rounded-xl bg-black" controls playsInline preload="metadata"
          onLoadedMetadata={onLoaded} onTimeUpdate={onTime} onPlay={onPlay}
          onPause={() => setStamp(timeRef.current)}
          onSeeked={() => { const player = video.current; const cut = cuts[playing]; if (player?.paused && cut && !pending.current) setStamp(cut.timeline_start + Math.min(Math.max(player.currentTime - cut.start_seconds, 0), cut.length)); }}
          onError={() => setPlayError(current && !ready.has(current.source_video_id)
            ? "이 영상의 휴대폰용 미리보기를 아직 만드는 중이에요. 다 되면 바로 틀 수 있어요."
            : "영상을 재생할 수 없어요. 서버 연결을 확인해 주세요.")} />
        {current && <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">컷 {current.number} · {current.source_filename}</span>}
      </div>
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm tabular-nums text-slate-600">
        <span aria-label="편집 속 시각">{clock(time)} / {clock(total)} · 컷 {cuts.length}개</span>
        <div className="flex flex-wrap items-center gap-1.5">
          <div role="group" aria-label="다시 만들 길이" className="flex flex-wrap gap-1.5">
            {[0, 5, 8, 12, 20].map((minutes) => <button key={minutes} type="button" aria-pressed={remakeMinutes === minutes} disabled={busy} onClick={() => setRemakeMinutes(minutes)}
              className={`h-8 rounded-full px-3 text-[13px] ${remakeMinutes === minutes ? "bg-sky-100 font-bold text-sky-800" : "border border-slate-300 bg-white text-slate-600 hover:border-sky-400"}`}>{minutes ? `${minutes}분` : "AI 추천"}</button>)}
          </div>
          <Button type="button" size="sm" variant="secondary" disabled={busy} onClick={() => remake.mutate()} title="지금 편집안은 되돌리기로 다시 가져올 수 있어요">{remake.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <RefreshCw size={14} />}{remake.isPending ? "만드는 중…" : "이 길이로 다시 만들기"}</Button>
        </div>
      </div>
      {playError && <Alert>{playError}</Alert>}
      <CutStrip cuts={cuts} total={total} time={time} playing={playing} changed={marked} onPick={(index) => { video.current?.pause(); goTo(index, 0, false); setStamp(cuts[index].timeline_start); }} />
      {marked.size > 0 && <p className="text-xs text-slate-500"><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-amber-500 bg-amber-100 align-[-1px]" />방금 고친 컷</p>}
      {current && <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-sm">
        <p className="font-semibold text-slate-800">컷 {current.number} · {current.length.toFixed(1)}초 <span className="font-normal text-slate-500">({current.source_filename} {current.start_seconds.toFixed(1)}–{current.end_seconds.toFixed(1)}초)</span></p>
        <p className="mt-1 text-slate-600">{current.speech}</p>
        {current.caption && <p className="mt-1 text-xs text-slate-500">화면: {current.caption}</p>}
      </div>}
      {data.unused.length > 0 && <details className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
        <summary className="cursor-pointer text-slate-700">안 쓴 장면 {data.unused.length}개 <span className="text-xs text-slate-500">· "안 쓴 장면 2 넣어 줘"</span></summary>
        <ol className="mt-2 space-y-1 text-xs text-slate-500">{data.unused.map((scene) => <li key={scene.candidate_id}><b className="text-slate-700">장면 {scene.number}</b> · {scene.source_filename} · {(scene.end_seconds - scene.start_seconds).toFixed(1)}초 · {scene.speech}</li>)}</ol>
      </details>}
      <details open={openTaste} className="rounded-xl border border-slate-200 bg-white p-3 text-sm">
        <summary className="cursor-pointer text-slate-700">내 취향 · 내 편집본과 비교</summary>
        <div className="mt-3 space-y-4"><TasteBriefCard projectId={projectId} /><MyEditCard projectId={projectId} /></div>
      </details>
    </section>

    <section aria-label="대화창" className="flex min-w-0 flex-col rounded-2xl border border-slate-200 bg-white p-3 lg:max-h-[calc(100vh-7rem)] lg:sticky lg:top-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 border-b border-slate-200 pb-2" aria-label="내 규칙">
        <span className="text-xs text-slate-500">내 규칙</span>
        {(rules.data ?? []).map((rule) => <span key={rule.id} className="flex items-center gap-1 rounded-full border border-sky-300 px-2 py-0.5 text-xs text-sky-700">
          {rule.text}<button type="button" aria-label={`규칙 지우기: ${rule.text}`} disabled={removeRule.isPending} onClick={() => removeRule.mutate(rule.id)}><X size={12} /></button>
        </span>)}
        {rules.data?.length === 0 && <span className="text-[11px] text-slate-500">아직 없어요</span>}
      </div>
      {candidates.length > 0 && <div className="mb-2 space-y-1.5" aria-label="규칙 후보">
        {candidates.map((item) => <div key={item.key} className="rounded-lg border border-dashed border-sky-300 bg-sky-50 px-3 py-2 text-sm">
          <p className="text-[11px] text-sky-700">규칙 후보 · {item.key.startsWith("my_edit") || item.why.includes("내 편집본") ? "내 편집본과 비교해서 찾음" : "내 선택 기록에서 찾음"}</p>
          <p className="mt-0.5 font-semibold text-slate-800">{item.text}</p>
          <p className="mt-0.5 text-xs text-slate-500">근거: {item.why}</p>
          <div className="mt-1.5 flex gap-2">
            <Button type="button" size="sm" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: true })}>규칙으로</Button>
            <Button type="button" size="sm" variant="secondary" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: false })}>아니야</Button>
          </div>
        </div>)}
      </div>}
      {(addRule.error || removeRule.error || answer.error) && <div className="mb-2"><Alert>{errorText(addRule.error ?? removeRule.error ?? answer.error)}</Alert></div>}
      <div ref={list} className="min-h-40 flex-1 space-y-2 overflow-y-auto pr-1" aria-live="polite">
        {data.messages.length === 0 && <p className="text-sm text-slate-500">영상을 멈추고 고칠 점을 말해 줘요.</p>}
        {data.messages.map((item, index) => <div key={item.id ?? index} className={item.role === "user" ? "flex flex-col items-end gap-0.5" : ""}>
          <Bubble item={item} projectId={projectId} busy={busy} onPick={(choice) => item.id && pick.mutate({ messageId: item.id, choice })} />
          {item.role === "user" && (ruleTexts.has(plain(item.text))
            ? <span className="text-[11px] text-sky-700">규칙으로 저장됨</span>
            : <button type="button" disabled={addRule.isPending} onClick={() => addRule.mutate(item.text)} className="text-[11px] text-slate-500 hover:text-sky-700">규칙으로 저장</button>)}
        </div>)}
        {send.isPending && <p className="flex items-center gap-2 text-sm text-slate-500"><LoaderCircle size={14} className="animate-spin" />고치는 중…</p>}
      </div>
      {(send.error || undo.error || pick.error || remake.error) && <div className="mt-2"><Alert>{errorText(send.error ?? undo.error ?? pick.error ?? remake.error)}</Alert></div>}
      <form className="mt-3 space-y-2 border-t border-slate-200 pt-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        {current && <div className="flex flex-wrap gap-1.5" aria-label="바로 고치기">
          {[["이 컷 짧게", "이 장면 짧게"], ["다른 장면으로", "다른 장면으로"], ["이 컷 빼기", `${current.number}번 빼`]].map(([label, text]) =>
            <button key={label} type="button" disabled={busy} onClick={() => quick(text)} className="h-8 rounded-full border border-slate-300 bg-white px-3 text-[13px] text-slate-700 hover:border-sky-400 disabled:opacity-50">{label}</button>)}
        </div>}
        <div className="flex min-w-0 items-center gap-2 rounded-lg border border-slate-300 bg-white px-2 focus-within:ring-2 focus-within:ring-sky-500">
          {stamp !== null && <span className="flex shrink-0 items-center gap-1 rounded-full border border-sky-300 px-2 py-0.5 text-xs tabular-nums text-sky-700">[{clock(stamp)}]<button type="button" aria-label="시각 떼기" onClick={() => setStamp(null)}><X size={12} /></button></span>}
          <input id="chat-edit-input" aria-label="고칠 내용" value={message} maxLength={400} disabled={busy} onChange={(event) => setMessage(event.target.value)}
            placeholder={stamp !== null ? "이 장면을 어떻게 고칠까요?" : "고칠 내용을 말해 줘요 (영상을 멈추면 시각이 붙어요)"}
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-slate-800 placeholder:text-slate-500 focus:outline-none" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" disabled={busy || !message.trim()}><span className="flex items-center gap-1">{send.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}고치기</span></Button>
          {data.brains.length > 0 && <label className="ml-auto flex items-center gap-1 text-xs text-slate-500">어려운 말 담당
            <select aria-label="편집 두뇌" value={brain ?? ""} onChange={(event) => setBrain(event.target.value)} className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs text-slate-700">
              {data.brains.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
            </select></label>}
        </div>
        <p className="text-[11px] text-slate-500">{data.brains.length === 0 ? "AI가 꺼져 있어 간단한 말만 알아들어요." : "간단한 말은 바로(무료), 나머지는 AI가 읽어요."}
          {claude && ` · Claude ${claude.calls}번 $${claude.usd.toFixed(4)} (약 ${Math.max(1, Math.round(claude.usd * WON_PER_USD))}원)`}{local && ` · 로컬 AI ${local.calls}번`}</p>
        {data.dropped > 0 && <p className="text-[11px] text-amber-700">분석이 바뀌어 없어진 장면 {data.dropped}개는 다음 고치기 때 편집안에서 빠져요.</p>}
      </form>
    </section>
    </div>
  </div>;
}

function CutStrip({ cuts, total, time, playing, changed, onPick }: { cuts: ChatCut[]; total: number; time: number; playing: number; changed: Set<string>; onPick: (index: number) => void }) {
  return <div className="relative py-1" aria-label="컷 띠">
    <div className="flex gap-[3px]">
      {cuts.map((cut, index) => <button key={cut.candidate_id} type="button" onClick={() => onPick(index)}
        title={`컷 ${cut.number} · ${cut.length.toFixed(1)}초 · ${cut.speech}`} aria-label={`컷 ${cut.number}, ${cut.length.toFixed(1)}초${changed.has(cut.candidate_id) ? ", 방금 고침" : ""}`}
        style={{ flexGrow: Math.max(cut.length, 0.5), flexBasis: 0 }}
        className={`h-10 min-w-[6px] overflow-hidden rounded-[4px] border text-[10px] tabular-nums ${changed.has(cut.candidate_id) ? "border-amber-500 bg-amber-100 text-amber-800" : "border-sky-200 bg-sky-100 text-sky-800"} ${index === playing ? "outline outline-2 outline-offset-1 outline-sky-600" : ""}`}>
        {cut.length >= 2 ? cut.number : ""}
      </button>)}
    </div>
    {total > 0 && <span aria-hidden className="pointer-events-none absolute bottom-0 top-0 w-0.5 bg-sky-300" style={{ left: `${Math.min(100, (time / total) * 100)}%` }} />}
  </div>;
}

function Bubble({ item, projectId, busy, onPick }: { item: ChatMessage; projectId: string; busy: boolean; onPick: (choice: number) => void }) {
  if (item.role === "user") {
    const stamp = item.text.match(/^\s*(\[\d{1,3}:\d{2}\])\s*/);
    return <div className={`ml-auto max-w-[92%] rounded-xl px-3 py-2 text-sm ${item.undone ? "bg-slate-50 text-slate-500" : "bg-sky-100 text-slate-800"}`}>
      {stamp && <b className={`mr-1 tabular-nums ${item.undone ? "" : "text-sky-700"}`}>{stamp[1]}</b>}<span className={item.undone ? "line-through" : ""}>{stamp ? item.text.slice(stamp[0].length) : item.text}</span>
      {item.undone && <span className="ml-2 text-[11px] text-slate-500">되돌림</span>}
    </div>;
  }
  const engine = engineLabel(item.engine);
  const choices = item.choices ?? [];
  const open = choices.length > 0 && (item.picked === null || item.picked === undefined);
  return <div className={`max-w-[95%] rounded-xl px-3 py-2 text-sm ${item.error ? "bg-amber-100 text-amber-700" : item.undone ? "bg-slate-50 text-slate-500" : "bg-slate-100 text-slate-700"}`}>
    <p className={item.no_change && !choices.length ? "text-amber-700" : ""}>{item.text}</p>
    {choices.length > 0 && <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3" aria-label={`${item.for_cut}번 컷 대신 넣을 장면`}>
      {choices.map((choice, index) => <button key={`${choice.candidate_id}-${choice.start_seconds}`} type="button" disabled={!open || busy} onClick={() => onPick(index)}
        className={`group overflow-hidden rounded-lg border text-left text-[11px] ${item.picked === index ? "border-sky-500 ring-2 ring-sky-500" : "border-slate-200"} ${open ? "hover:border-sky-500" : "opacity-50"}`}>
        <img src={thumbUrl(projectId, choice.source_video_id, (choice.start_seconds + choice.end_seconds) / 2)} alt={choice.label} loading="lazy" className="block aspect-video w-full bg-black object-cover" />
        <span className="block px-1.5 py-1 leading-tight text-slate-600">{choice.label}<span className="text-slate-500"> · {(choice.end_seconds - choice.start_seconds).toFixed(1)}초</span></span>
      </button>)}
    </div>}
    {open && <button type="button" disabled={busy} onClick={() => onPick(-1)} className="mt-1.5 rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:border-slate-400">그대로 두기</button>}
    {item.done.length > 0 && <div className="mt-1"><p className="text-[11px] text-slate-500">실제로 한 일</p><ul className="space-y-0.5">{item.done.map((line) => <li key={line} className={item.undone ? "text-slate-500 line-through" : "text-emerald-700"}>✓ {line}</li>)}</ul></div>}
    {item.skipped.length > 0 && <ul className="mt-1 space-y-0.5">{item.skipped.map((line) => <li key={line} className="text-amber-700">· {line}</li>)}</ul>}
    {engine && <p className="mt-1 text-[11px] text-slate-500">{engine}{item.undone ? " · 되돌림" : ""}</p>}
  </div>;
}
