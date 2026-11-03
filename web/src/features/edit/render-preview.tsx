import { useEffect, useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

type Version = "plain" | "subtitled";

export function RenderPreview({ projectId, renderId, plainPath, subtitledPath, onUnavailable }: {
  projectId: string;
  renderId: string;
  plainPath: string;
  subtitledPath: string | null;
  /** Called when the media request fails (e.g. 409 integrity block) so the caller re-reads status. */
  onUnavailable?: () => void;
}) {
  const [version, setVersion] = useState<Version>("plain");
  const [time, setTime] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => { setVersion("plain"); setTime(0); setLoading(true); setError(""); }, [projectId, renderId]);
  useEffect(() => { if (version === "subtitled" && !subtitledPath) setVersion("plain"); }, [version, subtitledPath]);
  const path = version === "subtitled" && subtitledPath ? subtitledPath : plainPath;

  return <div className="min-w-0 space-y-3 rounded-xl border border-white/10 bg-[#0b1420] p-3 sm:p-4" aria-label="최종 영상 미리보기">
    <div className="flex min-w-0 flex-wrap items-center justify-between gap-3"><div className="min-w-0"><p className="text-sm font-medium text-white">최종 영상 미리보기</p><p className="mt-1 text-xs text-slate-400">현재 서버가 확인한 렌더 결과만 재생합니다.</p></div><div className="flex min-w-0 flex-wrap gap-2" role="group" aria-label="영상 버전 선택"><Button size="sm" variant={version === "plain" ? "default" : "secondary"} onClick={() => setVersion("plain")}>자막 없는 영상</Button><Button size="sm" variant={version === "subtitled" ? "default" : "secondary"} disabled={!subtitledPath} onClick={() => setVersion("subtitled")}>한국어 하드 자막 영상</Button></div></div>
    <video key={`${projectId}:${renderId}:${version}`} aria-label={`${version === "plain" ? "자막 없는" : "한국어 하드 자막"} 최종 영상 재생`} className="block aspect-video min-w-0 w-full rounded-lg bg-black" controls playsInline preload="metadata" src={`/api${path}`} onLoadStart={() => { setTime(0); setLoading(true); setError(""); }} onLoadedMetadata={() => setLoading(false)} onTimeUpdate={(event) => setTime(event.currentTarget.currentTime)} onError={() => { setLoading(false); setError("결과 영상을 재생할 수 없습니다. 파일 상태와 서버 연결을 다시 확인해 주세요."); onUnavailable?.(); }} />
    <p className="text-xs tabular-nums text-slate-400">{version === "plain" ? "자막 없음" : "한국어 하드 자막"} · 현재 재생 시각 {time.toFixed(2)}초{loading && !error ? " · 불러오는 중" : ""}</p>
    {error && <Alert>{error} 다운로드 버튼은 별도로 사용할 수 있습니다.</Alert>}
  </div>;
}
