import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TranscriptLines } from "@/features/projects/transcript-lines";

const id = "11111111-1111-4111-8111-111111111111";
const src = "22222222-2222-4222-8222-222222222222";

function json(status: number, data: unknown) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function line(start: number, text: string, speaker: string | null = null, score: number | null = null, my_voice = false) {
  return { start_seconds: start, end_seconds: start + 2, text, speaker, score, my_voice };
}
function payload(registered: boolean, scored: boolean) {
  return {
    project_id: id, threshold: 0.45, model_available: true,
    voice_run: { status: scored ? "COMPLETED" : "IDLE", done: scored ? 1 : 0, total: scored ? 1 : 0, error: null },
    my_voice: registered ? [{ source_video_id: src, start_seconds: 31, text: "오늘 학원 끝났어" }] : [],
    sources: [{
      source_video_id: src, original_filename: "DJI_0789.MP4", voice_current: scored,
      lines: scored
        ? [line(31, "오늘 학원 끝났어", "me", 0.71, true), line(38, "다음 동작 갈게요", "other", 0.12), line(44, "응", "unknown", null)]
        : [line(31, "오늘 학원 끝났어", null, null, registered), line(38, "다음 동작 갈게요"), line(44, "응")],
    }],
  };
}

function setup(fetcher: typeof fetch) {
  vi.stubGlobal("fetch", fetcher);
  const onPreview = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><TranscriptLines projectId={id} onPreview={onPreview} pollMs={5} /></QueryClientProvider>);
  return onPreview;
}

describe("TODO 24 대사 목록", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("registers a line as my voice, runs the voice step and shows 나 / 다른 사람 per line", async () => {
    const posts: unknown[] = [];
    let state = payload(false, false);
    setup(vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(`/api/projects/${id}`, "");
      if (path === "/my-voice" && init?.method === "POST") { posts.push(JSON.parse(String(init.body))); state = payload(true, false); return json(200, state); }
      if (path === "/voice-scan") { state = payload(true, true); return json(202, state.voice_run); }
      return json(200, state);
    }) as unknown as typeof fetch);

    expect(await screen.findByText("아직 등록 안 함")).toBeInTheDocument();
    const scanButton = screen.getByRole("button", { name: /목소리 분석/ });
    expect(scanButton).toBeDisabled();
    const first = screen.getByText("오늘 학원 끝났어").closest("li")!;
    await userEvent.click(within(first).getByRole("button", { name: "이건 내 목소리" }));
    expect(posts).toEqual([{ source_video_id: src, start_seconds: 31, end_seconds: 33, text: "오늘 학원 끝났어" }]);
    expect(await screen.findByText("등록한 줄 1개")).toBeInTheDocument();
    expect(screen.getByText(/아직 목소리 분석을 안 한 영상/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: /목소리 분석/ }));
    expect(await screen.findByText(/나 1줄 · 다른 사람 1줄 · 모름 1줄/)).toBeInTheDocument();
    expect(within(screen.getByText("다음 동작 갈게요").closest("li")!).getByText("다른 사람")).toBeInTheDocument();
    expect(within(screen.getByText("오늘 학원 끝났어").closest("li")!).getByText("나")).toBeInTheDocument();
  });

  it("filters to my lines and previews a line from its time", async () => {
    const onPreview = setup(vi.fn(async () => json(200, payload(true, true))) as unknown as typeof fetch);
    await screen.findByText("다음 동작 갈게요");
    await userEvent.click(screen.getByLabelText("내 말만 보기"));
    expect(screen.queryByText("다음 동작 갈게요")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "00:31부터 미리보기" }));
    expect(onPreview).toHaveBeenCalledWith(expect.objectContaining({ sourceId: src, start: 31, end: 33 }));
  });

  it("explains a line that is too short to register", async () => {
    setup(vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST"
      ? json(422, { detail: { code: "MY_VOICE_FAILED", message: "이 줄은 너무 짧아서 목소리를 알아듣기 어렵습니다. 더 긴 줄을 골라 주세요." } })
      : json(200, payload(false, false))) as unknown as typeof fetch);
    const short = (await screen.findByText("응")).closest("li")!;
    await userEvent.click(within(short).getByRole("button", { name: "이건 내 목소리" }));
    expect(await screen.findByText(/목소리를 알아듣기 어렵습니다/)).toBeInTheDocument();
  });
});
