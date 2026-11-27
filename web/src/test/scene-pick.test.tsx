import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ScenePickCard } from "@/features/chat-edit/scene-pick-card";

const project = "11111111-1111-4111-8111-111111111111";
const response = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const estimate = (minutes: number) => ({
  model: "claude-sonnet-5-5", target_minutes: minutes, scenes: 182, pictures: 364, chunks: 4, input_tokens: 110000,
  output_tokens: 15500, output_tokens_high: 37300, usd_low: 0.375, usd_high: 0.593, rules: ["한 컷은 5.5초 안팎"],
  has_brief: true, has_day_brief: false, reference: [], scenes_with_speech: 120, voice_marked: true,
});

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("TODO 43-2 Claude scene picking estimate", () => {
  it("shows the price and what is sent for the chosen length, and calls nothing paid", async () => {
    const calls: { url: string; method: string }[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, method: init?.method ?? "GET" });
      return Promise.resolve(response(estimate(Number(new URL(url, "http://x").searchParams.get("minutes")))));
    }));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ScenePickCard projectId={project} /></QueryClientProvider>);
    expect(await screen.findByLabelText("장면 고르기 예상 금액")).toHaveTextContent("예상 약 540~860원");
    expect(screen.getByLabelText("장면 고르기에 보내는 것")).toHaveTextContent("장면 182개(대사 있는 장면 120개) · 장면마다 사진 2장(모두 364장) · 4번에 나눠");
    expect(screen.getByLabelText("장면 고르기에 보내는 것")).toHaveTextContent("나/남 표시 포함");
    await userEvent.click(screen.getByRole("button", { name: "장면 고르기 12분" }));
    expect(await screen.findByText(/목표 길이 12분/)).toBeInTheDocument();
    expect(calls.map((call) => call.url)).toEqual([`/api/projects/${project}/scene-pick?minutes=8`, `/api/projects/${project}/scene-pick?minutes=12`]);
    expect(calls.every((call) => call.method === "GET")).toBe(true);
  });

  it("calls Claude only after the price is confirmed, lists the picks, and puts them in the plan", async () => {
    const scene = (number: number, score: number, what: string) => ({
      number, candidate_id: `c${number}`, source_video_id: "s1", clock: "09:10", scene_start: 10, scene_end: 30,
      clip_start: 12, clip_end: 18.5, score, what, why: "내가 크게 웃음" });
    const picked = { made_at: "2026-11-26T12:00:00Z", model: "claude-sonnet-5-5", target_minutes: 8, usd: 0.31,
      total_seconds: 470, title: "학원 하루", summary: "아침부터 저녁까지",
      chapters: [{ title: "아침 교실", description: "수다로 시작", reason: "하루의 시작", scenes: [scene(1, 3, "만두 없다에 빵 터짐")] }],
      left_out: [scene(2, 0, "하늘만 보임")] };
    const calls: { url: string; method: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.endsWith("/chat-edit/remake")) return Promise.resolve(response({ cuts: [] }));
      return Promise.resolve(response({ ...estimate(8), picked: method === "POST" ? picked : null }));
    }));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ScenePickCard projectId={project} /></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "장면 고르기 시작" }));
    expect(screen.getByText(/Claude를 부르면 약 540~860원이 들어요/)).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST")).toBe(false);
    await userEvent.click(screen.getByRole("button", { name: "부르기" }));
    expect(calls.find((call) => call.method === "POST")?.body).toEqual({ minutes: 8, run: true });
    const list = await screen.findByLabelText("Claude가 고른 장면");
    expect(list).toHaveTextContent("장면 1개 · 합계 7:50 (목표 8분) · 뺀 장면 1개 · 든 돈 약 450원");
    expect(list).toHaveTextContent("챕터 1. 아침 교실");
    expect(list).toHaveTextContent("1번 · 09:10 · 꼭 씀 · 6.5초 (장면 20.0초 중)");
    await userEvent.click(screen.getByRole("button", { name: "이대로 편집안 만들기" }));
    expect(await screen.findByText("Claude가 고른 장면으로 편집안을 바꿨어요.")).toBeInTheDocument();
    expect(calls.find((call) => call.url.endsWith("/chat-edit/remake"))?.body).toEqual(
      { clips: [{ candidate_id: "c1", start_seconds: 12, end_seconds: 18.5 }] });
  });

  it("TODO 43 다음(A): shows the widened cuts and puts those in the plan", async () => {
    const scene = { number: 1, candidate_id: "c1", source_video_id: "s1", clock: "09:10", scene_start: 10, scene_end: 13,
      clip_start: 10, clip_end: 13, score: 3, what: "수다", why: "웃음" };
    const picked = { made_at: "2026-11-26T12:00:00Z", model: "claude-sonnet-5-5", target_minutes: 8, usd: 0.31,
      total_seconds: 3, title: "학원 하루", summary: "", chapters: [{ title: "아침", description: "", reason: "", scenes: [scene] }],
      left_out: [] };
    const widened = { clips: [{ candidate_id: "c1", source_video_id: "s1", numbers: [1], chapter: 0, start: 8.6, end: 14.2,
      picked_start: 10, picked_end: 13 }], cuts: 1, median_seconds: 5.6, total_seconds: 5.6, merged: 2, left_out: 30, typical_cut: 5.5 };
    const calls: { url: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      calls.push({ url, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.endsWith("/chat-edit/remake")) return Promise.resolve(response({ cuts: [] }));
      return Promise.resolve(response({ ...estimate(8), picked, widened }));
    }));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><ScenePickCard projectId={project} /></QueryClientProvider>);
    const note = await screen.findByLabelText("넓힌 컷");
    expect(note).toHaveTextContent("편집안에는 컷 1개 · 한 컷 가운데 5.6초 · 합계 0:06로 넣어요");
    expect(note).toHaveTextContent("붙어 있는 장면 2곳을 합치고, 점수 낮은 컷 30개를 빼고");
    await userEvent.click(screen.getByRole("button", { name: "이대로 편집안 만들기" }));
    await screen.findByText("Claude가 고른 장면으로 편집안을 바꿨어요.");
    expect(calls.find((call) => call.url.endsWith("/chat-edit/remake"))?.body).toEqual(
      { clips: [{ candidate_id: "c1", start_seconds: 8.6, end_seconds: 14.2 }] });
  });
});
