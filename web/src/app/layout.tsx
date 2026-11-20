import { Clapperboard, LockKeyhole } from "lucide-react";
import { Link, Outlet } from "react-router-dom";

export function Layout() {
  return <div className="min-h-screen bg-[#F3F5F7] text-slate-800">
    <div className="relative mx-auto min-h-screen min-w-0 max-w-[1500px] px-3 sm:px-8 lg:px-12">
      <header className="flex h-14 items-center justify-between border-b border-slate-200 sm:h-20">
        <Link to="/" className="flex items-center gap-3 text-slate-900" aria-label="Cutory 홈">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-sky-600 text-white"><Clapperboard size={20} strokeWidth={2.2} /></span>
          <span className="text-xl font-bold tracking-[-.04em]">cutory<span className="text-sky-700">.</span></span>
        </Link>
        <span className="hidden items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-xs text-amber-700 sm:flex"><LockKeyhole size={13} /> 로컬 개발 전용 · 인증 미구현</span>
      </header>
      <main><Outlet /></main>
      <footer className="mt-10 flex flex-col gap-2 border-t border-slate-200 py-5 text-xs text-slate-500 sm:mt-20 sm:flex-row sm:justify-between sm:py-7">
        <span>Cutory · 영상 편집 작업의 첫 단계</span>
        <span>프로젝트 등록·장면 분석·편집 계획·렌더링을 지원합니다.</span>
      </footer>
    </div>
  </div>;
}
