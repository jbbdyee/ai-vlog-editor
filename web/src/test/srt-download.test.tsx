import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import { downloadPath, fetchRenderFile, type RenderStatus } from "@/api/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const renderId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const hex = renderId.replaceAll("-", "");
const srtUrl = `/projects/${project}/renders/${hex}/subtitles/download`;
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const srtBody = "1\n00:00:00,000 --> 00:00:01,000\n안녕하세요\n";

function completed(srt: "VERIFIED" | "CORRUPT" | null, overrides: Partial<RenderStatus> = {}): RenderStatus {
  return {
    project_id: project, status: "COMPLETED", render_id: renderId, is_active: false, succeeded: true, failed: false,
    safe_error_code: null, download_available: true,
    output: { filename: "final.mp4", duration_seconds: 4, video_codec: "h264", audio_codec: "aac", file_size_bytes: 10,
      download_url: `/projects/${project}/renders/${hex}/download` },
    hard_subtitle_status: "AVAILABLE", hard_subtitle_error_code: null, hard_subtitle_download_available: true,
    hard_subtitle_download_url: `/projects/${project}/renders/${hex}/subtitled/download`,
    integrity_status: "VERIFIED", subtitle_integrity_status: srt, hard_subtitle_integrity_status: "VERIFIED",
    subtitle_download_available: srt === "VERIFIED", subtitle_download_url: srt === "VERIFIED" ? srtUrl : null,
    ...overrides,
  };
}

function mount(current: RenderStatus, download?: (url: string) => Response) {
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(
    download && url.includes("/download") ? download(url) :
      json(url.includes("/renders?limit=") ? { project_id: project, items: [current], next_cursor: null } :
        url.endsWith("/scene-candidates") ? { project_id: project, candidates: [] } :
          url.endsWith("/scene-edit-plan") ? { project_id: project, candidate_ids: [], invalid_candidate_ids: [] } : current)));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EditRender projectId={project} /></QueryClientProvider>);
  return fetchMock;
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("downloads the verified SRT as final.srt from the subtitles endpoint", async () => {
  const createObjectURL = vi.fn().mockReturnValue("blob:srt");
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL, revokeObjectURL: vi.fn() }));
  const clicked: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) { clicked.push(this.download); });
  const fetchMock = mount(completed("VERIFIED"), () => new Response(srtBody, { status: 200, headers: { "Content-Type": "application/x-subrip; charset=utf-8" } }));
  const button = await screen.findByRole("button", { name: "자막(SRT) 다운로드" });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  await waitFor(() => expect(clicked).toEqual(["final.srt"]));
  expect(fetchMock.mock.calls.some(([url]) => url === `/api${srtUrl}`)).toBe(true);
  const blob = createObjectURL.mock.calls[0][0] as Blob;
  expect(await blob.text()).toBe(srtBody);
  // The existing MP4 buttons are unchanged.
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeEnabled();
});

it("disables the SRT button when the SRT is unavailable, corrupt or the server is older", async () => {
  mount(completed("CORRUPT"));
  expect(await screen.findByRole("button", { name: "자막(SRT) 다운로드" })).toBeDisabled();
  expect(screen.getByText(/자막\(SRT\) 다운로드를 차단했습니다/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();

  const old = completed("VERIFIED");
  delete old.subtitle_download_available; delete old.subtitle_download_url;
  expect(downloadPath(old, project, "srt")).toBeNull();
  expect(downloadPath(completed(null), project, "srt")).toBeNull();
  expect(downloadPath(completed("VERIFIED", { subtitle_download_url: "/elsewhere.srt" }), project, "srt")).toBeNull();
  expect(downloadPath(completed("VERIFIED", { status: "RUNNING", succeeded: false, is_active: true }), project, "srt")).toBeNull();
  expect(downloadPath(completed("VERIFIED"), project, "srt")).toBe(srtUrl);
});

it("reports a blocked SRT download by code and rejects a non-SRT response", async () => {
  const fetchMock = mount(completed("VERIFIED"), () => json({ detail: { code: "SUBTITLE_FILE_CORRUPT" } }, 409));
  const button = await screen.findByRole("button", { name: "자막(SRT) 다운로드" });
  const before = fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/rendering")).length;
  fireEvent.click(button);
  expect(await screen.findByText(/SRT 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다/)).toBeInTheDocument();
  await waitFor(() => expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/rendering")).length).toBeGreaterThan(before));

  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("<html>", { status: 200, headers: { "Content-Type": "text/html" } })));
  await expect(fetchRenderFile(srtUrl, "srt")).rejects.toMatchObject({ message: "다운로드 응답이 SRT 자막 파일이 아닙니다." });
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: { code: "SUBTITLE_FILE_NOT_FOUND" } }, 404)));
  await expect(fetchRenderFile(srtUrl)).rejects.toMatchObject({ code: "SUBTITLE_FILE_NOT_FOUND", status: 404 });
});
