import { useEffect, useMemo, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, LoaderCircle, Send, Undo2, X } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { addEditRule, answerRuleCandidate, clock, cutAt, deleteEditRule, getChatEdit, getEditRules, pickChatChoice, sendChatEdit, startFromStoryDirection, thumbUrl, undoChatEdit, type ChatCut, type ChatEditView, type ChatMessage } from "@/api/chat-edit";
import { ApiError, getProject, isProjectId, sourceMediaUrl } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { MyEditCard } from "@/features/chat-edit/my-edit-card";

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
  return <div className="py-5 sm:py-8">
    <Link to={`/projects/${projectId}`} className="inline-flex items-center gap-2 text-sm text-slate-400 hover:text-white"><ArrowLeft size={16} /> 프로젝트로 돌아가기</Link>
    <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
      <div><p className="text-xs font-semibold uppercase tracking-[.2em] text-cyan-300">대화형 편집</p><h1 className="mt-1 text-2xl font-semibold tracking-[-.03em] text-white sm:text-3xl">{project.data?.name ?? "프로젝트"}</h1></div>
      <p className="text-xs text-slate-400">고친 편집안은 바로 저장돼요. 영상 파일은 프로젝트 화면의 &lsquo;최종 영상 렌더링&rsquo;에서 다시 만들어요.</p>
    </div>
    {view.isPending && <p className="mt-6 text-sm text-slate-400">편집안을 불러오는 중…</p>}
    {view.isError && <div className="mt-6"><Alert>{errorText(view.error)}</Alert></div>}
    {view.data && (view.data.cuts.length === 0
      ? <NoPlan projectId={projectId} onDone={() => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] })} />
      : <Editor projectId={projectId} data={view.data} />)}
  </div>;
}

