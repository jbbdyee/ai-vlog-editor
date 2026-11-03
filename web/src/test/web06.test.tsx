import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SourcePreview } from "@/features/projects/source-preview";
import { EditRender } from "@/features/edit/edit-render";
import { sourceMediaUrl, type Source } from "@/api/projects";

const project = "11111111-1111-4111-8111-111111111111";
const sources: Source[] = [
  { source_video_id: "22222222-2222-4222-8222-222222222222", original_filename: "first.mov", processing_status: "COMPLETED", stages: [] },
  { source_video_id: "33333333-3333-4333-8333-333333333333", original_filename: "second.mp4", processing_status: "COMPLETED", stages: [] },
];
beforeEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(() => {});
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(() => Promise.resolve());
});

it("shows source, interval and duration in the saved order and links preview without changing selection", async () => {
  const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const onPreview = vi.fn();
  vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(new Response(JSON.stringify(
    url.endsWith("/scene-candidates") ? { project_id: project, candidates: [{ candidate_id: id, source_video_id: sources[0].source_video_id, start_seconds: 3, end_seconds: 4.25, evidence: [] }] } :
      url.endsWith("/scene-edit-plan") ? { project_id: project, candidate_ids: [id], invalid_candidate_ids: [] } :
        { project_id: project, status: "NOT_STARTED", is_active: false, succeeded: false, render_id: null },
  ), { status: 200, headers: { "Content-Type": "application/json" } }))));
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={query}><EditRender projectId={project} processing={{ project_id: project, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: sources.slice(0, 1) }} onPreview={onPreview} previewCandidateId={id} /></QueryClientProvider>);
  const item = await screen.findByText(/first\.mov · 3\.00–4\.25초 · 길이 1\.25초/);
  expect(item).toBeInTheDocument();
  const list = screen.getByRole("list", { name: "선택한 장면 순서" });
  fireEvent.click(list.querySelector("button")!);
  expect(onPreview).toHaveBeenCalledWith({ candidateId: id, sourceId: sources[0].source_video_id, start: 3, end: 4.25 });
  expect(screen.getByText("저장된 편집 계획입니다.")).toBeInTheDocument();
});

it("uses validated project/source media URL and switches the original", () => {
  const clear = vi.fn();
  render(<SourcePreview projectId={project} sources={sources} range={null} onClearRange={clear} />);
  const video = screen.getByLabelText("first.mov 재생") as HTMLVideoElement;
  expect(video.getAttribute("src")).toBe(sourceMediaUrl(project, sources[0].source_video_id));
  fireEvent.change(screen.getByLabelText("원본 영상", { exact: true }), { target: { value: sources[1].source_video_id } });
  expect(clear).toHaveBeenCalled();
  expect(screen.getByLabelText("second.mp4 재생")).toHaveAttribute("src", sourceMediaUrl(project, sources[1].source_video_id));
  expect(() => sourceMediaUrl(project, "../../secret")).toThrow();
});

it("seeks into a short candidate and stops at its end", () => {
  const range = { candidateId: "candidate", sourceId: sources[1].source_video_id, start: 4.12, end: 4.32 };
  render(<SourcePreview projectId={project} sources={sources} range={range} onClearRange={() => {}} />);
  const video = screen.getByLabelText("second.mp4 재생") as HTMLVideoElement;
  expect(video.currentTime).toBe(4.12);
  video.currentTime = 4.34;
  fireEvent.timeUpdate(video);
  expect(video.currentTime).toBe(4.32);
  expect(HTMLMediaElement.prototype.pause).toHaveBeenCalled();
  fireEvent.error(video);
  expect(screen.getByText(/후보 선택·편집 계획 저장은 계속 사용할 수 있습니다/)).toBeInTheDocument();
});

it("replaces the media URL and clears the old player on project change", () => {
  const other = "44444444-4444-4444-8444-444444444444";
  const view = render(<SourcePreview key={project} projectId={project} sources={sources} range={null} onClearRange={() => {}} />);
  const old = screen.getByLabelText("first.mov 재생");
  view.rerender(<SourcePreview key={other} projectId={other} sources={[sources[1]]} range={null} onClearRange={() => {}} />);
  expect(old).not.toBeInTheDocument();
  expect(screen.getByLabelText("second.mp4 재생")).toHaveAttribute("src", sourceMediaUrl(other, sources[1].source_video_id));
});
