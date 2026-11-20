import { useEffect, useRef, useState } from "react";
import { FileVideo2 } from "lucide-react";
import { ApiError, uploadSource, validateVideo } from "@/api/projects";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Progress } from "@/components/ui/progress";

type UploadState = "waiting" | "uploading" | "done" | "failed";
type UploadItem = { key: string; file: File; state: UploadState; progress: number | null; message: string; retryable: boolean };

const stateLabels: Record<UploadState, string> = { waiting: "대기", uploading: "올라가는 중", done: "완료", failed: "실패" };
const stateStyles: Record<UploadState, string> = {
  waiting: "border-slate-200 text-slate-500",
  uploading: "border-sky-300 text-sky-700",
  done: "border-emerald-300 text-emerald-700",
  failed: "border-rose-300 text-rose-700",
};

function errorText(error: unknown): string {
  return error instanceof ApiError ? `${error.message}${error.code ? ` (${error.code})` : ""}` : "업로드를 완료하지 못했습니다.";
}
const fileKey = (file: File) => `${file.name}:${file.size}:${file.lastModified}`;

export function UploadQueue({ projectId, onUploaded }: { projectId: string; onUploaded: () => void }) {
  const [items, setItems] = useState<UploadItem[]>([]);
  const itemsRef = useRef<UploadItem[]>([]);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const stopRef = useRef(false);

  useEffect(() => () => { stopRef.current = true; abortRef.current?.abort(); }, []);

  function commit(next: UploadItem[]) { itemsRef.current = next; setItems(next); }
  function patch(key: string, change: Partial<UploadItem>) {
    commit(itemsRef.current.map((item) => item.key === key ? { ...item, ...change } : item));
  }

  function addFiles(files: File[]) {
    const known = new Set(itemsRef.current.map((item) => item.key));
    const added: UploadItem[] = [];
    for (const file of files) {
      const key = fileKey(file);
      if (known.has(key)) continue;
      known.add(key);
      const invalid = validateVideo(file);
      added.push({ key, file, state: invalid ? "failed" : "waiting", progress: null, message: invalid ?? "", retryable: !invalid });
    }
    commit([...itemsRef.current, ...added]);
  }

  async function run() {
    if (running) return;
    setRunning(true);
    stopRef.current = false;
    while (!stopRef.current) {
      const next = itemsRef.current.find((item) => item.state === "waiting");
      if (!next) break;
      patch(next.key, { state: "uploading", progress: 0, message: "" });
      const abort = new AbortController();
      abortRef.current = abort;
      try {
        const registered = await uploadSource(projectId, next.file, abort.signal, (percent) => patch(next.key, { progress: percent }));
        patch(next.key, { state: "done", progress: 100, message: `서버 등록 완료 · 소스 ID ${registered.source_video_id}` });
        onUploaded();
      } catch (error) {
        if (error instanceof DOMException && error.name === "AbortError") {
          patch(next.key, { state: "waiting", progress: null, message: "중지됨 · 서버 등록 여부는 오른쪽 소스 목록에서 확인해 주세요." });
          onUploaded();
          break;
        }
        patch(next.key, { state: "failed", progress: null, message: errorText(error), retryable: true });
      }
    }
    abortRef.current = null;
    setRunning(false);
  }

  function stop() { stopRef.current = true; abortRef.current?.abort(); }
  function retryFailed() {
    commit(itemsRef.current.map((item) => item.state === "failed" && item.retryable ? { ...item, state: "waiting", message: "" } : item));
  }
  function clearFinished() { commit(itemsRef.current.filter((item) => item.state === "waiting" || item.state === "uploading")); }

  const done = items.filter((item) => item.state === "done").length;
  const failed = items.filter((item) => item.state === "failed").length;
  const remaining = items.filter((item) => item.state === "waiting" || item.state === "uploading").length;
  const retryable = items.some((item) => item.state === "failed" && item.retryable);
  const hasWaiting = items.some((item) => item.state === "waiting");

  return <>
    <div><Label htmlFor="video-file">영상 파일 (여러 개 선택 가능)</Label><Input id="video-file" type="file" multiple accept=".mov,.mp4,video/quicktime,video/mp4" onChange={(event) => { addFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} /></div>
    {items.length > 0 && <div className="space-y-2">
      <p role="status" className="text-sm text-slate-600">전체 {items.length}개 · 완료 {done} · 실패 {failed} · 남음 {remaining}</p>
      <ul aria-label="업로드 목록" className="max-h-96 space-y-2 overflow-y-auto pr-1">{items.map((item) => <li key={item.key} className="min-w-0 rounded-xl border border-slate-200 bg-slate-50 px-3 py-2 sm:px-4">
        <div className="flex min-w-0 items-start justify-between gap-2">
          <p className="flex min-w-0 items-start gap-2 break-all text-sm text-slate-700"><FileVideo2 size={16} className="mt-0.5 shrink-0 text-sky-700" />{item.file.name}</p>
          <span className={`shrink-0 rounded-full border px-2.5 py-0.5 text-xs ${stateStyles[item.state]}`}>{stateLabels[item.state]}{item.state === "uploading" && item.progress !== null && item.progress < 100 ? ` ${item.progress}%` : ""}</span>
        </div>
        <p className="mt-1 pl-6 text-xs text-slate-500">{(item.file.size / 1024 / 1024).toFixed(1)} MiB{item.state === "uploading" ? item.progress === 100 ? " · 전송 완료, 서버 등록 응답 대기" : item.progress === null ? " · 전송 중" : "" : ""}</p>
        {item.state === "uploading" && <Progress className="mt-2" value={item.progress} />}
        {item.message && <p className={`mt-1 break-all pl-6 text-xs ${item.state === "failed" ? "text-rose-700" : item.state === "done" ? "text-sky-700" : "text-slate-500"}`}>{item.message}</p>}
      </li>)}</ul>
    </div>}
    <div className="flex flex-wrap gap-2 sm:gap-3">
      <Button onClick={() => void run()} disabled={running || !hasWaiting}>파일 등록</Button>
      {running && <Button variant="secondary" onClick={stop}>업로드 중지</Button>}
      {!running && retryable && <Button variant="secondary" onClick={retryFailed}>실패한 것 다시 올리기</Button>}
      {!running && (done > 0 || failed > 0) && <Button variant="secondary" onClick={clearFinished}>목록 비우기</Button>}
    </div>
    <p className="text-xs leading-5 text-slate-500">한 번에 한 개씩 차례로 올립니다. 하나가 실패해도 나머지는 계속 올립니다. 파일 형식·크기(최대 4 GiB)는 브라우저에서 먼저 확인하고, 최종 판단은 서버가 합니다.</p>
  </>;
}
