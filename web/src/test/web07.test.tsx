import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RenderPreview } from "@/features/edit/render-preview";
import { EditRender } from "@/features/edit/edit-render";
import type { RenderStatus } from "@/api/edit-render";

const projectId = "11111111-1111-4111-8111-111111111111";
const otherId = "22222222-2222-4222-8222-222222222222";
const renderId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const nextRenderId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const plain = `/projects/${projectId}/renders/${renderId.replaceAll("-", "")}/download`;
const subtitled = `/projects/${projectId}/renders/${renderId.replaceAll("-", "")}/subtitled/download`;

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("switches between the two validated URLs and preserves native playback controls", () => {
  render(<RenderPreview projectId={projectId} renderId={renderId} plainPath={plain} subtitledPath={subtitled} />);
  const original = screen.getByLabelText("자막 없는 최종 영상 재생") as HTMLVideoElement;
  expect(original).toHaveAttribute("src", `/api${plain}`);
  expect(original.controls).toBe(true);
  original.currentTime = 1.25;
  fireEvent.timeUpdate(original);
  expect(screen.getByText(/현재 재생 시각 1\.25초/)).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "한국어 하드 자막 영상" }));
  const captioned = screen.getByLabelText("한국어 하드 자막 최종 영상 재생");
  expect(captioned).toHaveAttribute("src", `/api${subtitled}`);
  expect(original).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "자막 없는 영상" }));
  expect(screen.getByLabelText("자막 없는 최종 영상 재생")).toHaveAttribute("src", `/api${plain}`);
});

it("keeps plain playback available when subtitles are absent and reports media failure", () => {
  render(<RenderPreview projectId={projectId} renderId={renderId} plainPath={plain} subtitledPath={null} />);
  expect(screen.getByRole("button", { name: "한국어 하드 자막 영상" })).toBeDisabled();
  const player = screen.getByLabelText("자막 없는 최종 영상 재생");
  fireEvent.error(player);
  expect(screen.getByText(/다운로드 버튼은 별도로 사용할 수 있습니다/)).toBeInTheDocument();
});

it("resets failed playback when a different project or render is shown", () => {
  const view = render(<RenderPreview key={`${projectId}:${renderId}`} projectId={projectId} renderId={renderId} plainPath={plain} subtitledPath={subtitled} />);
  fireEvent.click(screen.getByRole("button", { name: "한국어 하드 자막 영상" }));
  fireEvent.error(screen.getByLabelText("한국어 하드 자막 최종 영상 재생"));
  const nextPath = `/projects/${otherId}/renders/${nextRenderId.replaceAll("-", "")}/download`;
  view.rerender(<RenderPreview key={`${otherId}:${nextRenderId}`} projectId={otherId} renderId={nextRenderId} plainPath={nextPath} subtitledPath={null} />);
  expect(screen.queryByText(/다운로드 버튼은 별도로 사용할 수 있습니다/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("자막 없는 최종 영상 재생")).toHaveAttribute("src", `/api${nextPath}`);
});

const status = (id = renderId, run: RenderStatus["status"] = "COMPLETED", available = true): RenderStatus => {
  const hex = id.replaceAll("-", "");
  return { project_id: projectId, status: run, render_id: id, is_active: run === "RUNNING", succeeded: run === "COMPLETED", failed: false, safe_error_code: null,
    download_available: available, output: { filename: "final.mp4", duration_seconds: 5.4, video_codec: "h264", audio_codec: "aac", file_size_bytes: 200,
      download_url: available ? `/projects/${projectId}/renders/${hex}/download` : null },
    hard_subtitle_status: "AVAILABLE", hard_subtitle_error_code: null, hard_subtitle_download_available: available,
    hard_subtitle_download_url: available ? `/projects/${projectId}/renders/${hex}/subtitled/download` : null };
};

it("shows only the server-confirmed current result and hides it during the next render", async () => {
  const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.endsWith("/scene-candidates") ? { project_id: projectId, candidates: [] } :
      url.endsWith("/scene-edit-plan") ? { project_id: projectId, candidate_ids: [], invalid_candidate_ids: [] } : status(),
  ), { status: 200, headers: { "Content-Type": "application/json" } })));
  vi.stubGlobal("fetch", fetcher);
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={query}><EditRender projectId={projectId} /></QueryClientProvider>);
  expect(await screen.findByLabelText("최종 영상 미리보기")).toBeInTheDocument();
  query.setQueryData(["rendering", projectId], status(renderId, "RUNNING"));
  await waitFor(() => expect(screen.queryByLabelText("최종 영상 미리보기")).not.toBeInTheDocument());
  query.setQueryData(["rendering", projectId], status(nextRenderId));
  const next = await screen.findByLabelText("자막 없는 최종 영상 재생");
  expect(next).toHaveAttribute("src", `/api/projects/${projectId}/renders/${nextRenderId.replaceAll("-", "")}/download`);
  query.setQueryData(["rendering", projectId], status(nextRenderId, "COMPLETED", false));
  await waitFor(() => expect(screen.queryByLabelText("최종 영상 미리보기")).not.toBeInTheDocument());
  expect(screen.getByText(/기본 MP4 결과를 미리 보거나 다운로드할 수 없습니다/)).toBeInTheDocument();
});
