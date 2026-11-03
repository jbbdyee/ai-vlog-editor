import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><EditRender projectId={project} /></QueryClientProvider>);
}
function mockApi(initial = [a, b]) {
  let saved = initial;
  let mismatch = false;
  let failure = false;
  const puts: string[][] = [];
  const fetcher = vi.fn((url: string, options?: RequestInit) => {
    if (url.endsWith("/scene-candidates")) return Promise.resolve(json(200, { project_id: project, candidates: [a, b].map((id, index) => ({ candidate_id: id, source_video_id: source, start_seconds: index + 1, end_seconds: index + 2, evidence: [] })) }));
    if (url.endsWith("/scene-edit-plan")) {
      if (options?.method === "PUT") {
        const ids = (JSON.parse(options.body as string) as { candidate_ids: string[] }).candidate_ids;
        puts.push(ids);
        if (failure) return Promise.resolve(json(500, { detail: { code: "SCENE_EDIT_PLAN_SAVE_FAILED" } }));
        if (!mismatch) saved = ids;
      }
      return Promise.resolve(json(200, { project_id: project, candidate_ids: saved, invalid_candidate_ids: [] }));
    }
    if (url.endsWith("/renders")) return Promise.resolve(json(200, { project_id: project, items: [], next_cursor: null }));
    return Promise.resolve(json(200, { project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null }));
  });
  vi.stubGlobal("fetch", fetcher);
  return { puts, setFailure: (value: boolean) => { failure = value; }, setMismatch: (value: boolean) => { mismatch = value; } };
}
beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("WEB-11 scene selection and order", () => {
  it("shows selection, touch sized boundary controls and saves the changed order", async () => {
    const api = mockApi();
    const view = mount();
    expect(await screen.findByText("선택한 장면 2개 / 후보 2개")).toBeInTheDocument();
    expect(screen.getAllByText("선택됨")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "1번 위로" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "2번 아래로" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "1번 위로" })).toHaveClass("min-h-11", "min-w-11");
    await userEvent.click(screen.getByRole("button", { name: "2번 위로" }));
    expect(screen.getByText("저장되지 않은 변경사항이 있습니다.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    await waitFor(() => expect(api.puts).toEqual([[b, a]]));
    expect(await screen.findByText("편집 계획 저장 완료.")).toBeInTheDocument();
    view.unmount();
    mount();
    const list = await screen.findByRole("list", { name: "선택한 장면 순서" });
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(2));
    const items = within(list).getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("2.00–3.00초");
    expect(items[1]).toHaveTextContent("1.00–2.00초");
  });

  it("can remove every scene and persist an empty plan without enabling render", async () => {
    const api = mockApi();
    mount();
    const selected = await screen.findByRole("list", { name: "선택한 장면 순서" });
    await waitFor(() => expect(within(selected).getAllByRole("listitem")).toHaveLength(2));
    await userEvent.click(within(selected).getAllByRole("button", { name: "선택 해제" })[0]);
    await userEvent.click(within(selected).getByRole("button", { name: "선택 해제" }));
    expect(screen.getByText("선택한 장면 0개 / 후보 2개")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    await waitFor(() => expect(api.puts).toEqual([[]]));
    expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  });

  it("keeps the draft after failure or a mismatched server response, then retries", async () => {
    const api = mockApi();
    api.setFailure(true);
    mount();
    await screen.findByText("선택한 장면 2개 / 후보 2개");
    await userEvent.click(screen.getByRole("button", { name: "2번 위로" }));
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    expect(await screen.findByText(/SCENE_EDIT_PLAN_SAVE_FAILED/)).toBeInTheDocument();
    api.setFailure(false); api.setMismatch(true);
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    expect(await screen.findByText(/요청한 장면 순서를 저장했는지 확인할 수 없습니다/)).toBeInTheDocument();
    const selected = screen.getByRole("list", { name: "선택한 장면 순서" });
    expect(within(selected).getAllByRole("listitem")[0]).toHaveTextContent("2.00–3.00초");
    api.setMismatch(false);
    await userEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
    expect(await screen.findByText("편집 계획 저장 완료.")).toBeInTheDocument();
    expect(api.puts).toEqual([[b, a], [b, a], [b, a]]);
  });
});
