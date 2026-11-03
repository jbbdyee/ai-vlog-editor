import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import { fetchRenderFile, renderFileProblem, type IntegrityStatus, type RenderStatus } from "@/api/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const good = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const corrupt = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const legacy = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee";
const failed = "ffffffff-ffff-4fff-8fff-ffffffffffff";
const hex = (id: string) => id.replaceAll("-", "");
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const codes: Record<IntegrityStatus, string | null> = {
  VERIFIED: null, MISSING: "RENDER_FILE_MISSING", CORRUPT: "RENDER_FILE_CORRUPT", UNVERIFIED: "RENDER_FILE_UNVERIFIED",
};

function completed(renderId: string, base: IntegrityStatus, hard: IntegrityStatus | "BASE" = "VERIFIED", srt: IntegrityStatus | null = "VERIFIED"): RenderStatus {
  const ok = base === "VERIFIED";
  const hardOk = ok && hard === "VERIFIED";
  return {
    project_id: project, status: "COMPLETED", render_id: renderId, is_active: false, succeeded: true, failed: false,
    safe_error_code: codes[base], download_available: ok,
    output: { filename: "final.mp4", duration_seconds: 4, video_codec: "h264", audio_codec: "aac", file_size_bytes: 10,
      download_url: ok ? `/projects/${project}/renders/${hex(renderId)}/download` : null },
    hard_subtitle_status: !ok ? "BASE_UNAVAILABLE" : hard === "VERIFIED" ? "AVAILABLE" : hard === "BASE" ? "BASE_UNAVAILABLE" : hard,
    hard_subtitle_error_code: null, hard_subtitle_download_available: hardOk,
    hard_subtitle_download_url: hardOk ? `/projects/${project}/renders/${hex(renderId)}/subtitled/download` : null,
    integrity_status: base, subtitle_integrity_status: srt, hard_subtitle_integrity_status: ok && hard !== "BASE" ? hard : null,
  };
}

const failedRun: RenderStatus = {
  project_id: project, status: "FAILED", render_id: failed, is_active: false, succeeded: false, failed: true,
  safe_error_code: "CONCAT_FAILED", download_available: false, output: null, hard_subtitle_status: "NOT_STARTED",
  hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null,
  integrity_status: null, subtitle_integrity_status: null, hard_subtitle_integrity_status: null,
};