function NoPlan({ projectId, onDone }: { projectId: string; onDone: () => void }) {
  const start = useMutation({ mutationFn: () => startFromStoryDirection(projectId), onSuccess: onDone });
  return <div className="mt-6 max-w-xl space-y-3 rounded-2xl border border-white/10 bg-white/[.03] p-5">
    <p className="text-sm text-slate-200">아직 저장된 편집안이 없어요. 추천 편집 방향(&lsquo;오늘 있었던 일&rsquo;을 적었다면 그 설명대로)으로 첫 편집안을 만들고 여기서 고쳐요.</p>
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

  function goTo(index: number, offset: number, play: boolean) {
    const player = video.current;
    const cut = cuts[index];
    if (!player || !cut) return;
    setPlaying(index);
    setTime(cut.timeline_start + offset);
    const src = sourceMediaUrl(projectId, cut.source_video_id);
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
  const pick = useMutation({
    mutationFn: ({ messageId, choice }: { messageId: string; choice: number }) => pickChatChoice(projectId, messageId, choice),
    onSuccess: refresh,
    onError: () => void client.invalidateQueries({ queryKey: ["chat-edit", projectId] }),
  });
  const busy = send.isPending || undo.isPending || pick.isPending;
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

  const claude = data.usage.find((item) => item.key === "claude");
  const local = data.usage.find((item) => item.key === "ollama");
  const current = cuts[playing];

  return <div className="mt-5 grid min-w-0 gap-4 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)]">
    <section aria-label="편집안 미리보기" className="min-w-0 space-y-3">
      <div className="relative">
        <video ref={video} aria-label="편집안 재생" className="block aspect-video w-full rounded-xl bg-black" controls playsInline preload="metadata"
          onLoadedMetadata={onLoaded} onTimeUpdate={onTime} onPlay={onPlay}
          onPause={() => setStamp(timeRef.current)}
          onSeeked={() => { const player = video.current; const cut = cuts[playing]; if (player?.paused && cut && !pending.current) setStamp(cut.timeline_start + Math.min(Math.max(player.currentTime - cut.start_seconds, 0), cut.length)); }}
          onError={() => setPlayError("영상을 재생할 수 없어요. 서버 연결을 확인해 주세요.")} />
        {current && <span className="pointer-events-none absolute right-2 top-2 rounded bg-black/60 px-2 py-0.5 text-xs text-white">컷 {current.number} · {current.source_filename}</span>}
      </div>
      <p className="flex flex-wrap justify-between gap-2 text-sm tabular-nums text-slate-300"><span aria-label="편집 속 시각">{clock(time)} / {clock(total)}</span><span className="text-slate-500">컷 {cuts.length}개 · 안 쓴 장면 {data.unused.length}개</span></p>
      {playError && <Alert>{playError}</Alert>}
      <CutStrip cuts={cuts} total={total} time={time} playing={playing} changed={changed} onPick={(index) => { video.current?.pause(); goTo(index, 0, false); setStamp(cuts[index].timeline_start); }} />
      <p className="flex flex-wrap gap-4 text-xs text-slate-500"><span><i className="mr-1 inline-block h-2.5 w-2.5 rounded-sm border border-fuchsia-300 bg-fuchsia-300/30 align-[-1px]" />방금 고친 컷</span><span>칸 너비 = 컷 길이 · 누르면 그 컷으로</span></p>
      {current && <div className="rounded-xl border border-white/10 bg-white/[.03] p-3 text-sm">
        <p className="font-semibold text-slate-100">컷 {current.number} · {current.length.toFixed(1)}초 <span className="font-normal text-slate-500">({current.source_filename} {current.start_seconds.toFixed(1)}–{current.end_seconds.toFixed(1)}초)</span></p>
        <p className="mt-1 text-slate-300">{current.speech}</p>
        {current.caption && <p className="mt-1 text-xs text-slate-500">화면: {current.caption}</p>}
      </div>}
      {data.unused.length > 0 && <details className="rounded-xl border border-white/10 p-3 text-sm">
        <summary className="cursor-pointer text-slate-200">안 쓴 장면 {data.unused.length}개 <span className="text-xs text-slate-500">· "안 쓴 장면 2 넣어 줘"처럼 말하면 들어가요</span></summary>
        <ol className="mt-2 space-y-1 text-xs text-slate-400">{data.unused.map((scene) => <li key={scene.candidate_id}><b className="text-slate-200">장면 {scene.number}</b> · {scene.source_filename} · {(scene.end_seconds - scene.start_seconds).toFixed(1)}초 · {scene.speech}</li>)}</ol>
      </details>}
      <MyEditCard projectId={projectId} />
    </section>

    <section aria-label="대화창" className="flex min-w-0 flex-col rounded-2xl border border-white/10 bg-white/[.03] p-3 lg:max-h-[calc(100vh-7rem)] lg:sticky lg:top-3">
      <div className="mb-2 flex flex-wrap items-center gap-1.5 border-b border-white/10 pb-2" aria-label="내 규칙">
        <span className="text-xs text-slate-400">내 규칙</span>
        {(rules.data ?? []).map((rule) => <span key={rule.id} className="flex items-center gap-1 rounded-full border border-fuchsia-300/60 px-2 py-0.5 text-xs text-fuchsia-100">
          {rule.text}<button type="button" aria-label={`규칙 지우기: ${rule.text}`} disabled={removeRule.isPending} onClick={() => removeRule.mutate(rule.id)}><X size={12} /></button>
        </span>)}
        {rules.data?.length === 0 && <span className="text-[11px] text-slate-500">아직 없어요 · 마음에 든 내 말 아래 [규칙으로 저장]을 누르면 모든 프로젝트의 다음 편집안에 반영돼요</span>}
      </div>
      {candidates.length > 0 && <div className="mb-2 space-y-1.5" aria-label="규칙 후보">
        {candidates.map((item) => <div key={item.key} className="rounded-lg border border-dashed border-cyan-300/60 bg-cyan-300/[.06] px-3 py-2 text-sm">
          <p className="text-[11px] text-cyan-200">규칙 후보 · {item.key.startsWith("my_edit") || item.why.includes("내 편집본") ? "내 편집본과 비교해서 찾음" : "내 선택 기록에서 찾음"}</p>
          <p className="mt-0.5 font-semibold text-slate-100">{item.text}</p>
          <p className="mt-0.5 text-xs text-slate-400">근거: {item.why}</p>
          <div className="mt-1.5 flex gap-2">
            <Button type="button" size="sm" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: true })}>규칙으로</Button>
            <Button type="button" size="sm" variant="secondary" disabled={answer.isPending} onClick={() => answer.mutate({ key: item.key, accept: false })}>아니야</Button>
          </div>
        </div>)}
      </div>}
      {(addRule.error || removeRule.error || answer.error) && <div className="mb-2"><Alert>{errorText(addRule.error ?? removeRule.error ?? answer.error)}</Alert></div>}
      <div ref={list} className="min-h-40 flex-1 space-y-2 overflow-y-auto pr-1" aria-live="polite">
        {data.messages.length === 0 && <div className="space-y-1 text-sm text-slate-400"><p>영상을 멈추고 고칠 점을 말해 줘요. 멈춘 시각이 앞에 붙어요.</p><p className="text-xs text-slate-500">예: 이 장면 짧게 · 다른 장면으로 · 여기서 끝내 · 3번 빼 · 3번이랑 4번 바꿔 · 안 쓴 장면 2 맨 끝에 넣어 · 다른 사람이 말하는 컷 줄여</p></div>}
        {data.messages.map((item, index) => <div key={item.id ?? index} className={item.role === "user" ? "flex flex-col items-end gap-0.5" : ""}>
          <Bubble item={item} projectId={projectId} busy={busy} onPick={(choice) => item.id && pick.mutate({ messageId: item.id, choice })} />
          {item.role === "user" && (ruleTexts.has(plain(item.text))
            ? <span className="text-[11px] text-fuchsia-200">규칙으로 저장됨</span>
            : <button type="button" disabled={addRule.isPending} onClick={() => addRule.mutate(item.text)} className="text-[11px] text-slate-500 hover:text-fuchsia-200">규칙으로 저장</button>)}
        </div>)}
        {send.isPending && <p className="flex items-center gap-2 text-sm text-slate-400"><LoaderCircle size={14} className="animate-spin" />고치는 중…</p>}
      </div>
      {(send.error || undo.error || pick.error) && <div className="mt-2"><Alert>{errorText(send.error ?? undo.error ?? pick.error)}</Alert></div>}
      <form className="mt-3 space-y-2 border-t border-white/10 pt-3" onSubmit={(event) => { event.preventDefault(); submit(); }}>
        <div className="flex min-w-0 items-center gap-2 rounded-lg border border-white/15 bg-[#0b1420] px-2 focus-within:ring-2 focus-within:ring-cyan-300">
          {stamp !== null && <span className="flex shrink-0 items-center gap-1 rounded-full border border-fuchsia-300/60 px-2 py-0.5 text-xs tabular-nums text-fuchsia-200">[{clock(stamp)}]<button type="button" aria-label="시각 떼기" onClick={() => setStamp(null)}><X size={12} /></button></span>}
          <input id="chat-edit-input" aria-label="고칠 내용" value={message} maxLength={400} disabled={busy} onChange={(event) => setMessage(event.target.value)}
            placeholder={stamp !== null ? "이 장면을 어떻게 고칠까요?" : "고칠 내용을 말해 줘요 (영상을 멈추면 시각이 붙어요)"}
            className="min-w-0 flex-1 bg-transparent py-2 text-sm text-slate-100 placeholder:text-slate-500 focus:outline-none" />
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button type="submit" size="sm" disabled={busy || !message.trim()}><span className="flex items-center gap-1">{send.isPending ? <LoaderCircle size={14} className="animate-spin" /> : <Send size={14} />}고치기</span></Button>
          <Button type="button" size="sm" variant="secondary" disabled={busy || data.undo_count === 0} onClick={() => undo.mutate()}><span className="flex items-center gap-1"><Undo2 size={14} />되돌리기{data.undo_count > 0 ? ` (${data.undo_count})` : ""}</span></Button>
          {data.brains.length > 0 && <label className="ml-auto flex items-center gap-1 text-xs text-slate-400">어려운 말 담당
            <select aria-label="편집 두뇌" value={brain ?? ""} onChange={(event) => setBrain(event.target.value)} className="rounded border border-white/15 bg-[#0b1420] px-1 py-0.5 text-xs text-slate-200">
              {data.brains.map((item) => <option key={item.key} value={item.key}>{item.label}</option>)}
            </select></label>}
        </div>
        <p className="text-[11px] text-slate-500">{data.brains.length === 0 ? "편집 두뇌(AI)가 꺼져 있어 규칙으로 읽는 말만 돼요." : "\"3번 빼\" 같은 말은 규칙으로 바로(무료), 나머지는 고른 AI가 읽어요."}
          {claude && ` · Claude ${claude.calls}번 $${claude.usd.toFixed(4)} (약 ${Math.max(1, Math.round(claude.usd * WON_PER_USD))}원)`}{local && ` · 로컬 AI ${local.calls}번`}</p>
        {data.dropped > 0 && <p className="text-[11px] text-amber-200">분석이 바뀌어 없어진 장면 {data.dropped}개는 다음 고치기 때 편집안에서 빠져요.</p>}
      </form>
    </section>
  </div>;
}

