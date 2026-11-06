import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StoryDirectionCard } from "@/features/story/story-direction";

const id = "11111111-1111-4111-8111-111111111111";
const scene = { candidate_id: "33333333-3333-4333-8333-333333333333", source_video_id: "22222222-2222-4222-8222-222222222222", source_filename: "IMG_0001.MOV", start_seconds: 1, end_seconds: 6.5 };
const direction = {
  project_id: id, title: "도쿄 여행", summary: "도착부터 야경까지", engine: "llm:ollama/gemma3:4b", fallback_reason: null,
  notes: ["추천 흐름에 넣지 않은 장면이 2개 있습니다."],
  chapters: [{ title: "도착", description: "공항과 호텔", reason: "여행의 시작", scenes: [scene], total_seconds: 5.5 }],
};

function json(status: number, data: unknown) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function renderCard(onPreview = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoryDirectionCard projectId={id} onPreview={onPreview} /></QueryClientProvider>);
  return onPreview;
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recommended story direction", () => {
  it("asks the server and shows chapters with scenes that can be previewed", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, direction)); vi.stubGlobal("fetch", fetcher);
    const onPreview = renderCard();
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText("도쿄 여행")).toBeTruthy();
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${id}/story-direction`, expect.objectContaining({ method: "POST" }));
    expect(screen.getByText(/챕터 1\. 도착/)).toBeTruthy();
    expect(screen.getByText("이유: 여행의 시작")).toBeTruthy();
    expect(screen.getByText(/AI 추천 \(ollama\/gemma3:4b\)/)).toBeTruthy();
    expect(screen.getByText("추천 흐름에 넣지 않은 장면이 2개 있습니다.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "미리보기" }));
    expect(onPreview).toHaveBeenCalledWith({ candidateId: scene.candidate_id, sourceId: scene.source_video_id, start: 1, end: 6.5 });
  });

  it("explains when scene analysis has not run yet", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(409, { detail: { code: "NO_SCENE_CANDIDATES", message: "x" } })));
    renderCard();
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText("장면 후보가 없습니다. 먼저 장면 분석을 실행해 주세요.")).toBeTruthy();
  });
});
