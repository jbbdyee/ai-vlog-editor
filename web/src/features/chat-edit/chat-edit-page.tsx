import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Clapperboard, LoaderCircle, MoreHorizontal, Send, Undo2, X } from "lucide-react";
import { Link, useLocation, useParams } from "react-router-dom";
import { addEditRule, clock, cutAt, ensurePreviews, getChatEdit, getEditRules, pickChatChoice, previewUrl, remakeFromStoryDirection, sendChatEdit, startFromStoryDirection, thumbUrl, undoChatEdit, type ChatCut, type ChatEditView, type ChatMessage } from "@/api/chat-edit";
import { ApiError, getProject, isProjectId, sourceMediaUrl } from "@/api/projects";
import { startRendering } from "@/api/edit-render";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { EditRoomMenu } from "@/features/chat-edit/edit-room-menu";

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
  // TODO 37: with a plan, the edit room draws its own one-line top bar
  if (view.data && view.data.cuts.length > 0) return <Editor projectId={projectId} name={project.data?.name ?? "프로젝트"} data={view.data} />;
  return <div className="py-4 sm:py-6">
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
      <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-1.5 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={16} /> 홈</Link>
      <h1 className="text-xl font-bold tracking-[-.02em] text-slate-900 sm:text-2xl">{project.data?.name ?? "프로젝트"} · 편집실</h1>
      <span className="text-xs text-slate-500">고치면 바로 저장돼요</span>
    </div>
    {view.isPending && <p className="mt-6 text-sm text-slate-500">편집안을 불러오는 중…</p>}
    {view.isError && <div className="mt-6"><Alert>{errorText(view.error)}</Alert></div>}
    {view.data && <NoPlan projectId={projectId} onDone={() => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] })} />}
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

