import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MyEditCard } from "@/features/chat-edit/my-edit-card";
import type { MyEditResult } from "@/api/my-edit";

const project = "11111111-1111-4111-8111-111111111111";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

const result: MyEditResult = {
  filename: "제목 없음.mp4", compared_at: "2026-11-17T00:00:00Z", seconds_taken: 30, edit_duration: 480, found_seconds: 420,
  frames: 1920, found_frames: 1700,
  mine: { cut_count: 120, total_seconds: 420, median_cut: 2.5, mean_cut: 3.5 },
  cutory: { cut_count: 31, total_seconds: 232.2, median_cut: 6.4, mean_cut: 7.5 },
  overlap_seconds: 61.5, not_found: [{ edit_start: 300, edit_end: 330 }], not_found_seconds: 30, day_seconds: 4917,
  sources: [{ number: 1, filename: "a.MP4", day_start: 0, duration: 100 }, { number: 2, filename: "b.MP4", day_start: 100, duration: 4817 }],
  mine_spans: [[0, 50], [200, 400]], cutory_spans: [[10, 30]],
  tags: { other_voice: { mine: 300, cutory: 100 }, quiet: { mine: 120, cutory: 132.2 } },
  cuts: [{ number: 1, edit_start: 0, edit_end: 2.5, length: 2.5, source_id: "s", source_number: 1, source_filename: "a.MP4",
    source_start: 10, source_end: 12.5, score: 0.95, tags: ["other_voice"], in_cutory: true }],
};

function show(responses: Record<string, unknown>) {
  vi.stubGlobal("fetch", vi.fn((url: string) => Promise.resolve(response(responses[url.replace(/^.*\/projects\/[^/]+/, "")] ?? {}))));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><MyEditCard projectId={project} /></QueryClientProvider>);
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("TODO 29 my edit compared with the Cutory plan", () => {
  it("asks for my edited video when nothing was compared yet", async () => {
    show({ "/my-edit": { project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, has_video: false, result: null } });
    expect(await screen.findByRole("button", { name: /내 편집 영상 올리기/ })).toBeInTheDocument();
    expect(screen.getByText(/원본에 없음/)).toBeInTheDocument();
  });

  it("shows the taste card: cuts, cut length, day bars, kinds of scenes and the not-found parts", async () => {
    show({ "/my-edit": { project_id: project, status: "COMPLETED", step: "match", done: 1, total: 1, error_code: null, has_video: true, result } });
    const card = await screen.findByLabelText("취향 카드");
    expect(within(card).getByText("나 120개")).toBeInTheDocument();
    expect(within(card).getByText("Cutory 31개")).toBeInTheDocument();
    expect(within(card).getByText("나 2.5초")).toBeInTheDocument();
    expect(within(card).getByText(/약 88%/)).toBeInTheDocument();
    expect(within(card).getByLabelText("나 편집이 쓴 곳").children).toHaveLength(2);
    expect(within(card).getByText("다른 사람 목소리")).toBeInTheDocument();
    expect(within(card).getByText(/원본에 없음 1곳 ·/, { selector: "summary" })).toBeInTheDocument();
    expect(within(card).getByAltText("내 편집 05:00 장면")).toHaveAttribute("src", expect.stringContaining("/my-edit/thumb?at=315.000"));
    expect(screen.getByRole("button", { name: /지금 편집안과 다시 비교/ })).toBeEnabled();
  });

  it("shows where the comparison is while it runs", async () => {
    show({ "/my-edit": { project_id: project, status: "RUNNING", step: "sources", done: 3, total: 35, error_code: null, has_video: true, result: null } });
    expect(await screen.findByText(/원본 훑는 중 3\/35/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /다른 편집 영상 올리기/ })).toBeDisabled();
    await userEvent.setup().click(screen.getByRole("button", { name: /다른 편집 영상 올리기/ })).catch(() => undefined);
  });
});
