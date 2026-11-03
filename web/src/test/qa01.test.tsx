import { beforeEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json" },
});

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("shows render history API failure without hiding the latest completed result", async () => {
  vi.stubGlobal("fetch", vi.fn((url: string) => {
    if (url.includes("/renders?limit=")) return Promise.resolve(json({ detail: { code: "HISTORY_UNAVAILABLE" } }, 503));
    if (url.endsWith("/scene-candidates")) return Promise.resolve(json({ project_id: project, candidates: [] }));
    if (url.endsWith("/scene-edit-plan")) return Promise.resolve(json({ project_id: project, candidate_ids: [], invalid_candidate_ids: [] }));
    return Promise.resolve(json({
      project_id: project, status: "COMPLETED", render_id: renderId, is_active: false,
      succeeded: true, failed: false, safe_error_code: null, download_available: true,
      output: { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac",
        file_size_bytes: 100, download_url: `/projects/${project}/renders/${renderId.replaceAll("-", "")}/download` },
      hard_subtitle_status: "NO_SUBTITLES", hard_subtitle_error_code: null,
      hard_subtitle_download_available: false, hard_subtitle_download_url: null,
    }));
  }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EditRender projectId={project} /></QueryClientProvider>);
  expect(await screen.findByText(/이전 렌더 기록을 표시할 수 없습니다/)).toBeInTheDocument();
  expect(screen.getByText("저장된 장면이 없습니다. 장면을 선택하고 계획을 저장해 주세요.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
});