function Editor({ projectId, name, data }: { projectId: string; name: string; data: ChatEditView }) {
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
  const [olderOpen, setOlderOpen] = useState(false);
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

  // A cut that runs to the very end of its source can reach the file's end before the check above:
  // the browser then stops by itself (paused), so move on here (학원 하루 컷 1·6·62 used to stop).
  function onEnded() {
    if (pending.current) return;
    if (playing < cuts.length - 1) goTo(playing + 1, 0, true);
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
  // TODO 27: sentences saved as rules, shared by every project (the chips themselves live in the ⋯ menu)
  const rules = useQuery({ queryKey: ["edit-rules"], queryFn: getEditRules });
  const addRule = useMutation({ mutationFn: addEditRule, onSuccess: (value) => client.setQueryData(["edit-rules"], value) });
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
  const [menuOpen, setMenuOpen] = useState(openTaste);

  // TODO 37: only the latest exchange (my last message and the answers after it) stays on screen
  const lastUser = data.messages.map((item) => item.role).lastIndexOf("user");
  // (a run of answers with no message of mine, e.g. many remakes, shows just the newest one)
  const split = lastUser >= 0 && data.messages.length - lastUser <= 3 ? lastUser : Math.max(0, data.messages.length - 1);
  const older = data.messages.slice(0, split);
  const recent = data.messages.slice(split);

  const current = cuts[playing];
  const previewDone = previews.data ? previews.data.ready.length + previews.data.failed.length >= previews.data.total : true;
  const previewStatus = previews.data && previews.data.total > 0
    ? `휴대폰용 미리보기 ${previewDone ? "준비됨" : "만드는 중"} ${previews.data.ready.length}/${previews.data.total}${previews.data.failed.length ? ` · 못 만든 영상 ${previews.data.failed.length}개` : ""}`
    : null;

  const showMessage = (item: ChatMessage, index: number) => <div key={item.id ?? index} className={item.role === "user" ? "flex flex-col items-end gap-0.5" : ""}>
    <Bubble item={item} projectId={projectId} busy={busy} onPick={(choice) => item.id && pick.mutate({ messageId: item.id, choice })} />
    {item.role === "user" && (ruleTexts.has(plain(item.text))
      ? <span className="text-[11px] text-sky-700">규칙으로 저장됨</span>
      : <button type="button" disabled={addRule.isPending} onClick={() => addRule.mutate(item.text)} className="text-[11px] text-slate-500 hover:text-sky-700">규칙으로 저장</button>)}
  </div>;

  return <div className="pb-4">
    <header className="sticky top-0 z-30 -mx-4 flex items-center gap-1.5 border-b border-slate-200 bg-white/95 px-3 py-2 backdrop-blur sm:mx-0 sm:mt-3 sm:rounded-2xl sm:border">
      <Link to={`/projects/${projectId}`} aria-label="홈" className="rounded-full p-2 text-slate-600 hover:bg-slate-100"><ArrowLeft size={20} /></Link>
      <div className="min-w-0 flex-1 leading-tight">
        <h1 className="truncate text-[15px] font-bold text-slate-900 sm:text-base">{name}</h1>
        <p className="text-xs tabular-nums text-slate-500">{clock(total)} · 컷 {cuts.length}개</p>
      </div>
      <button type="button" aria-label={data.undo_count > 0 ? `되돌리기 (${data.undo_count})` : "되돌리기"} title="되돌리기" disabled={busy || data.undo_count === 0} onClick={() => undo.mutate()}
        className="relative rounded-full p-2 text-slate-600 hover:bg-slate-100 disabled:opacity-40">
        <Undo2 size={20} />{data.undo_count > 0 && <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-sky-600 px-1 text-[10px] font-bold leading-4 text-white">{data.undo_count}</span>}
      </button>
      <button type="button" aria-label="더 보기" title="더 보기" onClick={() => setMenuOpen(true)} className="relative rounded-full p-2 text-slate-600 hover:bg-slate-100">
        <MoreHorizontal size={20} />{candidates.length > 0 && <span aria-label="새 규칙 후보" className="absolute right-1 top-1 h-2 w-2 rounded-full bg-sky-600" />}
      </button>
      <Button type="button" size="sm" disabled={render.isPending || render.isSuccess} onClick={() => render.mutate()}>{render.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Clapperboard size={16} />}영상 만들기</Button>
    </header>
    {render.isSuccess && <p role="status" className="mt-2 text-sm text-sky-700">4K 영상을 만들기 시작했어요. 홈에서 확인해요.</p>}
    {render.error && <p className="mt-2 text-sm text-rose-700">{errorText(render.error)}</p>}

    <div className="mt-3 grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
    <section aria-label="편집안 미리보기" className="min-w-0 space-y-2">
      <div className="relative">
        <video ref={video} aria-label="편집안 재생" className="block aspect-video w-full rounded-xl bg-black" controls playsInline preload="metadata"
          onLoadedMetadata={onLoaded} onTimeUpdate={onTime} onPlay={onPlay} onEnded={onEnded}
          onPause={() => setStamp(timeRef.current)}
          onSeeked={() => { const player = video.current; const cut = cuts[playing]; if (player?.paused && cut && !pending.current) setStamp(cut.timeline_start + Math.min(Math.max(player.currentTime - cut.start_seconds, 0), cut.length)); }}
          onError={() => setPlayError(current && !ready.has(current.source_video_id)
            ? "이 영상의 휴대폰용 미리보기를 아직 만드는 중이에요. 다 되면 바로 틀 수 있어요."
            : "영상을 재생할 수 없어요. 서버 연결을 확인해 주세요.")} />
      </div>
      <div className="flex items-center gap-2 text-xs tabular-nums text-slate-500">
        <span aria-label="편집 속 시각">{clock(time)} / {clock(total)}</span>
        <span className="h-1 flex-1 overflow-hidden rounded-full bg-slate-200"><span className="block h-full bg-sky-500" style={{ width: `${total > 0 ? Math.min(100, (time / total) * 100) : 0}%` }} /></span>
        {marked.size > 0 && <span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-amber-500 bg-amber-100 align-[-1px]" />방금 고친 컷</span>}
      </div>
      {!previewDone && previewStatus && <p className="text-xs text-slate-500">{previewStatus}</p>}
      {playError && <Alert>{playError}</Alert>}
      <CutStrip projectId={projectId} cuts={cuts} playing={playing} changed={marked} onPick={(index) => { video.current?.pause(); goTo(index, 0, false); setStamp(cuts[index].timeline_start); }} />
    </section>

    <section aria-label="대화창" className="flex min-w-0 flex-col gap-2 lg:sticky lg:top-20 lg:max-h-[calc(100vh-11rem)] lg:rounded-2xl lg:border lg:border-slate-200 lg:bg-white lg:p-3">
      {current && <div className="rounded-xl bg-slate-50 px-3 py-2 text-sm">
        <p className="font-semibold text-slate-800">컷 {current.number} · {current.length.toFixed(1)}초 <span className="font-normal text-xs text-slate-500">{current.source_filename} {current.start_seconds.toFixed(1)}–{current.end_seconds.toFixed(1)}초</span></p>
        <p className="mt-0.5 line-clamp-2 text-slate-600">{current.speech}</p>
      </div>}
      <div ref={list} className="min-h-0 flex-1 space-y-2 overflow-y-auto" aria-live="polite">
        {older.length > 0 && <button type="button" aria-expanded={olderOpen} onClick={() => setOlderOpen(!olderOpen)} className="text-xs text-slate-500 hover:text-sky-700">{olderOpen ? "지난 대화 접기" : `지난 대화 ${older.length}개 보기`}</button>}
        {olderOpen && <div className="space-y-2 opacity-80">{older.map(showMessage)}</div>}
        {data.messages.length === 0 && <p className="text-sm text-slate-500">아래 장면 그림을 눌러 컷을 고르고, 고칠 점을 말해 줘요.</p>}
        {recent.map((item, index) => showMessage(item, split + index))}
        {send.isPending && <p className="flex items-center gap-2 text-sm text-slate-500"><LoaderCircle size={14} className="animate-spin" />고치는 중…</p>}
      </div>
      {(send.error || undo.error || pick.error || remake.error || addRule.error) && <Alert>{errorText(send.error ?? undo.error ?? pick.error ?? remake.error ?? addRule.error)}</Alert>}
      <form className="sticky bottom-0 z-20 -mx-4 space-y-2 border-t border-slate-200 bg-white/95 px-4 pb-[max(.75rem,env(safe-area-inset-bottom))] pt-2 backdrop-blur lg:static lg:mx-0 lg:bg-transparent lg:px-0 lg:pb-0" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        {current && <div className="flex gap-1.5 overflow-x-auto" aria-label="바로 고치기">
          {[["이 컷 짧게", "이 장면 짧게"], ["다른 장면으로", "다른 장면으로"], ["이 컷 빼기", `${current.number}번 빼`]].map(([label, text]) =>
            <button key={label} type="button" disabled={busy} onClick={() => quick(text)} className="h-8 shrink-0 rounded-full border border-slate-300 bg-white px-3 text-[13px] text-slate-700 hover:border-sky-400 disabled:opacity-50">{label}</button>)}
        </div>}
        <div className="flex min-w-0 items-center gap-2 rounded-full border border-slate-300 bg-white pl-3 pr-1 focus-within:ring-2 focus-within:ring-sky-500">
          {stamp !== null && <span className="flex shrink-0 items-center gap-1 rounded-full border border-sky-300 px-2 py-0.5 text-xs tabular-nums text-sky-700">[{clock(stamp)}]<button type="button" aria-label="시각 떼기" onClick={() => setStamp(null)}><X size={12} /></button></span>}
          <input id="chat-edit-input" aria-label="고칠 내용" value={message} maxLength={400} disabled={busy} onChange={(event) => setMessage(event.target.value)}
            placeholder={stamp !== null ? "이 장면을 어떻게 고칠까요?" : "고칠 점을 말해 줘요"}
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-slate-800 placeholder:text-slate-500 focus:outline-none" />
          <button type="submit" aria-label="고치기" disabled={busy || !message.trim()} className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-40">
            {send.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <Send size={16} />}
          </button>
        </div>
        {data.dropped > 0 && <p className="text-[11px] text-amber-700">분석이 바뀌어 없어진 장면 {data.dropped}개는 다음 고치기 때 편집안에서 빠져요.</p>}
      </form>
    </section>
    </div>
    {menuOpen && <EditRoomMenu projectId={projectId} data={data} busy={busy} brain={brain} onBrain={setBrain}
      remakeMinutes={remakeMinutes} onRemakeMinutes={setRemakeMinutes} onRemake={() => remake.mutate()} remaking={remake.isPending}
      previewStatus={previewStatus} openTaste={openTaste} onClose={() => setMenuOpen(false)} />}
  </div>;
}

/** TODO 37: the cuts as a row of scene pictures (it scrolls sideways and keeps the cut on screen in view). */
function CutStrip({ projectId, cuts, playing, changed, onPick }: { projectId: string; cuts: ChatCut[]; playing: number; changed: Set<string>; onPick: (index: number) => void }) {
  const strip = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const box = strip.current;
    const item = box?.querySelector<HTMLElement>(`[data-cut-index="${playing}"]`);
    if (box && item) box.scrollTo?.({ left: item.offsetLeft - box.clientWidth / 2 + item.clientWidth / 2, behavior: "smooth" });
  }, [playing]);
  return <div ref={strip} className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 sm:mx-0 sm:px-0" aria-label="컷 띠">
    {cuts.map((cut, index) => <button key={cut.candidate_id} type="button" data-cut-index={index} onClick={() => onPick(index)}
      title={`컷 ${cut.number} · ${cut.length.toFixed(1)}초 · ${cut.speech}`} aria-label={`컷 ${cut.number}, ${cut.length.toFixed(1)}초${cut.zoom ? (cut.zoom === "push" ? ", 천천히 줌" : ", 확대") : ""}${cut.texts?.length ? `, 글자 ${cut.texts.join(" ")}` : ""}${changed.has(cut.candidate_id) ? ", 방금 고침" : ""}`}
      className={`relative w-[84px] shrink-0 overflow-hidden rounded-lg border-2 sm:w-24 ${index === playing ? "border-sky-600" : changed.has(cut.candidate_id) ? "border-amber-500" : "border-transparent"}`}>
      <img src={thumbUrl(projectId, cut.source_video_id, (cut.start_seconds + cut.end_seconds) / 2)} alt="" loading="lazy" className="block aspect-video w-full bg-slate-200 object-cover" />
      <span className="absolute left-1 top-1 rounded bg-black/60 px-1 text-[10px] font-bold tabular-nums text-white">{cut.number}</span>
      <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1 text-[10px] tabular-nums text-white">{cut.length.toFixed(1)}초</span>
      {cut.zoom && <span className="absolute right-1 top-1 rounded bg-sky-600/90 px-1 text-[10px] font-bold text-white" title="완성 영상에 들어가는 효과">🔍 {cut.zoom === "push" ? "줌" : "확대"}</span>}
      {cut.texts && cut.texts.length > 0 && <span className="absolute bottom-1 left-1 max-w-[60%] truncate rounded bg-amber-400/95 px-1 text-[10px] font-bold text-slate-900" title={`완성 영상에 들어가는 글자: ${cut.texts.join(" · ")}`}>💬 {cut.texts[0]}{cut.texts.length > 1 ? ` +${cut.texts.length - 1}` : ""}</span>}
    </button>)}
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
