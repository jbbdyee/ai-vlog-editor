import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import { downloadPath, fetchRenderFile, type RenderStatus } from "@/api/edit-render";

const id = "11111111-1111-4111-8111-111111111111";
const other = "33333333-3333-4333-8333-333333333333";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const gone = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const hex = renderId.replaceAll("-", "");
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const candidate = (candidateId: string, start: number) => ({ candidate_id: candidateId, source_video_id: b, start_seconds: start, end_seconds: start + 1, evidence: [] });
const status = (projectId = id, runStatus: RenderStatus["status"] = "NOT_STARTED"): RenderStatus => ({ project_id: projectId, status: runStatus, render_id: runStatus === "COMPLETED" ? renderId : null, is_active: runStatus === "QUEUED" || runStatus === "RUNNING", succeeded: runStatus === "COMPLETED", failed: runStatus === "FAILED", safe_error_code: runStatus === "FAILED" ? "PROJECT_RENDER_FAILED" : null, download_available: runStatus === "COMPLETED", output: runStatus === "COMPLETED" ? { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100, download_url: `/projects/${projectId}/renders/${hex}/download` } : null, hard_subtitle_status: runStatus === "COMPLETED" ? "AVAILABLE" : "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: runStatus === "COMPLETED", hard_subtitle_download_url: runStatus === "COMPLETED" ? `/projects/${projectId}/renders/${hex}/subtitled/download` : null });
function mount(projectId = id) { const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } }); return render(<QueryClientProvider client={client}><EditRender key={projectId} projectId={projectId} /></QueryClientProvider>); }
beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("WEB-03 edit and render", () => {
  it("selects, reorders, saves and keeps a failed draft", async () => {
    let saved: string[] = []; let fail = true;
    const fetcher = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/scene-candidates")) return Promise.resolve(json(200, { project_id: id, candidates: [candidate(a, 1), candidate(b, 3)] }));
      if (url.endsWith("/scene-edit-plan") && init?.method === "PUT") { if (fail) return Promise.resolve(json(500, { detail: { code: "SCENE_EDIT_PLAN_SAVE_FAILED" } })); saved = JSON.parse(init.body as string).candidate_ids; return Promise.resolve(json(200, { project_id: id, candidate_ids: saved, invalid_candidate_ids: [] })); }
      if (url.endsWith("/scene-edit-plan")) return Promise.resolve(json(200, { project_id: id, candidate_ids: saved, invalid_candidate_ids: [] }));
      return Promise.resolve(json(200, status()));
    });
    vi.stubGlobal("fetch", fetcher); mount();
    const select = await screen.findAllByRole("button", { name: "장면 선택" });
    await userEvent.click(select[0]); await userEvent.click(screen.getByRole("button", { name: "장면 선택" }));
    await userEvent.click(screen.getByRole("button", { name: "2번 위로" }));
    expect(within(screen.getByRole("list", { name: "선택한 장면 순서" })).getAllByRole("listitem")[0]).toHaveTextContent(b);
    expect(screen.getByText("저장되지 않은 변경사항이 있습니다.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    expect(await screen.findByText(/SCENE_EDIT_PLAN_SAVE_FAILED/)).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "선택한 장면 순서" })).getAllByRole("listitem")).toHaveLength(2);
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    await waitFor(() => expect(saved).toEqual([b, a]));
    expect(await screen.findByText("편집 계획 저장 완료.")).toBeInTheDocument();
  });

  it("shows invalid saved IDs and requires explicit correction", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/scene-candidates") ? { project_id: id, candidates: [candidate(a, 1)] } : url.endsWith("/scene-edit-plan") ? { project_id: id, candidate_ids: [gone], invalid_candidate_ids: [gone] } : status()))));
    mount();
    expect(await screen.findByText(`무효 후보 · ${gone}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "무효 후보 제외" }));
    expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "장면 선택" }));
    expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeEnabled();
  });

  it("does not trust cross-project or fabricated download URLs and handles absent results", () => {
    const completed = status(id, "COMPLETED");
    expect(downloadPath(completed, id, "plain")).toBe(`/projects/${id}/renders/${hex}/download`);
    expect(downloadPath(completed, id, "subtitled")).toBe(`/projects/${id}/renders/${hex}/subtitled/download`);
    expect(downloadPath(completed, other, "plain")).toBeNull();
    expect(downloadPath({ ...completed, output: { ...completed.output!, download_url: "/evil" } }, id, "plain")).toBeNull();
    expect(downloadPath({ ...completed, hard_subtitle_download_available: false }, id, "subtitled")).toBeNull();
    expect(downloadPath(status(), id, "plain")).toBeNull();
  });

  it("rejects missing downloads, wrong MIME and empty MP4", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json(404, { detail: { code: "RENDER_NOT_FOUND" } })).mockResolvedValueOnce(new Response("bad", { headers: { "Content-Type": "text/html" } })).mockResolvedValueOnce(new Response("", { headers: { "Content-Type": "video/mp4" } })));
    await expect(fetchRenderFile("/file")).rejects.toMatchObject({ code: "RENDER_NOT_FOUND" });
    await expect(fetchRenderFile("/file")).rejects.toThrow("MP4가 아닙니다");
    await expect(fetchRenderFile("/file")).rejects.toThrow("비어 있습니다");
  });

  it("blocks a duplicate request during an active render", async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/scene-candidates") ? { project_id: id, candidates: [candidate(a, 1)] } : url.endsWith("/scene-edit-plan") ? { project_id: id, candidate_ids: [a], invalid_candidate_ids: [] } : status(id, "RUNNING"))));
    vi.stubGlobal("fetch", fetcher); mount();
    expect(await screen.findByText("렌더 진행 중")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "렌더링 중…" })).toBeDisabled();
    expect(fetcher.mock.calls.filter((call) => call[1]?.method === "POST")).toHaveLength(0);
  });

  it("shows render failure and keeps base download when subtitles are missing", async () => {
    let run: RenderStatus = status(id, "FAILED");
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/scene-candidates") ? { project_id: id, candidates: [candidate(a, 1)] } : url.endsWith("/scene-edit-plan") ? { project_id: id, candidate_ids: [a], invalid_candidate_ids: [] } : run)));
    vi.stubGlobal("fetch", fetcher);
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><EditRender projectId={id} /></QueryClientProvider>);
    expect(await screen.findByText("렌더 실패")).toBeInTheDocument();
    expect(screen.getByText(/PROJECT_RENDER_FAILED/)).toBeInTheDocument();
    run = { ...status(id, "COMPLETED"), hard_subtitle_status: "FAILED", hard_subtitle_error_code: "SUBTITLE_RENDER_FAILED", hard_subtitle_download_available: false, hard_subtitle_download_url: null };
    await userEvent.click(screen.getByRole("button", { name: "상태 다시 조회" }));
    expect(await screen.findByText(/SUBTITLE_RENDER_FAILED/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeDisabled();
  });

  it("restores a persisted plan on new mount and isolates another project", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      const projectId = url.includes(other) ? other : id;
      return Promise.resolve(json(200, url.endsWith("/scene-candidates") ? { project_id: projectId, candidates: projectId === id ? [candidate(a, 1)] : [] } : url.endsWith("/scene-edit-plan") ? { project_id: projectId, candidate_ids: projectId === id ? [a] : [], invalid_candidate_ids: [] } : status(projectId)));
    }));
    const first = mount();
    expect(await screen.findByText("저장된 편집 계획입니다.")).toBeInTheDocument();
    first.unmount();
    mount(other);
    expect(await screen.findByText("선택할 장면 후보가 없습니다. 장면 분석 결과를 확인해 주세요.")).toBeInTheDocument();
    expect(screen.queryByText(a)).not.toBeInTheDocument();
  });
});
