import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import type { RenderStatus } from "@/api/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const previous = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const latest = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const status = (renderId: string, kind: RenderStatus["status"], available = true): RenderStatus => ({
  project_id: project, status: kind, render_id: renderId, is_active: kind === "RUNNING" || kind === "QUEUED",
  succeeded: kind === "COMPLETED", failed: kind === "FAILED", safe_error_code: kind === "FAILED" ? "CONCAT_FAILED" : null,
  download_available: kind === "COMPLETED" && available,
  output: kind === "COMPLETED" ? { filename: "final.mp4", duration_seconds: 5,
    video_codec: "h264", audio_codec: "aac", file_size_bytes: 123,
    download_url: available ? `/projects/${project}/renders/${renderId.replaceAll("-", "")}/download` : null } : null,
  hard_subtitle_status: kind === "COMPLETED" && available ? "AVAILABLE" : "NOT_STARTED",
  hard_subtitle_error_code: null, hard_subtitle_download_available: kind === "COMPLETED" && available,
  hard_subtitle_download_url: kind === "COMPLETED" && available ? `/projects/${project}/renders/${renderId.replaceAll("-", "")}/subtitled/download` : null,
});

function mount(current: RenderStatus, items: RenderStatus[]) {
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(json(
    url.includes("/renders?limit=") ? { project_id: project, items, next_cursor: null } :
      url.endsWith("/scene-candidates") ? { project_id: project, candidates: [] } :
        url.endsWith("/scene-edit-plan") ? { project_id: project, candidate_ids: [], invalid_candidate_ids: [] } : current,
  ))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EditRender projectId={project} /></QueryClientProvider>);
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("opens a previous completed result while the latest attempt failed", async () => {
  mount(status(latest, "FAILED"), [status(latest, "FAILED"), status(previous, "COMPLETED")]);
  expect(await screen.findByText("렌더 실패")).toBeInTheDocument();
  const buttons = await screen.findAllByRole("button", { name: "이 결과 보기" });
  expect(buttons[0]).toBeDisabled();
  fireEvent.click(buttons[1]);
  const video = await screen.findByLabelText("자막 없는 최종 영상 재생");
  expect(video).toHaveAttribute("src", `/api/projects/${project}/renders/${previous.replaceAll("-", "")}/download`);
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
});

it("explains interruption and prevents a missing file from playing", async () => {
  mount(status(latest, "INTERRUPTED"), [status(latest, "INTERRUPTED"), status(previous, "COMPLETED", false)]);
  expect(await screen.findByText(/이전 렌더 작업이 중단됐습니다/)).toBeInTheDocument();
  await waitFor(() => expect(screen.getByText(/기본 파일 누락/)).toBeInTheDocument());
  expect(screen.getAllByRole("button", { name: "이 결과 보기" }).every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  expect(screen.queryByLabelText("최종 영상 미리보기")).not.toBeInTheDocument();
});
