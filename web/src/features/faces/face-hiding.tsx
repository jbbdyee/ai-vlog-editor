import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, ImagePlus, LoaderCircle, ScanFace, Trash2 } from "lucide-react";
import { ApiError } from "@/api/projects";
import { addMyFacePhoto, apiSrc, getFaceVideo, getMyFace, removeMyFacePhoto, startFaceVideo } from "@/api/faces";
import { formatDuration } from "@/api/story-direction";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const MY_FACE_KEY = ["my-face"];

const videoErrors: Record<string, string> = {
  FACE_RENDER_MISSING: "먼저 롱폼 영상을 렌더링해 주세요.",
  FACE_NOT_REGISTERED: "프로젝트 화면의 '내 얼굴' 카드에서 내 얼굴 사진을 먼저 등록해 주세요.",
  FACE_MODEL_MISSING: "얼굴 모델 파일이나 OpenCV가 없어 얼굴을 가릴 수 없습니다.",
  FACE_RUNNING: "이미 얼굴을 가리는 중입니다.",
  FACE_ENCODE_FAILED: "얼굴 가린 영상을 저장하지 못했습니다. 다시 시도해 주세요.",
  FACE_OUTPUT_INVALID: "얼굴 가린 영상 길이가 원본과 달라 저장하지 않았습니다.",
};

function message(error: unknown, code?: string | null): string {
  if (error instanceof ApiError) return (error.code && videoErrors[error.code]) || error.message;
  return (code && videoErrors[code]) || "얼굴 가린 영상을 만들지 못했습니다. 다시 시도해 주세요.";
}

/** TODO 25: register 3~5 photos of my own face; every project uses them to keep my face and hide everyone else's. */
export function MyFaceCard() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const face = useQuery({ queryKey: MY_FACE_KEY, queryFn: getMyFace });
  const add = useMutation({
    mutationFn: async (files: File[]) => {
      let last = face.data;
      const failed: string[] = [];
      for (const file of files) {
        try { last = await addMyFacePhoto(file); } catch (error) { failed.push(`${file.name}: ${error instanceof Error ? error.message : "올리지 못했습니다."}`); }
      }
      if (last) queryClient.setQueryData(MY_FACE_KEY, last);
      if (failed.length) throw new Error(failed.join("\n"));
    },
  });
  const remove = useMutation({
    mutationFn: removeMyFacePhoto,
    onSuccess: (value) => queryClient.setQueryData(MY_FACE_KEY, value),
  });
  const photos = face.data?.photos ?? [];
  return <Card aria-label="내 얼굴"><CardHeader>
    <CardTitle className="flex items-center gap-2"><ScanFace size={18} />내 얼굴</CardTitle>
    <CardDescription>내 얼굴이 정면으로 크게 나온 사진을 3~5장 올려 주세요. 영상 만들기에서 '다른 사람 얼굴 가리기'를 하면 이 얼굴만 남기고 모든 얼굴을 모자이크합니다. 모든 프로젝트가 같이 써요.</CardDescription>
  </CardHeader><CardContent className="space-y-3">
    {face.isError && <Alert>{message(face.error)}</Alert>}
    {face.data && !face.data.model_available && <Alert>얼굴 모델 파일이나 OpenCV가 없어 사진을 등록할 수 없습니다.</Alert>}
    <ul className="flex flex-wrap gap-3" aria-label="등록한 내 얼굴">
      {photos.map((photo) => <li key={photo.id} className="relative">
        <img src={apiSrc(photo.url)} alt={`내 얼굴 ${photo.filename}`} className="h-20 w-20 rounded-full border border-white/15 object-cover" />
        <button type="button" aria-label={`${photo.filename} 지우기`} disabled={remove.isPending}
          onClick={() => remove.mutate(photo.id)}
          className="absolute -right-1 -top-1 rounded-full border border-white/20 bg-[#0b1420] p-1 text-slate-300 hover:text-white">
          <Trash2 size={12} />
        </button>
      </li>)}
      {photos.length === 0 && !face.isPending && <li className="text-sm text-slate-400">아직 등록한 얼굴이 없어요.</li>}
    </ul>
    <p className="text-sm text-slate-300">등록 {photos.length}장{photos.length > 0 && photos.length < 3 ? " · 3장 이상이면 옆모습도 더 잘 알아봐요" : ""}</p>
    <input ref={input} type="file" accept="image/*" multiple className="hidden" aria-label="내 얼굴 사진 고르기"
      onChange={(event) => { const files = Array.from(event.target.files ?? []); event.target.value = ""; if (files.length) add.mutate(files); }} />
    <Button variant="secondary" disabled={add.isPending || face.data?.model_available === false} onClick={() => input.current?.click()}>
      <span className="flex items-center gap-2">{add.isPending ? <LoaderCircle size={16} className="animate-spin" /> : <ImagePlus size={16} />}{add.isPending ? "얼굴 찾는 중…" : "사진 올리기"}</span>
    </Button>
    {add.isError && <Alert><span className="whitespace-pre-line">{add.error.message}</span></Alert>}
    {remove.isError && <Alert>{message(remove.error)}</Alert>}
  </CardContent></Card>;
}

