import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AnalyzeAll } from "@/features/projects/analyze-all";

const id = "11111111-1111-4111-8111-111111111111";
const srcA = "22222222-2222-4222-8222-222222222222";
const srcB = "44444444-4444-4444-8444-444444444444";

function json(status: number, data: unknown) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function source(sid: string, name: string, status: string) { return { source_video_id: sid, original_filename: name, processing_status: status, stages: [] }; }
function processing(status: string, sourceStatus: string) {
  return { project_id: id, project_status: status, total_sources: 2, completed_count: sourceStatus === "COMPLETED" ? 2 : 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0,
    sources: [source(srcA, "IMG_0001.MOV", sourceStatus), source(srcB, "IMG_0002.MOV", sourceStatus)] };
}
function sceneRun(status: string, done: boolean) {
  return { project_id: id, run_status: status, total_sources: 2, processed_count: done ? 2 : 0, completed_count: done ? 2 : 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null,
    sources: done ? [srcA, srcB].map((sid) => ({ source_video_id: sid, status: "COMPLETED", candidate_count: 1, safe_error_code: null, warnings: [] })) : [] };
}
function diagnostics(status: string) {
  return { project_id: id, sources: [srcA, srcB].map((sid) => ({ source_video_id: sid, status, has_record: status !== "NOT_ANALYZED", candidate_count: status === "COMPLETED" ? 1 : null, abstain_reason: null, evidence_counts: {}, evidence_type_counts: {}, evidence_intervals: [], warnings: [] })) };
}
function candidates(captioned: boolean) {
  return { project_id: id, candidates: [srcA, srcB].map((sid, index) => ({ candidate_id: `33333333-3333-4333-8333-33333333333${index}`, source_video_id: sid, start_seconds: 0, end_seconds: 5, evidence: [], visual_caption: captioned ? "바다가 보인다" : null })) };
}
function vision(status: string) { return { project_id: id, status, model: "gemma3", total: 2, captioned: status === "COMPLETED" ? 2 : 0, skipped: 0, failed: 0, error_codes: [] }; }

/** A fake server whose answers move forward once each step has been requested. */
function fakeServer(initial: { processed: boolean; scened: boolean; captioned: boolean }) {
  const state = { ...initial };
  const posts: string[] = [];
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(`/api/projects/${id}`, "");
    if (init?.method === "POST") {
      posts.push(path);
      if (path === "/process") { state.processed = true; return json(202, { project_id: id, accepted: true, status_url: "" }); }
      if (path === "/scene-process") { state.scened = true; return json(202, { project_id: id, accepted: true, status_url: "" }); }
      if (path === "/scene-vision") { state.captioned = true; return json(202, vision("QUEUED")); }
    }
    if (path === "/processing") return json(200, processing(state.processed ? "COMPLETED" : "CREATED", state.processed ? "COMPLETED" : "READY"));
    if (path === "/scene-processing") return json(200, state.scened && posts.includes("/scene-process") ? sceneRun("COMPLETED", true) : sceneRun("NOT_STARTED", false));
    if (path === "/scene-diagnostics") return json(200, diagnostics(state.scened ? "COMPLETED" : "NOT_ANALYZED"));
    if (path === "/scene-candidates") return json(200, state.scened ? candidates(state.captioned) : { project_id: id, candidates: [] });
    if (path === "/scene-vision") return json(200, vision(state.captioned ? "COMPLETED" : "NOT_STARTED"));
    return json(404, {});
  });
  vi.stubGlobal("fetch", fetcher);
  return posts;
}
function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><AnalyzeAll projectId={id} pollMs={1} /></QueryClientProvider>);
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("analyze all videos with one button", () => {
  it("runs transcript, scenes and vision in order and shows each video's progress", async () => {
    const posts = fakeServer({ processed: false, scened: false, captioned: false });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /전체 분석 시작/ }));
    expect(await screen.findByText("전체 분석이 끝났습니다.")).toBeTruthy();
    expect(posts).toEqual(["/process", "/scene-process", "/scene-vision"]);
    const table = screen.getByRole("table", { name: "영상별 분석 진행" });
    const row = within(table).getByText("IMG_0001.MOV").closest("tr")!;
    expect(within(row).getByText("완료")).toBeTruthy();
    expect(within(row).getByText("장면 1개")).toBeTruthy();
    expect(within(row).getByText("1 / 1")).toBeTruthy();
  });

  it("skips steps that are already finished", async () => {
    const posts = fakeServer({ processed: true, scened: true, captioned: true });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /전체 분석 시작/ }));
    expect(await screen.findByText("전체 분석이 끝났습니다.")).toBeTruthy();
    expect(posts).toEqual([]);
  });

  it("stops with a clear message when no video finished the transcript step", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json(200, processing("COMPLETED", "FAILED"))));
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /전체 분석 시작/ }));
    expect(await screen.findByText("대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다.")).toBeTruthy();
  });
});
