import { useState, type FormEvent } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowRight, Film, FolderPlus, Link2, Sparkles } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, createProject, getProject, isProjectId, listProjects } from "@/api/projects";

function message(error: unknown) { return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "요청을 완료하지 못했습니다."; }

export function HomePage() {
  const navigate = useNavigate();
  const [offset, setOffset] = useState(0);
  const projects = useQuery({ queryKey: ["project-list", offset], queryFn: () => listProjects(offset), retry: false });
  const [name, setName] = useState("");
  const [projectId, setProjectId] = useState("");
  const [openError, setOpenError] = useState("");
  const create = useMutation({ mutationFn: createProject, onSuccess: (project) => navigate(`/projects/${project.project_id}`) });
  const open = useMutation({ mutationFn: getProject, onSuccess: (project) => navigate(`/projects/${project.project_id}`) });

  function onCreate(event: FormEvent) {
    event.preventDefault();
    const clean = name.trim();
    if (clean && clean.length <= 255) create.mutate(clean);
  }
  function onOpen(event: FormEvent) {
    event.preventDefault();
    const id = projectId.trim();
    if (!isProjectId(id)) { setOpenError("올바른 프로젝트 ID를 입력해 주세요."); return; }
    setOpenError("");
    open.mutate(id);
  }

  return <>
    <section className="grid min-w-0 gap-6 py-9 sm:py-16 lg:grid-cols-[1.15fr_.85fr] lg:items-end lg:py-24">
      <div className="min-w-0">
        <p className="mb-4 inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-300/7 px-3 py-1.5 text-[11px] font-semibold uppercase tracking-[.12em] text-cyan-200 sm:mb-6 sm:px-4 sm:py-2 sm:text-xs sm:tracking-[.18em]"><Sparkles size={14} /> Creative workspace · local</p>
        <h1 className="max-w-3xl text-3xl font-semibold leading-[1.12] tracking-[-.045em] text-white sm:text-6xl lg:text-7xl">장면을 찾는 일부터,<br /><span className="text-cyan-300">편집의 흐름까지.</span></h1>
        <p className="mt-4 max-w-xl text-sm leading-6 text-slate-400 sm:mt-7 sm:text-base sm:leading-8">영상을 등록하고 장면을 고르세요. 사용할 장면의 순서를 저장한 뒤 기본·한국어 자막 영상을 만듭니다.</p>
      </div>
      <div className="relative hidden h-72 overflow-hidden rounded-3xl border border-white/10 bg-[#101b29] p-6 lg:block" aria-hidden="true">
        <div className="absolute -right-16 -top-20 h-64 w-64 rounded-full bg-cyan-300/15 blur-3xl" />
        <div className="relative flex items-center justify-between text-xs uppercase tracking-[.18em] text-slate-500"><span>Workspace / 001</span><span>24 fps · Preview later</span></div>
        <div className="relative mt-11 grid h-36 grid-cols-3 gap-3 opacity-85"><div className="rounded-xl border border-cyan-300/25 bg-gradient-to-br from-cyan-900/70 to-slate-950" /><div className="rounded-xl border border-white/10 bg-gradient-to-br from-slate-700/55 to-slate-950" /><div className="rounded-xl border border-white/10 bg-gradient-to-br from-blue-900/65 to-slate-950" /></div>
        <div className="relative mt-5 flex items-center gap-2"><span className="h-1.5 w-20 rounded bg-cyan-300" /><span className="h-1.5 w-12 rounded bg-slate-600" /><span className="h-1.5 w-24 rounded bg-slate-600" /><span className="ml-auto text-xs text-slate-500">영상 작업 공간 준비 중</span></div>
      </div>
    </section>
    <section className="grid min-w-0 gap-3 sm:gap-5 lg:grid-cols-2" aria-label="프로젝트 시작">
      <Card><CardHeader><div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-cyan-300/10 text-cyan-300"><FolderPlus size={21} /></div><CardTitle>새 프로젝트 시작</CardTitle><CardDescription>프로젝트를 만든 다음 MOV 또는 MP4 원본을 등록합니다.</CardDescription></CardHeader><CardContent>
        <form onSubmit={onCreate} className="space-y-4"><div><Label htmlFor="project-name">프로젝트 이름</Label><Input id="project-name" value={name} onChange={(event) => setName(event.target.value)} placeholder="예: 주말의 작은 기록" maxLength={255} required /></div>
          {create.error && <Alert>{message(create.error)}</Alert>}
          <Button type="submit" disabled={create.isPending || !name.trim()} className="w-full">{create.isPending ? "프로젝트 생성 중…" : "프로젝트 만들기"}<ArrowRight size={17} /></Button>
        </form>
      </CardContent></Card>
      <Card><CardHeader><div className="mb-4 flex h-11 w-11 items-center justify-center rounded-xl bg-white/8 text-slate-300"><Link2 size={21} /></div><CardTitle>프로젝트 ID로 열기</CardTitle><CardDescription>목록에 없는 프로젝트도 ID로 직접 확인할 수 있습니다.</CardDescription></CardHeader><CardContent>
        <form onSubmit={onOpen} className="space-y-4"><div><Label htmlFor="project-id">프로젝트 ID</Label><Input id="project-id" value={projectId} onChange={(event) => { setProjectId(event.target.value); setOpenError(""); }} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" /></div>
          {(openError || open.error) && <Alert>{openError || message(open.error)}</Alert>}
          <Button type="submit" variant="secondary" disabled={open.isPending} className="w-full">{open.isPending ? "프로젝트 확인 중…" : "ID로 열기"}<ArrowRight size={17} /></Button>
        </form>
      </CardContent></Card>
    </section>
    <section className="mt-8 min-w-0 sm:mt-12" aria-label="기존 프로젝트 목록">
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3"><div className="min-w-0"><h2 className="text-xl font-semibold text-white sm:text-2xl">기존 프로젝트</h2><p className="mt-1 text-xs text-slate-400 sm:text-sm">이 로컬 DB에 저장된 프로젝트를 생성일 최신순으로 표시합니다.</p></div><Button variant="secondary" size="sm" onClick={() => void projects.refetch()} disabled={projects.isFetching}>목록 새로고침</Button></div>
      {projects.isPending && <p className="rounded-xl border border-white/10 p-4 text-sm text-slate-400" role="status">프로젝트 목록을 불러오는 중…</p>}
      {projects.isError && <Alert>프로젝트 목록을 불러오지 못했습니다. {message(projects.error)}</Alert>}
      {projects.data?.items.length === 0 && <p className="rounded-xl border border-white/10 p-4 text-sm text-slate-400">저장된 프로젝트가 없습니다. 새 프로젝트를 시작해 주세요.</p>}
      {projects.data && projects.data.items.length > 0 && <div className="grid min-w-0 gap-3 md:grid-cols-2 xl:grid-cols-3">{projects.data.items.map((item) => <Link key={item.project_id} to={`/projects/${item.project_id}`} className="block min-w-0 rounded-xl border border-white/10 bg-white/[.03] p-3 transition-colors hover:border-cyan-300/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 sm:p-4"><h3 className="break-words text-base font-semibold text-white">{item.name?.trim() || "이름 없는 프로젝트"}</h3><p className="mt-1 break-all text-[11px] text-slate-500">{item.project_id}</p><div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-xs text-slate-300"><span>생성 {new Date(item.created_at).toLocaleDateString("ko-KR")}</span><span>영상 {item.source_count}개</span><span>편집 계획 {item.has_edit_plan ? "있음" : "없음"}</span></div><p className="mt-2 text-xs text-slate-400">최근 렌더 기록: {item.latest_render_status ?? "없음"}</p></Link>)}</div>}
      {projects.data && (offset > 0 || projects.data.next_offset !== null) && <div className="mt-4 flex gap-2"><Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 20))}>이전</Button><Button variant="secondary" size="sm" disabled={projects.data.next_offset === null} onClick={() => setOffset(projects.data!.next_offset!)}>다음</Button></div>}
    </section>
    <p className="mt-5 flex items-start gap-2 text-xs leading-5 text-slate-500 sm:mt-8 sm:text-sm"><Film size={16} className="mt-0.5 shrink-0" /> 영상 분석·렌더링은 FastAPI가 담당합니다. 로컬 개발 환경에서만 사용하세요.</p>
  </>;
}
