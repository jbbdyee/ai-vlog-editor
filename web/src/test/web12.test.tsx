import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const processing = { project_id: project, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: source, original_filename: "촬영 원본.mov", processing_status: "COMPLETED", stages: [] }] } as Parameters<typeof EditRender>[0]["processing"];
function setup(initial: string[] = [b, a], historyItems: unknown[] = []) {
  let saved = initial;
  let fail = false;
  let release: (() => void) | undefined;
  const fetcher = vi.fn((url: string, options?: RequestInit) => {
    if (url.endsWith("/scene-candidates")) return Promise.resolve(response({ project_id: project, candidates: [
      { candidate_id: a, source_video_id: source, start_seconds: 1.1, end_seconds: 2.35, evidence: [] },
      { candidate_id: b, source_video_id: source, start_seconds: 4, end_seconds: 6.5, evidence: [] },
    ] }));
    if (url.endsWith("/scene-edit-plan")) {
      if (options?.method === "PUT") {
        if (fail) return Promise.resolve(response({ detail: { code: "SAVE_FAILED" } }, 500));
        return new Promise<Response>((resolve) => { release = () => { saved = (JSON.parse(options.body as string) as { candidate_ids: string[] }).candidate_ids; resolve(response({ project_id: project, candidate_ids: saved, invalid_candidate_ids: [] })); }; });
      }
      return Promise.resolve(response({ project_id: project, candidate_ids: saved, invalid_candidate_ids: [] }));
    }
    if (url.includes("/renders?")) return Promise.resolve(response({ project_id: project, items: historyItems, next_cursor: null }));
    return Promise.resolve(response({ project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null }));
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const view = render(<QueryClientProvider client={client}><EditRender projectId={project} processing={processing} /></QueryClientProvider>);
  return { ...view, fetcher, release: () => release?.(), setFail: () => { fail = true; }, client };
}
beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("WEB-12 saved plan review", () => {
  it("shows saved order, source, durations and sum, without starting a render", async () => {
    const app = setup();
    const review = await screen.findByRole("region", { name: "렌더 전 편집 계획 검토" });
    await waitFor(() => expect(within(review).getByText("저장된 장면 2개 · 예상 길이 3.75초")).toBeInTheDocument());
    const rows = within(review).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("4.00–6.50초 · 길이 2.50초");
    expect(rows[1]).toHaveTextContent("1.10–2.35초 · 길이 1.25초");
    expect(rows[0]).toHaveTextContent("촬영 원본.mov");
    expect(within(review).getByRole("link", { name: "장면 선택·순서 수정" })).toHaveAttribute("href", "#scene-selection");
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeEnabled();
    expect(app.fetcher.mock.calls.some(([url]) => String(url).endsWith("/render") && !String(url).endsWith("/rendering"))).toBe(false);
  });

  it("blocks render for dirty, pending and failed save; reviews the saved response after retry", async () => {
    const app = setup();
    await screen.findByText("저장된 장면 2개 · 예상 길이 3.75초");
    await userEvent.click(screen.getByRole("button", { name: "2번 위로" }));
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
    expect(screen.queryByRole("list", { name: "저장된 최종 장면 순서" })).not.toBeInTheDocument();
    app.setFail();
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    await screen.findByText(/SAVE_FAILED/);
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
    app.unmount();
    const retry = setup();
    await screen.findByText("저장된 장면 2개 · 예상 길이 3.75초");
    await userEvent.click(screen.getByRole("button", { name: "2번 위로" }));
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    expect(screen.getByText("편집 계획 저장 중입니다. 완료 후 검토할 수 있습니다.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
    retry.release();
    await waitFor(() => expect(screen.getByText("저장된 장면 2개 · 예상 길이 3.75초")).toBeInTheDocument());
    const rows = within(screen.getByRole("list", { name: "저장된 최종 장면 순서" })).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("1.10–2.35초");
  });

  it("keeps empty saved plan in guidance state", async () => {
    setup([]);
    expect(await screen.findByText("저장된 장면이 없습니다. 장면을 선택하고 계획을 저장해 주세요.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  });

  it("keeps previous render history distinct from an empty current plan", async () => {
    setup([], [{ project_id: project, render_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", status: "COMPLETED", download_available: false }]);
    expect(await screen.findByText("저장된 장면이 없습니다. 장면을 선택하고 계획을 저장해 주세요.")).toBeInTheDocument();
    expect(await screen.findByText(/기본 파일 누락/)).toBeInTheDocument();
    expect(screen.getByText("아래 렌더 기록과 결과는 이전 실행의 산출물이며 현재 계획의 예상 결과가 아닙니다.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  });
});
