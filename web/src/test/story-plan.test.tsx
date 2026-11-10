import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import { StoryDirectionCard, toPlanDraft, type StoryPlanDraft } from "@/features/story/story-direction";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const c = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const gone = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const scene = (id: string, start: number) => ({ candidate_id: id, source_video_id: source, source_filename: "IMG_0001.MOV", start_seconds: start, end_seconds: start + 2, clip_start_seconds: start, clip_end_seconds: start + 2 });
const direction = {
  project_id: project, title: "도쿄 여행", summary: "도착부터 야경까지", engine: "rule", notes: [], fallback_reason: null,
  target_minutes: 1, recommended_minutes: 1, length_reason: "기본", length_options: [1, 3], total_seconds: 6, max_seconds: 6, footage_seconds: 60,
  chapters: [
    { title: "도착", description: "공항", reason: "시작", scenes: [scene(c, 9), scene(a, 1)], total_seconds: 4 },
    { title: "야경", description: "밤", reason: "마무리", scenes: [scene(b, 4)], total_seconds: 2 },
  ],
};

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("story direction -> edit plan", () => {
  it("flattens chapters in order with a chapter label per scene", () => {
    const draft = toPlanDraft(direction);
    expect(draft.candidateIds).toEqual([c, a, b]);
    expect(draft.chapterById[a]).toBe("챕터 1. 도착");
    expect(draft.chapterById[b]).toBe("챕터 2. 야경");
  });

  it("the card button hands the draft to the page", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(direction)));
    const onApply = vi.fn();
    const client = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><StoryDirectionCard projectId={project} onApply={onApply} /></QueryClientProvider>);
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    await userEvent.click(await screen.findByRole("button", { name: /이 방향으로 편집 계획 만들기/ }));
    expect((onApply.mock.calls[0][0] as StoryPlanDraft).candidateIds).toEqual([c, a, b]);
  });

  it("fills the unsaved edit plan in chapter order and drops unknown scenes", async () => {
    const fetcher = vi.fn((url: string, _options?: RequestInit) => {
      if (url.endsWith("/scene-candidates")) return Promise.resolve(response({ project_id: project, candidates: [a, b, c].map((id, i) => ({ candidate_id: id, source_video_id: source, start_seconds: i * 3, end_seconds: i * 3 + 2, evidence: [] })) }));
      if (url.endsWith("/scene-edit-plan")) return Promise.resolve(response({ project_id: project, candidate_ids: [b], invalid_candidate_ids: [] }));
      if (url.includes("/renders?")) return Promise.resolve(response({ project_id: project, items: [], next_cursor: null }));
      return Promise.resolve(response({ project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null }));
    });
    vi.stubGlobal("fetch", fetcher);
    const draft: StoryPlanDraft = { candidateIds: [c, gone, a, b], chapterById: { [c]: "챕터 1. 도착", [a]: "챕터 1. 도착", [b]: "챕터 2. 야경" }, nonce: 1 };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><EditRender projectId={project} storyDraft={draft} /></QueryClientProvider>);
    expect(await screen.findByText(/장면 3개를 챕터 순서대로 채웠습니다\. 현재 후보에 없는 장면 1개는 뺐습니다\./)).toBeInTheDocument();
    const rows = within(screen.getByRole("list", { name: "선택한 장면 순서" })).getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent("챕터 1. 도착");
    expect(rows[0]).toHaveTextContent("6.00–8.00초");
    expect(rows[1]).toHaveTextContent("0.00–2.00초");
    expect(rows[2]).toHaveTextContent("챕터 2. 야경");
    expect(screen.getByText("저장되지 않은 변경사항이 있습니다.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeEnabled());
    expect(fetcher.mock.calls.some(([, options]) => options?.method === "PUT")).toBe(false);
  });
});