function CutStrip({ cuts, total, time, playing, changed, onPick }: { cuts: ChatCut[]; total: number; time: number; playing: number; changed: Set<string>; onPick: (index: number) => void }) {
  return <div className="relative py-1" aria-label="컷 띠">
    <div className="flex gap-[3px]">
      {cuts.map((cut, index) => <button key={cut.candidate_id} type="button" onClick={() => onPick(index)}
        title={`컷 ${cut.number} · ${cut.length.toFixed(1)}초 · ${cut.speech}`} aria-label={`컷 ${cut.number}, ${cut.length.toFixed(1)}초${changed.has(cut.candidate_id) ? ", 방금 고침" : ""}`}
        style={{ flexGrow: Math.max(cut.length, 0.5), flexBasis: 0 }}
        className={`h-10 min-w-[6px] overflow-hidden rounded-[4px] border text-[10px] tabular-nums ${changed.has(cut.candidate_id) ? "border-fuchsia-300 bg-fuchsia-300/25 text-fuchsia-100" : "border-white/10 bg-white/[.06] text-slate-400"} ${index === playing ? "outline outline-2 outline-offset-1 outline-white" : ""}`}>
        {cut.length >= 2 ? cut.number : ""}
      </button>)}
    </div>
    {total > 0 && <span aria-hidden className="pointer-events-none absolute bottom-0 top-0 w-0.5 bg-fuchsia-300" style={{ left: `${Math.min(100, (time / total) * 100)}%` }} />}
  </div>;
}

