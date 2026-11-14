import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, LoaderCircle, MessageSquareText } from "lucide-react";
import { ApiError } from "@/api/projects";
import { captionedVideoSrc, getCaptionedVideo, startCaptionedVideo } from "@/api/captions";
import { formatDuration } from "@/api/story-direction";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

const errors: Record<string, string> = {
  CAPTION_RENDER_MISSING: "먼저 롱폼 영상을 렌더링해 주세요.",
  CAPTION_NO_LINES: "이 영상에는 말한 내용(자막)이 없어 입힐 수 없습니다.",
  CAPTION_RUNNING: "이미 자막을 입히는 중입니다.",
  CAPTION_BURN_FAILED: "자막을 영상에 입히지 못했습니다. 다시 시도해 주세요.",
  CAPTION_OUTPUT_INVALID: "자막 영상 길이가 원본과 달라 저장하지 않았습니다.",
};

function errorText(code: string | null | undefined, error?: unknown): string {
  if (error instanceof ApiError) return (error.code && errors[error.code]) || error.message;
  return (code && errors[code]) || "자막 영상을 만들지 못했습니다. 다시 시도해 주세요.";
}

/** TODO 21: under the render result, burn the spoken lines and a few inner thoughts onto the long-form video. */
export function LongformCaptions({ projectId, renderKey }: { projectId: string; renderKey?: string | null }) {
  const queryClient = useQueryClient();
  const key = ["captioned-video", projectId, renderKey ?? ""];
  const status = useQuery({
    queryKey: key, queryFn: () => getCaptionedVideo(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const start = useMutation({
    mutationFn: () => startCaptionedVideo(projectId),
    onSuccess: (value) => queryClient.setQueryData(key, value),
  });
  const data = status.data;
  if (!data?.latest_render_id && !data?.video) return null;
  const running = data.status === "RUNNING" || start.isPending;
  const video = data.video;
  return <div role="region" aria-label="말한 내용 자막" className="space-y-3 rounded-xl border border-white/10 bg-white/[.03] p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-100">말한 내용 자막 + 속마음</p>
        <p className="text-xs text-slate-400">마지막 렌더 영상에 말한 내용을 아래 자막으로, 가끔 작은 속마음 한마디를 오른쪽에 입힙니다. 속마음은 로컬 AI가 쓰고, AI가 꺼져 있으면 자막만 입혀요. 3분 영상은 1~2분쯤 걸려요.</p>
      </div>
      <Button onClick={() => start.mutate()} disabled={running || !data.latest_render_id}>
        <span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <MessageSquareText size={16} />}{running ? "자막 입히는 중…" : video ? "자막 다시 입히기" : "말한 내용 자막 입히기"}</span>
      </Button>
    </div>
    {data.status === "RUNNING" && <p role="status" className="text-sm text-cyan-200">{data.step}</p>}
    {status.isError && <Alert>{errorText(null, status.error)}</Alert>}
    {start.isError && <Alert>{errorText(null, start.error)}</Alert>}
    {data.status === "FAILED" && <Alert>{errorText(data.error_code)}</Alert>}
    {video && <div className="space-y-2">
      <video key={video.url} controls playsInline preload="metadata" src={captionedVideoSrc(video)} aria-label="자막 입힌 롱폼 영상"
        className="block aspect-video w-full min-w-0 rounded-lg bg-black" />
      <p className="text-sm text-slate-300 tabular-nums">길이 <b className="text-slate-50">{formatDuration(video.duration_seconds)}</b> · 자막 {video.line_count}줄 · 속마음 {video.thoughts.length}개 · {(video.file_size_bytes / 1024 / 1024).toFixed(1)}MB</p>
      {video.thoughts.length > 0 && <p className="text-xs text-slate-400">속마음: {video.thoughts.join(" · ")}</p>}
      {!video.matches_render && <p className="text-xs text-amber-200">새로 렌더한 영상이 있어요. 이 자막 영상은 예전 렌더로 만든 것입니다.</p>}
      <a href={captionedVideoSrc(video)} download="vlog-captioned.mp4" className="inline-flex items-center gap-1.5 text-sm text-cyan-300 underline"><Download size={14} />자막 영상 내려받기</a>
    </div>}
  </div>;
}