function mount(current: RenderStatus, items: RenderStatus[], download?: (url: string) => Response) {
  const fetchMock = vi.fn().mockImplementation((url: string) => Promise.resolve(
    download && url.includes("/download") ? download(url) :
      json(url.includes("/renders?limit=") ? { project_id: project, items, next_cursor: null } :
        url.endsWith("/scene-candidates") ? { project_id: project, candidates: [] } :
          url.endsWith("/scene-edit-plan") ? { project_id: project, candidate_ids: [], invalid_candidate_ids: [] } : current)));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EditRender projectId={project} /></QueryClientProvider>);
  return fetchMock;
}
const statusCalls = (mock: ReturnType<typeof vi.fn>) => mock.mock.calls.filter(([url]) => String(url).endsWith("/rendering")).length;

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("explains a SHA-256 mismatch, blocks playback and keeps the record listed", async () => {
  mount(completed(corrupt, "CORRUPT"), [completed(corrupt, "CORRUPT")]);
  expect(await screen.findByText(/기록한 SHA-256과 다릅니다/)).toBeInTheDocument();
  expect(screen.queryByLabelText("최종 영상 미리보기")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeDisabled();
  expect(screen.getByText(/기본 영상 확인 실패로 자막 영상도 제공 중지/)).toBeInTheDocument();
  expect(await screen.findByText(/기본 파일 변형 감지/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이 결과 보기" })).toBeDisabled();
});

it("distinguishes missing, corrupt and hash-less history entries while a previous success stays selectable", async () => {
  mount(failedRun, [failedRun, completed(corrupt, "CORRUPT"), completed(legacy, "UNVERIFIED"),
    completed(good, "MISSING"), completed("dddddddd-dddd-4ddd-8ddd-dddddddddddd", "VERIFIED")]);
  expect(await screen.findByText("렌더 실패")).toBeInTheDocument();
  expect(await screen.findByText(/기본 파일 변형 감지/)).toBeInTheDocument();
  expect(screen.getByText(/무결성 기록 없음/)).toBeInTheDocument();
  expect(screen.getByText(/기본 파일 누락/)).toBeInTheDocument();
  const buttons = screen.getAllByRole("button", { name: "이 결과 보기" });
  expect(buttons.map((button) => (button as HTMLButtonElement).disabled)).toEqual([true, true, true, true, false]);
  fireEvent.click(buttons[4]);
  expect(await screen.findByLabelText("자막 없는 최종 영상 재생")).toBeInTheDocument();
});

it("shows the hash-less legacy explanation instead of a generic missing file", async () => {
  mount(completed(legacy, "UNVERIFIED"), [completed(legacy, "UNVERIFIED")]);
  expect(await screen.findByText(/SHA-256\)이 도입되기 전에 완료된 렌더/)).toBeInTheDocument();
  expect(screen.getByText(/렌더 기록은 그대로 보존됩니다/)).toBeInTheDocument();
});

it("keeps the base MP4 when only the subtitled MP4 or SRT changed", async () => {
  mount(completed(good, "VERIFIED", "CORRUPT", "CORRUPT"), [completed(good, "VERIFIED", "CORRUPT", "CORRUPT")]);
  expect(await screen.findByText(/하드 자막 파일 변형 감지/)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeDisabled();
  expect(screen.getByLabelText("자막 없는 최종 영상 재생")).toBeInTheDocument();
  expect(screen.getByText(/SRT 파일이 렌더 완료 때와 다릅니다/)).toBeInTheDocument();
});

it("reports a blocked download by code and re-reads the render state", async () => {
  const fetchMock = mount(completed(good, "VERIFIED"), [completed(good, "VERIFIED")],
    () => json({ detail: { code: "RENDER_FILE_CORRUPT" } }, 409));
  const button = await screen.findByRole("button", { name: "자막 없는 MP4 다운로드" });
  const before = statusCalls(fetchMock);
  fireEvent.click(button);
  expect(await screen.findByText(/렌더 완료 때와 달라 다운로드를 차단했습니다\. \(RENDER_FILE_CORRUPT\)/)).toBeInTheDocument();
  await waitFor(() => expect(statusCalls(fetchMock)).toBeGreaterThan(before));
});

it("re-reads the render state when preview playback is refused", async () => {
  const fetchMock = mount(completed(good, "VERIFIED"), [completed(good, "VERIFIED")]);
  const video = await screen.findByLabelText("자막 없는 최종 영상 재생");
  const before = statusCalls(fetchMock);
  fireEvent.error(video);
  expect(await screen.findByText(/결과 영상을 재생할 수 없습니다/)).toBeInTheDocument();
  await waitFor(() => expect(statusCalls(fetchMock)).toBeGreaterThan(before));
});

it("maps integrity codes for both download kinds and stays compatible with older responses", async () => {
  for (const [code, text] of [["SUBTITLED_RENDER_CORRUPT", "자막 MP4 파일이 렌더 완료 때와 달라"], ["SUBTITLED_RENDER_UNVERIFIED", "무결성 기록이 없는 자막 MP4"], ["RENDER_FILE_UNVERIFIED", "무결성 기록이 없는 과거 렌더"]] as const) {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: { code } }, 409)));
    await expect(fetchRenderFile("/file")).rejects.toMatchObject({ code, status: 409, message: expect.stringContaining(text) });
  }
  const old = { ...completed(good, "MISSING") } as Partial<RenderStatus>;
  delete old.integrity_status; delete old.subtitle_integrity_status; delete old.hard_subtitle_integrity_status;
  old.safe_error_code = null;
  expect(renderFileProblem(old as RenderStatus)?.short).toBe("기본 파일 누락");
  expect(renderFileProblem(completed(good, "VERIFIED"))).toBeNull();
});