function Bubble({ item, projectId, busy, onPick }: { item: ChatMessage; projectId: string; busy: boolean; onPick: (choice: number) => void }) {
  if (item.role === "user") {
    const stamp = item.text.match(/^\s*(\[\d{1,3}:\d{2}\])\s*/);
    return <div className={`ml-auto max-w-[92%] rounded-xl px-3 py-2 text-sm ${item.undone ? "bg-white/[.04] text-slate-500" : "bg-fuchsia-300/15 text-slate-100"}`}>
      {stamp && <b className={`mr-1 tabular-nums ${item.undone ? "" : "text-fuchsia-200"}`}>{stamp[1]}</b>}<span className={item.undone ? "line-through" : ""}>{stamp ? item.text.slice(stamp[0].length) : item.text}</span>
      {item.undone && <span className="ml-2 text-[11px] text-slate-500">되돌림</span>}
    </div>;
  }
  const engine = engineLabel(item.engine);
  const choices = item.choices ?? [];
  const open = choices.length > 0 && (item.picked === null || item.picked === undefined);
  return <div className={`max-w-[95%] rounded-xl px-3 py-2 text-sm ${item.error ? "bg-amber-300/10 text-amber-100" : item.undone ? "bg-white/[.03] text-slate-500" : "bg-white/[.06] text-slate-200"}`}>
    <p className={item.no_change && !choices.length ? "text-amber-100" : ""}>{item.text}</p>
    {choices.length > 0 && <div className="mt-2 grid grid-cols-2 gap-1.5 sm:grid-cols-3" aria-label={`${item.for_cut}번 컷 대신 넣을 장면`}>
      {choices.map((choice, index) => <button key={`${choice.candidate_id}-${choice.start_seconds}`} type="button" disabled={!open || busy} onClick={() => onPick(index)}
        className={`group overflow-hidden rounded-lg border text-left text-[11px] ${item.picked === index ? "border-fuchsia-300 ring-2 ring-fuchsia-300" : "border-white/10"} ${open ? "hover:border-cyan-300" : "opacity-50"}`}>
        <img src={thumbUrl(projectId, choice.source_video_id, (choice.start_seconds + choice.end_seconds) / 2)} alt={choice.label} loading="lazy" className="block aspect-video w-full bg-black object-cover" />
        <span className="block px-1.5 py-1 leading-tight text-slate-300">{choice.label}<span className="text-slate-500"> · {(choice.end_seconds - choice.start_seconds).toFixed(1)}초</span></span>
      </button>)}
    </div>}
    {open && <button type="button" disabled={busy} onClick={() => onPick(-1)} className="mt-1.5 rounded border border-white/15 px-2 py-0.5 text-xs text-slate-300 hover:border-white/40">그대로 두기</button>}
    {item.done.length > 0 && <div className="mt-1"><p className="text-[11px] text-slate-500">실제로 한 일</p><ul className="space-y-0.5">{item.done.map((line) => <li key={line} className={item.undone ? "text-slate-500 line-through" : "text-emerald-200"}>✓ {line}</li>)}</ul></div>}
    {item.skipped.length > 0 && <ul className="mt-1 space-y-0.5">{item.skipped.map((line) => <li key={line} className="text-amber-200">· {line}</li>)}</ul>}
    {engine && <p className="mt-1 text-[11px] text-slate-500">{engine}{item.undone ? " · 되돌림" : ""}</p>}
  </div>;
}
