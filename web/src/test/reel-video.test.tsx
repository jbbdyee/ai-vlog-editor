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
  modes: [{ key: "auto", label: "자동 (AI가 골라 줌)" }], paces: [{ key: "normal", label: "보통" }], lengths: [30], default_length: 30,
  text_templates: [{ key: "clean", label: "감성 글로우", hint: "얇은 글씨" }, { key: "neon", label: "네온", hint: "빛 번짐" }],
  text_colors: [{ key: "auto", label: "템플릿 기본" }, { key: "pink", label: "분홍" }],
  text_positions: [{ key: "auto", label: "템플릿 기본" }, { key: "bottom", label: "아래" }],
  text_sizes: [{ key: "normal", label: "보통" }, { key: "large", label: "크게" }],
};
const draft = {
  format: "short", mode: "try_on", mode_label: "옷 입어보기·하울", pace: "normal", pace_label: "보통", target_seconds: 30,
  total_seconds: 29.6, title: "이 3벌 중에 골라줘", engine: "llm:ollama/gemma3:4b", shot_count: 10, notes: [], fallback_reason: null,
  scenes: [{ shot_index: 1, source_video_id: source, source_filename: "a.mp4", start_seconds: 0, end_seconds: 2.5,
    caption: "핏 예쁘지?", label: "브라운 미니스커트", is_hook: true, shot_caption: "" }],
};
const draftStatus = { project_id: project, status: "COMPLETED", step: "완료", done: 0, total: 0, error_code: null, draft };
const noVideo = { project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, video: null };
const video = { duration_seconds: 29.6, file_size_bytes: 12 * 1024 * 1024, scene_count: 9, matches_draft: true,
  url: `/projects/${project}/reel-video/file?v=1700000000` };

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function show(videoAnswer: (init?: RequestInit) => Response) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/reel-options")) return Promise.resolve(response(options));
    if (url.endsWith("/reel-video")) return Promise.resolve(videoAnswer(init));
    return Promise.resolve(response(draftStatus));
  });
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><ReelDraftCard projectId={project} /></QueryClientProvider>);
  return fetcher;
}

describe("TODO 12 vertical reel video", () => {
  it("starts making the video from the draft and shows the progress", async () => {
    let started = false;
    const fetcher = show((init) => {
      if (init?.method === "POST") { started = true; return response({ ...noVideo, status: "RUNNING", step: "장면 잘라 세로로 맞추기", done: 2, total: 9 }, 202); }
      return response(started ? { ...noVideo, status: "RUNNING", step: "장면 잘라 세로로 맞추기", done: 2, total: 9 } : noVideo);
    });
    await userEvent.click(await screen.findByRole("button", { name: "세로 영상 만들기" }));
    expect(fetcher.mock.calls.some(([url, init]) => url === `/api/projects/${project}/reel-video` && init?.method === "POST")).toBe(true);
    expect(await screen.findByText(/장면 잘라 세로로 맞추기 · 2\/9개/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /세로 영상 만드는 중/ })).toBeDisabled();
  });

  it("plays the finished video, offers the download and warns when the draft is newer", async () => {
    show(() => response({ ...noVideo, status: "COMPLETED", video: { ...video, matches_draft: false } }));
    const panel = await screen.findByLabelText("세로 영상");
    const player = await within(panel).findByLabelText("완성된 세로 영상");
    expect(player).toHaveAttribute("src", `/api${video.url}`);
    expect(within(panel).getByRole("link", { name: "영상 내려받기" })).toHaveAttribute("href", `/api${video.url}`);
    expect(panel).toHaveTextContent("장면 9개 · 12.0MB");
    expect(panel).toHaveTextContent("예전 초안으로 만든 것");
    expect(within(panel).getByRole("button", { name: "세로 영상 다시 만들기" })).toBeEnabled();
  });

  it("sends the chosen text template, colour, place and size, starting from the last video's look", async () => {
    const fetcher = show((init) => init?.method === "POST"
      ? response({ ...noVideo, status: "RUNNING", step: "장면 잘라 세로로 맞추기" }, 202)
      : response({ ...noVideo, status: "COMPLETED", video: { ...video, text_style: { template: "neon", color: "auto", position: "auto", size: "normal" } } }));
    const templates = await screen.findByRole("group", { name: "글자 템플릿" });
    expect(await within(templates).findByRole("button", { name: /네온/, pressed: true })).toBeInTheDocument();
    await userEvent.click(within(templates).getByRole("button", { name: /감성 글로우/ }));
    await userEvent.click(within(screen.getByRole("group", { name: "포인트 색" })).getByRole("button", { name: "분홍" }));
    await userEvent.click(within(screen.getByRole("group", { name: "문구 위치" })).getByRole("button", { name: "아래" }));
    await userEvent.click(within(screen.getByRole("group", { name: "글자 크기" })).getByRole("button", { name: "크게" }));
    await userEvent.click(screen.getByRole("button", { name: "세로 영상 다시 만들기" }));
    const post = fetcher.mock.calls.find(([url, init]) => url === `/api/projects/${project}/reel-video` && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ text_style: { template: "clean", color: "pink", position: "bottom", size: "large" } });
  });

  it("explains a failure in plain words", async () => {
    show(() => response({ ...noVideo, status: "FAILED", error_code: "REEL_SOURCE_MISSING" }));
    expect(await screen.findByText("초안에 쓰인 원본 영상 파일을 찾지 못했습니다.")).toBeInTheDocument();
  });
});