/** TODO 25: under the render result, pixelate every face but mine on the last long-form render. */
export function FaceHiding({ projectId, renderKey }: { projectId: string; renderKey?: string | null }) {
  const queryClient = useQueryClient();
  const key = ["face-video", projectId, renderKey ?? ""];
  const status = useQuery({
    queryKey: key, queryFn: () => getFaceVideo(projectId),
    refetchInterval: (query) => query.state.data?.status === "RUNNING" ? 2000 : false,
  });
  const start = useMutation({
    mutationFn: () => startFaceVideo(projectId),
    onSuccess: (value) => queryClient.setQueryData(key, value),
  });
  const data = status.data;
  if (!data?.latest_render_id && !data?.video) return null;
  const running = data.status === "RUNNING" || start.isPending;
  const video = data.video;
  return <div role="region" aria-label="다른 사람 얼굴 가리기" className="space-y-3 rounded-xl border border-white/10 bg-white/[.03] p-3">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <p className="text-sm font-semibold text-slate-100">다른 사람 얼굴 가리기</p>
        <p className="text-xs text-slate-400">등록한 내 얼굴({data.photo_count}장)만 남기고 영상 속 모든 얼굴을 모자이크합니다. 너무 작거나 알아보기 어려운 얼굴도 가려요. 영상 길이만큼쯤 걸려요(8분 영상 → 약 8분). 가린 뒤 자막을 입히면 가린 영상 위에 자막이 올라갑니다.</p>
      </div>
      <Button onClick={() => start.mutate()} disabled={running || !data.latest_render_id || data.photo_count === 0}>
        <span className="flex items-center gap-2">{running ? <LoaderCircle size={16} className="animate-spin" /> : <ScanFace size={16} />}{running ? "얼굴 가리는 중…" : video ? "다시 가리기" : "다른 사람 얼굴 가리기"}</span>
      </Button>
    </div>
    {data.photo_count === 0 && <p className="text-sm text-amber-200">프로젝트 화면의 '내 얼굴' 카드에서 내 얼굴 사진을 먼저 올려 주세요.</p>}
    {data.status === "RUNNING" && <p role="status" className="text-sm text-cyan-200 tabular-nums">{data.total ? `${formatDuration(data.done / 30)} / ${formatDuration(data.total / 30)} 확인함` : "준비 중"}</p>}
    {status.isError && <Alert>{message(status.error)}</Alert>}
    {start.isError && <Alert>{message(start.error)}</Alert>}
    {data.status === "FAILED" && <Alert>{message(null, data.error_code)}</Alert>}
    {video && <div className="space-y-2">
      <video key={video.url} controls playsInline preload="metadata" src={apiSrc(video.url)} aria-label="얼굴 가린 롱폼 영상"
        className="block aspect-video w-full min-w-0 rounded-lg bg-black" />
      <p className="text-sm text-slate-300 tabular-nums">길이 <b className="text-slate-50">{formatDuration(video.duration_seconds)}</b> · 얼굴 가린 장면 {formatDuration(video.frames_hidden / 30)} · 내 얼굴이 나온 장면 {formatDuration(video.frames_with_me / 30)} · {(video.file_size_bytes / 1024 / 1024).toFixed(1)}MB</p>
      {!video.matches_render && <p className="text-xs text-amber-200">새로 렌더한 영상이 있어요. 이 영상은 예전 렌더로 만든 것입니다.</p>}
      <a href={apiSrc(video.url)} download="vlog-faces.mp4" className="inline-flex items-center gap-1.5 text-sm text-cyan-300 underline"><Download size={14} />얼굴 가린 영상 내려받기</a>
    </div>}
  </div>;
}
