import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TasteBriefCard } from "@/features/chat-edit/taste-brief-card";

const project = "11111111-1111-4111-8111-111111111111";
const response = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
const estimate = { scenes: 182, examples: 0, model: "claude-sonnet-5-5", input_tokens: 21000, output_tokens: 4750, usd: 0.0895, ran: false, counts: {}, made_at: null };

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("TODO 32-4 my editing taste", () => {
  it("saves my description, shows the price before the paid call, then the score counts", async () => {
    const calls: { url: string; method: string; body: unknown }[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      calls.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
      if (url.endsWith("/edit-taste")) return Promise.resolve(response({ text: method === "PUT" ? "회의에서 내 의견은 꼭 남김" : "" }));
      if (method === "POST") return Promise.resolve(response({ ...estimate, ran: true, counts: { "0": 40, "1": 60, "2": 50, "3": 32 }, made_at: "2026-11-18T10:00:00Z" }));
      return Promise.resolve(response(estimate));
    }));
    render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><TasteBriefCard projectId={project} /></QueryClientProvider>);
    await userEvent.type(await screen.findByRole("textbox", { name: "내 편집 취향 설명" }), "회의에서 내 의견은 꼭 남김");
    await userEvent.click(screen.getByRole("button", { name: "취향 저장" }));
    expect(calls.find((call) => call.method === "PUT")?.body).toEqual({ text: "회의에서 내 의견은 꼭 남김" });
    await userEvent.click(await screen.findByRole("button", { name: "취향으로 장면 점수 매기기" }));
    expect(screen.getByText(/유료 · 예상 약 \$0\.089/)).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST")).toBe(false);  // nothing paid before the second click
    await userEvent.click(screen.getByRole("button", { name: "점수 매기기" }));
    expect(await screen.findByLabelText("장면 점수")).toHaveTextContent("꼭 남김 32 · 남기면 좋음 50 · 빼도 됨 60 · 빼야 함 40");
  });
});
