import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReelDraftCard } from "@/features/reels/reel-draft";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const options = {
  formats: [{ key: "short", label: "숏폼 (릴스·쇼츠)" }, { key: "long", label: "롱폼 (유튜브)" }],
  modes: [{ key: "auto", label: "자동 (AI가 골라 줌)" }, { key: "challenge", label: "도전기·연습 기록" }, { key: "try_on", label: "옷 입어보기·하울" }],
  paces: [{ key: "relaxed", label: "여유있게 (장면당 약 4초)" }, { key: "normal", label: "보통 (장면당 약 2.5초)" }, { key: "fast", label: "빠르게 (장면당 약 1.8초)" }],
  lengths: [15, 30, 45], default_length: 30,
};
const scene = (index: number, caption: string, hook = false, label = "") => ({
  shot_index: index, source_video_id: source, source_filename: "dance.mp4", start_seconds: index * 4, end_seconds: index * 4 + 2.5,
  caption, label, is_hook: hook, shot_caption: "연습실에서 춤을 춘다",
});
const draft = {
  format: "short", mode: "challenge", mode_label: "도전기·연습 기록", pace: "fast", pace_label: "빠르게", target_seconds: 15,
  total_seconds: 15.2, title: "첫 댄스곡 도전기", engine: "llm:ollama/gemma3:4b", shot_count: 12, notes: [], fallback_reason: null,
  scenes: [scene(5, "폭풍 칭찬 받았어요", true), scene(1, "처음 뵙겠습니다"), scene(2, "카운트 맞추는 중")],
};
const idle = { project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, draft: null };

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ReelDraftCard projectId={project} /></QueryClientProvider>);
}

describe("TODO 10 reel draft", () => {
  it("sends the chosen mode, pace and length, then shows the draft with the hook first", async () => {
    let made = false;
    const fetcher = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/reel-options")) return Promise.resolve(response(options));
      if (init?.method === "POST") { made = true; return Promise.resolve(response({ ...idle, status: "COMPLETED", step: "완료", draft }, 202)); }
      return Promise.resolve(response(made ? { ...idle, status: "COMPLETED", draft } : idle));
    });
    vi.stubGlobal("fetch", fetcher);
    show();
    await userEvent.click(await screen.findByRole("button", { name: "도전기·연습 기록" }));
    await userEvent.click(screen.getByRole("button", { name: /빠르게/ }));
    await userEvent.click(screen.getByRole("button", { name: "15초" }));
    await userEvent.click(screen.getByRole("button", { name: "릴스 초안 만들기" }));
    const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
    expect(JSON.parse(post[1]!.body as string)).toEqual({ format: "short", mode: "challenge", pace: "fast", target_seconds: 15 });
    const result = await screen.findByLabelText("릴스 초안");
    expect(within(result).getByText("첫 댄스곡 도전기")).toBeInTheDocument();
    const rows = within(result).getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("맨 앞 장면");
    expect(rows[0]).toHaveTextContent("폭풍 칭찬 받았어요");
    expect(rows[1]).toHaveTextContent("처음 뵙겠습니다");
    expect(result).toHaveTextContent("AI 초안 (ollama/gemma3:4b)");
  });

  it("long-form points to the story direction instead of making a reel", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(url.endsWith("/reel-options") ? options : idle))));
    show();
    await userEvent.click(await screen.findByRole("button", { name: "롱폼 (유튜브)" }));
    expect(screen.getByRole("link", { name: "추천 편집 방향" })).toHaveAttribute("href", "#story-direction");
    expect(screen.queryByRole("button", { name: "릴스 초안 만들기" })).not.toBeInTheDocument();
  });

  it("shows progress while shots are being read", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(url.endsWith("/reel-options") ? options
      : { ...idle, status: "RUNNING", step: "장면 나누고 화면 설명하기", done: 3, total: 12 }))));
    show();
    expect(await screen.findByText(/장면 나누고 화면 설명하기 · 3\/12개/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /릴스 초안 만드는 중/ })).toBeDisabled();
  });
});
