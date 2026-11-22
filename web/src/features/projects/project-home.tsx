import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, ChevronDown, Circle, LoaderCircle } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { getProcessing, getProject, isProjectId } from "@/api/projects";
import { clock, getChatEdit, getTasteScores, thumbUrl } from "@/api/chat-edit";
import { getDayBrief } from "@/api/story-direction";
import { getRendering } from "@/api/edit-render";
import { getReelStatus } from "@/api/reels";
import { Alert } from "@/components/ui/alert";

/** TODO 37: the project home. A cover picture, one big button into the edit room, three check lines; the rest behind "더 보기". */
export function ProjectHome() {
  const { projectId = "" } = useParams();
  const valid = isProjectId(projectId);
  const on = { enabled: valid };
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => getProject(projectId), ...on });
  const sources = useQuery({ queryKey: ["processing", projectId], queryFn: () => getProcessing(projectId), ...on });
  const brief = useQuery({ queryKey: ["day-brief", projectId], queryFn: () => getDayBrief(projectId), ...on });
  const plan = useQuery({ queryKey: ["chat-edit", projectId], queryFn: () => getChatEdit(projectId), ...on });
  const taste = useQuery({ queryKey: ["taste-scores", projectId], queryFn: () => getTasteScores(projectId), ...on });
  const render = useQuery({ queryKey: ["rendering", projectId], queryFn: () => getRendering(projectId), ...on });
  const reel = useQuery({ queryKey: ["reel-draft", projectId], queryFn: () => getReelStatus(projectId), ...on });
  const [more, setMore] = useState(false);

  if (!valid) return <div className="mx-auto max-w-2xl py-24"><Alert>올바른 프로젝트 주소가 아니에요.</Alert></div>;
  const tools = `/projects/${projectId}/tools`;
  const editRoom = `/projects/${projectId}/chat-edit`;
  const cuts = plan.data?.cuts ?? [];
  const total = plan.data?.total_seconds ?? 0;
  const counts = taste.data?.counts ?? {};
  const made = render.data?.status === "COMPLETED" && render.data.output;
  const running = render.data?.is_active;
  const cover = cuts[0];

  return <div className="py-4 sm:py-8">
    <Link to="/" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={16} /> 프로젝트 목록</Link>
    <div className="mt-3 grid gap-5 lg:mt-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:items-center lg:gap-10">
      <div className="aspect-video overflow-hidden rounded-2xl bg-slate-200">
        {cover && <img src={thumbUrl(projectId, cover.source_video_id, (cover.start_seconds + cover.end_seconds) / 2)} alt="대표 장면" className="h-full w-full object-cover" />}
      </div>

      <div className="flex min-w-0 flex-col gap-4">
        <div>
          <h1 className="break-words text-2xl font-bold tracking-[-.03em] text-slate-900 sm:text-3xl">{project.data?.name ?? "프로젝트"}</h1>
          <p className="mt-1 text-sm text-slate-500">
            {project.data && new Date(project.data.created_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}
            {cuts.length > 0 ? ` · 편집안 ${clock(total)} 준비됨` : plan.data ? " · 아직 편집안이 없어요" : ""}
          </p>
        </div>

        <Link to={editRoom} className="inline-flex h-14 items-center justify-center gap-2 rounded-2xl bg-sky-600 px-6 text-base font-bold text-white hover:bg-sky-700">
          {cuts.length > 0 ? "편집 이어하기" : "편집 시작하기"} <ArrowRight size={20} />
        </Link>

        <ul aria-label="진행 상황" className="space-y-2 text-[15px]">
          <Step done={!!sources.data && sources.data.total_sources > 0}>
            원본 {sources.data ? `${sources.data.total_sources}개` : "…"}
            {sources.data && <Note> · 분석 끝 {sources.data.completed_count}{sources.data.failed_count > 0 && ` · 읽지 못함 ${sources.data.failed_count}`}</Note>}
          </Step>
          <Step done={cuts.length > 0}>
            편집안 {cuts.length > 0 ? clock(total) : "아직 없음"}{cuts.length > 0 && <Note> · 컷 {cuts.length}개</Note>}
          </Step>
          <Step done={!!made} busy={!!running}>
            완성 영상 {running ? "만드는 중" : made ? clock(made.duration_seconds) : "아직 없음"}
            {made && !running && <Note> · {Math.round(made.file_size_bytes / 1024 / 1024)}MB</Note>}
          </Step>
        </ul>

        <div>
          <button type="button" aria-expanded={more} onClick={() => setMore(!more)} className="inline-flex items-center gap-1 text-sm text-slate-500 hover:text-sky-700">
            더 보기 <ChevronDown size={16} className={more ? "rotate-180" : ""} />
          </button>
          {more && <nav aria-label="더 보기" className="mt-2 divide-y divide-slate-100 overflow-hidden rounded-2xl border border-slate-200 bg-white">
            <MoreLink to={`${tools}#upload`} label="영상 더 넣기" />
            <MoreLink to={`${tools}#story-direction`} label="오늘 있었던 일" note={brief.data || "아직 안 적었어요"} />
            <MoreLink to={`${editRoom}#taste-brief`} label="내 취향" note={taste.data ? `꼭 남김 ${counts["3"] ?? 0} · 좋음 ${counts["2"] ?? 0} · 빼도 됨 ${counts["1"] ?? 0} · 빼야 함 ${counts["0"] ?? 0}` : undefined} />
            <MoreLink to={`${tools}#edit-render`} label={made ? "완성 영상 내려받기 · 다시 만들기" : "완성 영상"} />
            <MoreLink to={`${tools}#reel-draft`} label={reel.data?.draft ? "릴스 열기" : "릴스 만들기"} />
            <MoreLink to={tools} label="모든 도구" />
          </nav>}
        </div>
      </div>
    </div>
  </div>;
}

function Step({ done, busy = false, children }: { done: boolean; busy?: boolean; children: ReactNode }) {
  return <li className={`flex items-center gap-2 ${done || busy ? "text-slate-800" : "text-slate-500"}`}>
    {busy ? <LoaderCircle size={18} className="shrink-0 animate-spin text-sky-600" />
      : done ? <Check size={18} className="shrink-0 text-sky-600" /> : <Circle size={18} className="shrink-0 text-slate-300" />}
    <span className="min-w-0">{children}</span>
  </li>;
}

const Note = ({ children }: { children: ReactNode }) => <span className="text-sm text-slate-500">{children}</span>;

function MoreLink({ to, label, note }: { to: string; label: string; note?: string }) {
  return <Link to={to} className="flex items-center gap-3 px-4 py-3 hover:bg-sky-50">
    <span className="min-w-0 flex-1"><span className="block text-sm font-medium text-slate-800">{label}</span>
      {note && <span className="block truncate text-xs text-slate-500">{note}</span>}</span>
    <ArrowRight size={16} className="shrink-0 text-slate-400" />
  </Link>;
}
