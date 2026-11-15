import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StoryDirectionCard } from "@/features/story/story-direction";

const id = "11111111-1111-4111-8111-111111111111";
const scene = { candidate_id: "33333333-3333-4333-8333-333333333333", source_video_id: "22222222-2222-4222-8222-222222222222", source_filename: "IMG_0001.MOV", start_seconds: 1, end_seconds: 6.5, clip_start_seconds: 0, clip_end_seconds: 20 };
const direction = {
  project_id: id, title: "도쿄 여행", summary: "도착부터 야경까지", engine: "llm:ollama/gemma3:4b", fallback_reason: null,
  notes: ["추천 흐름에 넣지 않은 장면이 2개 있습니다."],
  chapters: [{ title: "도착", description: "공항과 호텔", reason: "여행의 시작", scenes: [scene], total_seconds: 20 }],
  target_minutes: 8, recommended_minutes: 8, length_reason: "레슨이라 핵심 동작 위주", length_options: [3, 5, 8, 10, 15, 20],
  total_seconds: 472, max_seconds: 900, footage_seconds: 1860,
};

function json(status: number, data: unknown) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function renderCard(onPreview = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><StoryDirectionCard projectId={id} onPreview={onPreview} /></QueryClientProvider>);
  return onPreview;
}

// TODO 23: the card also loads the saved "오늘 있었던 일" note; answer that request here so `fetcher` sees only story calls.
function stubFetch(fetcher: (url: string, init?: RequestInit) => Promise<Response>, brief = "") {
  vi.stubGlobal("fetch", (url: string, init?: RequestInit) => String(url).endsWith("/day-brief")
    ? Promise.resolve(new Response(JSON.stringify({ text: brief }), { status: 200, headers: { "Content-Type": "application/json" } }))
    : fetcher(url, init));
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("recommended story direction", () => {
  it("asks the server and shows chapters with scenes that can be previewed", async () => {
    const fetcher = vi.fn().mockResolvedValue(json(200, direction)); stubFetch(fetcher);
    const onPreview = renderCard();
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText("도쿄 여행")).toBeTruthy();
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${id}/story-direction`, expect.objectContaining({ method: "POST" }));
    expect(screen.getByText(/챕터 1\. 도착/)).toBeTruthy();
    expect(screen.getByText("이유: 여행의 시작")).toBeTruthy();
    expect(screen.getByText(/AI 추천 \(ollama\/gemma3:4b\)/)).toBeTruthy();
    expect(screen.getByText("추천 흐름에 넣지 않은 장면이 2개 있습니다.")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "미리보기" }));
    expect(onPreview).toHaveBeenCalledWith({ candidateId: scene.candidate_id, sourceId: scene.source_video_id, start: 0, end: 20 });
  });

  it("shows the recommended length and changes only the length when another one is picked", async () => {
    const longer = { ...direction, target_minutes: 15, total_seconds: 880, notes: [], chapters: [{ ...direction.chapters[0], scenes: [{ ...scene, clip_end_seconds: 45 }], total_seconds: 45 }] };
    const fetcher = vi.fn().mockResolvedValueOnce(json(200, direction)).mockResolvedValueOnce(json(200, longer));
    stubFetch(fetcher);
    renderCard();
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText(/추천 8분/)).toBeTruthy();
    expect(screen.getByText(/레슨이라 핵심 동작 위주/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "8분 · 추천" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("status").textContent).toContain("합계 7분 52초");
    expect(screen.getByText(/0\.0–20\.0초/)).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "15분" }));
    expect(await screen.findByText(/0\.0–45\.0초/)).toBeTruthy();
    expect(screen.getByRole("status").textContent).toContain("합계 14분 40초");
    const body = JSON.parse(fetcher.mock.calls[1][1].body);
    expect(body.target_minutes).toBe(15);
    expect(body.reuse.title).toBe("도쿄 여행");
    expect(body.reuse.chapters[0].candidate_ids).toEqual([scene.candidate_id]);
  });

  it("shows the saved day note, sends the edited one with a fresh recommendation, and keeps it on a length change", async () => {
    const withBrief = { ...direction, day_brief: "아침 수다, 팀 회의 발표" };
    const fetcher = vi.fn().mockResolvedValueOnce(json(200, withBrief)).mockResolvedValueOnce(json(200, { ...direction, target_minutes: 15, day_brief: "" }));
    stubFetch(fetcher, "아침 수다");
    renderCard();
    const box = await screen.findByDisplayValue("아침 수다");
    await userEvent.type(box, ", 팀 회의 발표");
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText("'오늘 있었던 일'을 반영한 추천입니다.")).toBeTruthy();
    expect(JSON.parse(fetcher.mock.calls[0][1].body)).toEqual({ day_brief: "아침 수다, 팀 회의 발표" });
    await userEvent.click(screen.getByRole("button", { name: "15분" }));
    await screen.findByRole("button", { name: "15분", pressed: true });
    expect(JSON.parse(fetcher.mock.calls[1][1].body).day_brief).toBeUndefined();
    expect(screen.getByText("'오늘 있었던 일'을 반영한 추천입니다.")).toBeTruthy();
  });

  it("explains when scene analysis has not run yet", async () => {
    stubFetch(vi.fn().mockResolvedValue(json(409, { detail: { code: "NO_SCENE_CANDIDATES", message: "x" } })));
    renderCard();
    await userEvent.click(screen.getByRole("button", { name: /추천 편집 방향 만들기/ }));
    expect(await screen.findByText("장면 후보가 없습니다. 먼저 장면 분석을 실행해 주세요.")).toBeTruthy();
  });
});
