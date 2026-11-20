import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { getProcessing, getProject, isProjectId } from "@/api/projects";
import { clock, getChatEdit, getTasteScores } from "@/api/chat-edit";
import { getDayBrief } from "@/api/story-direction";
import { getRendering } from "@/api/edit-render";
import { getReelStatus } from "@/api/reels";
import { Alert } from "@/components/ui/alert";

/** TODO 36: the project home. Six cards show how far the day's edit has come; one button opens the edit room. */
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

  if (!valid) return <div className="mx-auto max-w-2xl py-24"><Alert>올바른 프로젝트 주소가 아니에요.</Alert></div>;
  const tools = `/projects/${projectId}/tools`;
  const editRoom = `/projects/${projectId}/chat-edit`;
  const cuts = plan.data?.cuts ?? [];
  const total = plan.data?.total_seconds ?? 0;
  const counts = taste.data?.counts ?? {};
  const scored = ["3", "2", "1", "0"].reduce((sum, key) => sum + (counts[key] ?? 0), 0);
  const made = render.data?.status === "COMPLETED" && render.data.output;
  const running = render.data?.is_active;

  return <div className="py-6 sm:py-10">
    <Link to="/" className="inline-flex items-center gap-2 text-sm text-slate-500 hover:text-slate-900"><ArrowLeft size={16} /> 프로젝트 목록</Link>
    <div className="mt-4 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="break-words text-3xl font-bold tracking-[-.03em] text-slate-900 sm:text-4xl">{project.data?.name ?? "프로젝트"}</h1>
        <p className="mt-2 text-sm text-slate-500">
          {project.data && new Date(project.data.created_at).toLocaleDateString("ko-KR", { month: "long", day: "numeric" })}
          {sources.data && ` · 원본 ${sources.data.total_sources}개`}
          {cuts.length > 0 && ` · 편집안 ${clock(total)}`}
        </p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Link to={tools} className="text-sm text-slate-500 hover:text-sky-700">모든 도구</Link>
        <Link to={editRoom} className="inline-flex h-12 items-center gap-2 rounded-xl bg-sky-600 px-5 text-[15px] font-bold text-white hover:bg-sky-700">편집실 들어가기 <ArrowRight size={18} /></Link>
      </div>
    </div>

    <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <HomeCard title="원본 영상" link={{ to: `${tools}#upload`, label: "영상 더 넣기" }}>
        <Big>{sources.data ? `${sources.data.total_sources}개` : "…"}</Big>
        {sources.data && <Small>분석 끝 {sources.data.completed_count}{sources.data.failed_count > 0 && ` · 읽지 못함 ${sources.data.failed_count}`}</Small>}
      </HomeCard>

      <HomeCard title="오늘 있었던 일" link={{ to: `${tools}#story-direction`, label: brief.data ? "고치기" : "적기" }}>
        {brief.data
          ? <p className="line-clamp-3 text-[15px] leading-6 text-slate-700">{brief.data}</p>
          : <Small>아직 안 적었어요. 하루를 한두 줄로 적으면 AI가 흐름을 잡을 때 참고해요.</Small>}
      </HomeCard>

      <HomeCard title="편집안" now link={{ to: editRoom, label: "편집실 열기" }}>
        <Big>{cuts.length > 0 ? clock(total) : "아직 없음"}</Big>
        {cuts.length > 0 && <>
          <div aria-label="컷 띠" className="flex h-[18px] gap-[2px]">
            {cuts.map((cut) => <span key={cut.candidate_id} className="rounded-[2px] bg-sky-300" style={{ flex: `${Math.max(cut.length, 1)} 1 0` }} />)}
          </div>
          <Small>컷 {cuts.length}개 · 안 쓴 장면 {plan.data?.unused.length ?? 0}개</Small>
        </>}
      </HomeCard>

      <HomeCard title="내 취향" link={{ to: `${editRoom}#taste-brief`, label: "취향 글 고치기" }}>
        {scored > 0 ? <>
          <div aria-label="장면 점수" className="flex h-3.5 gap-[2px] overflow-hidden rounded-full">
            {[["3", "bg-sky-800"], ["2", "bg-sky-500"], ["1", "bg-sky-200"], ["0", "bg-slate-300"]].map(([key, color]) =>
              <span key={key} className={color} style={{ flex: `${counts[key] ?? 0} 1 0` }} />)}
          </div>
          <Small>꼭 남김 {counts["3"] ?? 0} · 좋음 {counts["2"] ?? 0} · 빼도 됨 {counts["1"] ?? 0} · 빼야 함 {counts["0"] ?? 0}</Small>
        </> : <Small>아직 장면 점수가 없어요.</Small>}
      </HomeCard>

      <HomeCard title="완성 영상" link={{ to: `${tools}#edit-render`, label: made ? "내려받기 · 다시 만들기" : "만들러 가기" }}>
        <Big>{running ? "만드는 중" : made ? clock(made.duration_seconds) : "아직 없음"}</Big>
        {made && <Small>{Math.round(made.file_size_bytes / 1024 / 1024)}MB · 편집안을 고쳤다면 다시 만들어야 해요</Small>}
      </HomeCard>

      <HomeCard title="릴스" dashed={!reel.data?.draft} link={{ to: `${tools}#reel-draft`, label: reel.data?.draft ? "릴스 열기" : "릴스 만들기" }}>
        <Big>{reel.data?.draft ? "초안 있음" : "아직 없음"}</Big>
      </HomeCard>
    </div>
  </div>;
}

function HomeCard({ title, link, now = false, dashed = false, children }: { title: string; link: { to: string; label: string }; now?: boolean; dashed?: boolean; children: ReactNode }) {
  const frame = now ? "border-2 border-sky-400 p-[21px]" : dashed ? "border border-dashed border-slate-300 p-[22px]" : "border border-slate-200 p-[22px]";
  return <section aria-label={title} className={`flex min-w-0 flex-col gap-3 rounded-2xl bg-white ${frame}`}>
    <h2 className={`text-[15px] ${now ? "font-bold text-sky-700" : "font-medium text-slate-500"}`}>{title}{now && " · 지금 여기"}</h2>
    {children}
    <Link to={link.to} className={`mt-auto pt-1 text-sm text-sky-700 hover:text-sky-900 ${now ? "font-bold" : "font-medium"}`}>{link.label}</Link>
  </section>;
}

const Big = ({ children }: { children: ReactNode }) => <p className="text-[32px] font-bold leading-tight text-slate-900 tabular-nums">{children}</p>;
const Small = ({ children }: { children: ReactNode }) => <p className="text-sm leading-6 text-slate-500">{children}</p>;
