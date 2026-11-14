import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReelDraftCard } from "@/features/reels/reel-draft";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const options = {
  formats: [{ key: "short", label: "숏폼 (릴스·쇼츠)" }], modes: [{ key: "auto", label: "자동" }],
  paces: [{ key: "normal", label: "보통" }], lengths: [30], default_length: 30,
};
const scene = (index: number, caption: string, end = index * 4 + 2) => ({
  shot_index: index, source_video_id: source, source_filename: "dance.mp4", start_seconds: index * 4, end_seconds: end,
  caption, label: "", is_hook: index === 5, shot_caption: "연습실에서 춤을 춘다",
});
const draft = (second = scene(1, "처음 뵙겠습니다")) => ({
  format: "short", mode: "challenge", mode_label: "도전기", pace: "normal", pace_label: "보통", target_seconds: 30,
  total_seconds: 6, title_lead: "", title: "첫 댄스곡 도전기", engine: "llm:ollama/gemma3:4b", shot_count: 5, notes: [], fallback_reason: null,
  scenes: [scene(5, "제목 장면"), second, scene(2, "카운트 맞추는 중")],
});
const status = (body: object) => ({ project_id: project, status: "COMPLETED", step: "완료", done: 0, total: 0, error_code: null, ...body });

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("TODO 16 reel chat edits", () => {
  it("sends the sentence with the picked scene, shows what changed and can undo", async () => {
    const sent: unknown[] = [];
    let undone = false;
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/reel-options")) return Promise.resolve(response(options));
      if (url.endsWith("/reel-video")) return Promise.resolve(response({ project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, video: null }));
      if (url.endsWith("/reel-draft/edit")) {
        sent.push(JSON.parse(String(init?.body)));
        return Promise.resolve(response(status({ draft: draft(scene(1, "처음 뵙겠습니다", 7)), can_undo: true, done_edits: ["2번 장면 2.0초 → 3.0초"], skipped_edits: [] })));
      }
      if (url.endsWith("/reel-draft/undo")) { undone = true; return Promise.resolve(response(status({ draft: draft(), can_undo: false }))); }
      return Promise.resolve(response(status({ draft: draft() })));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReelDraftCard projectId={project} /></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "2번 장면 고르기" }));
    expect(screen.getByText("2번")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "더 길게" }));
    expect(await screen.findByText("✓ 2번 장면 2.0초 → 3.0초")).toBeInTheDocument();
    expect(sent).toEqual([{ message: "여기 더 길게", selected: 2 }]);

    await userEvent.type(screen.getByLabelText("고칠 내용"), "3번 자막 빼줘");
    await userEvent.click(screen.getByRole("button", { name: "고치기" }));
    expect(sent[1]).toEqual({ message: "3번 자막 빼줘", selected: 2 });

    await userEvent.click(screen.getByRole("button", { name: "되돌리기" }));
    expect(await screen.findByText("✓ 고치기 전 초안으로 되돌렸어요")).toBeInTheDocument();
    expect(undone).toBe(true);
  });

  it("explains a sentence it could not read", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/reel-options")) return Promise.resolve(response(options));
      if (url.endsWith("/reel-video")) return Promise.resolve(response({ project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, video: null }));
      if (url.endsWith("/reel-draft/edit")) return Promise.resolve(response({ detail: { code: "REEL_EDIT_NOT_UNDERSTOOD", message: "x" } }, 422));
      return Promise.resolve(response(status({ draft: draft() })));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><ReelDraftCard projectId={project} /></QueryClientProvider>);
    await userEvent.type(await screen.findByLabelText("고칠 내용"), "좀 신나게");
    await userEvent.click(screen.getByRole("button", { name: "고치기" }));
    expect(await screen.findByText(/알아듣지 못했어요/)).toBeInTheDocument();
  });
});
