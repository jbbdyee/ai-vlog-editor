import { useEffect, useRef, useState } from "react";
import { sourceMediaUrl, type Source } from "@/api/projects";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export interface PreviewRange {
  candidateId: string;
  sourceId: string;
  start: number;
  end: number;
}

export function SourcePreview({ projectId, sources, range, onClearRange }: {
  projectId: string;
  sources: Source[];
  range: PreviewRange | null;
  onClearRange: () => void;
}) {
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [time, setTime] = useState(0);
  const video = useRef<HTMLVideoElement>(null);
  const activeId = range?.sourceId ?? sourceId ?? sources[0]?.source_video_id ?? null;
  const activeSource = sources.find((source) => source.source_video_id === activeId);

  useEffect(() => {
    setError("");
    setTime(0);
    const player = video.current;
    if (player) { player.pause(); player.load(); }
  }, [projectId, activeId]);

  useEffect(() => {
    const player = video.current;
    if (!player || !range || range.sourceId !== activeId) return;
    player.pause();
    player.currentTime = range.start;
    setTime(range.start);
    setError("");
    void player.play().catch(() => setError("자동 재생이 차단됐습니다. 플레이어에서 재생을 눌러 주세요."));
  }, [range, activeId]);

  function updateTime() {
    const player = video.current;
    if (!player) return;
    if (range && player.currentTime >= range.end - 0.04) {
      player.pause();
      if (Math.abs(player.currentTime - range.end) > 0.005) player.currentTime = range.end;
    } else if (range && player.currentTime < range.start) {
      player.currentTime = range.start;
    }
    setTime(player.currentTime);
  }

  return <section id="source-preview" className="mt-3 min-w-0 scroll-mt-24 sm:mt-6 sm:scroll-mt-3" aria-label="원본 영상 미리보기"><Card><CardHeader><CardTitle>원본 영상 미리보기</CardTitle><CardDescription>원본·후보 구간을 재생합니다. 탐색 시각은 근사치입니다.</CardDescription></CardHeader><CardContent className="space-y-3 sm:space-y-4">
    {sources.length === 0 && <p className="text-sm text-slate-400">등록된 영상이 없습니다.</p>}
    {sources.length > 0 && <><label className="block text-sm text-slate-200" htmlFor="preview-source">원본 영상</label><select id="preview-source" className="block min-w-0 w-full rounded-lg border border-white/10 bg-[#0b1420] p-3 text-sm text-white" value={activeId ?? ""} onChange={(event) => { onClearRange(); setSourceId(event.target.value); }}>{sources.map((source) => <option key={source.source_video_id} value={source.source_video_id}>{source.original_filename} · 미리보기</option>)}</select>
      {range && <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-cyan-200"><span>후보 {range.start.toFixed(2)}–{range.end.toFixed(2)}초 · {(range.end - range.start).toFixed(2)}초</span><Button size="sm" variant="secondary" onClick={onClearRange}>전체 원본 보기</Button></div>}
      <video key={`${projectId}:${activeId}`} ref={video} aria-label={`${activeSource?.original_filename ?? "원본 영상"} 재생`} className="block aspect-video min-w-0 w-full rounded-xl bg-black" controls playsInline preload="metadata" src={activeId ? sourceMediaUrl(projectId, activeId) : undefined} onPlay={() => { if (range && video.current && video.current.currentTime >= range.end - 0.04) video.current.currentTime = range.start; }} onTimeUpdate={updateTime} onSeeking={updateTime} onLoadedMetadata={() => { if (range && video.current) video.current.currentTime = range.start; }} onError={() => setError("영상을 재생할 수 없습니다. 브라우저의 MOV/HEVC 지원 상태와 서버 연결을 확인해 주세요.")} />
      <p className="text-xs tabular-nums text-slate-400">현재 재생 시각 {time.toFixed(2)}초</p>{error && <Alert>{error} 후보 선택·편집 계획 저장은 계속 사용할 수 있습니다.</Alert>}</>}
  </CardContent></Card></section>;
}
