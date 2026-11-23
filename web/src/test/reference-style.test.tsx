import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ReferenceStyleCard } from "@/features/chat-edit/reference-style-card";
import type { ReferenceResult } from "@/api/reference-style";

const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const result: ReferenceResult = {
  filename: "릴스.mp4", measured_at: "2026-11-23T00:00:00Z", seconds_taken: 1.1, video_duration: 38.07,
  stats: { cut_count: 16, duration: 38.06, median_cut: 2.18, mean_cut: 2.38, p90_cut: 3.73, short_share: 0.438, long_share: 0, cuts_per_minute: 25.2 },
  lengths: [1.2, 2.5, 3.7, 1.8],
  candidates: [
    { key: "max_cut", text: "한 컷은 4초 넘지 않게", why: "컷 10개 중 9개가 3.7초 이하" },
    { key: "median_cut", text: "한 컷은 2초 안팎", why: "한 컷 가운데 값 2.2초" },
  ],
};

function show(rules: { id: string; text: string }[]) {
  const fetch = vi.fn((url: string, init?: RequestInit) => {
    if (url.endsWith("/reference-style")) return Promise.resolve(response({ status: "COMPLETED", error_code: null, result }));
    if (url.endsWith("/edit-rules") && init?.method === "POST") {
      const text = JSON.parse(String(init.body)).text as string;
      return Promise.resolve(response({ rules: [...rules, { id: "new", text }] }));
    }
    return Promise.resolve(response({ rules }));
  });
  vi.stubGlobal("fetch", fetch);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><ReferenceStyleCard /></QueryClientProvider>);
  return fetch;
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("TODO 33-1 follow a video I like", () => {
  it("shows the cut rhythm and saves a candidate as my rule", async () => {
    const fetch = show([{ id: "a", text: "한 컷은 2초 안팎" }]);
    expect(await screen.findByText("2.2초")).toBeInTheDocument();
    expect(screen.getByText("44%")).toBeInTheDocument();
    expect(screen.getByText("내 규칙에 있음")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "규칙으로" }));
    const post = fetch.mock.calls.find(([, init]) => init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ text: "한 컷은 4초 넘지 않게" });
    expect(await screen.findAllByText("내 규칙에 있음")).toHaveLength(2);
  });
});
