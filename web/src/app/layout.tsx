import { Clapperboard, LockKeyhole } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return <div className="min-h-screen bg-[#080e17] text-slate-100">
    <div className="pointer-events-none fixed inset-0 bg-[radial-gradient(circle_at_80%_0%,rgba(23,103,126,.18),transparent_36%),radial-gradient(circle_at_0%_55%,rgba(42,65,103,.12),transparent_35%)]" />
    <div className="relative mx-auto min-h-screen min-w-0 max-w-[1500px] px-3 sm:px-8 lg:px-12">
      <header className="flex h-14 items-center justify-between border-b border-white/8 sm:h-20">
        <Link to="/" className="flex items-center gap-3 text-white" aria-label="Cutory 홈">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-cyan-300 text-slate-950"><Clapperboard size={20} strokeWidth={2.2} /></span>
          <span className="text-xl font-bold tracking-[-.04em]">cutory<span className="text-cyan-300">.</span></span>
        </Link>
        <span className="hidden items-center gap-2 rounded-full border border-amber-300/15 bg-amber-300/5 px-4 py-2 text-xs text-amber-100/75 sm:flex"><LockKeyhole size={13} /> 로컬 개발 전용 · 인증 미구현</span>
      </header>
      <main><Outlet /></main>
      <footer className="mt-10 flex flex-col gap-2 border-t border-white/8 py-5 text-xs text-slate-500 sm:mt-20 sm:flex-row sm:justify-between sm:py-7">
        <span>Cutory · 영상 편집 작업의 첫 단계</span>
        <span>프로젝트 등록·장면 분석·편집 계획·렌더링을 지원합니다.</span>
      </footer>
    </div>
  </div>;
}
