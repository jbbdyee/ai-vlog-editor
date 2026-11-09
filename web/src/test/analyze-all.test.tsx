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

function analyzeAll(phase: string, error: string | null = null) {
  return { project_id: id, phase, running: ["transcript", "scenes", "vision"].includes(phase), error, started_at: null, finished_at: null };
}

/** A fake server: after "전체 분석" is started it reports the next phase on each status request, like the real server-side run. */
function fakeServer(options: { phases: string[]; error?: string | null; finished?: boolean }) {
  const posts: string[] = [];
  let started = false;
  let index = 0;
  const done = () => options.finished || (started && index >= options.phases.length - 1);
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    const path = url.replace(`/api/projects/${id}`, "");
    if (init?.method === "POST") {
      posts.push(path);
      if (path === "/analyze-all") { started = true; return json(202, analyzeAll(options.phases[0])); }
      return json(404, {});
    }
    if (path === "/analyze-all") {
      if (!started) return json(200, analyzeAll(options.finished ? options.phases.at(-1)! : "idle", options.error ?? null));
      index = Math.min(index + 1, options.phases.length - 1);
      const phase = options.phases[index];
      return json(200, analyzeAll(phase, phase === "failed" ? options.error ?? null : null));
    }
    if (path === "/processing") return json(200, processing("COMPLETED", done() ? "COMPLETED" : "READY"));
    if (path === "/scene-processing") return json(200, done() ? sceneRun("COMPLETED", true) : sceneRun("NOT_STARTED", false));
    if (path === "/scene-diagnostics") return json(200, diagnostics(done() ? "COMPLETED" : "NOT_ANALYZED"));
    if (path === "/scene-candidates") return json(200, done() ? candidates(true) : { project_id: id, candidates: [] });
    if (path === "/scene-vision") return json(200, vision(done() ? "COMPLETED" : "NOT_STARTED"));
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
  it("asks the server to run every step and follows its progress", async () => {
    const posts = fakeServer({ phases: ["transcript", "scenes", "vision", "done"] });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /전체 분석 시작/ }));
    expect(await screen.findByText("전체 분석이 끝났습니다.")).toBeTruthy();
    expect(posts).toEqual(["/analyze-all"]);
    const table = screen.getByRole("table", { name: "영상별 분석 진행" });
    const row = within(table).getByText("IMG_0001.MOV").closest("tr")!;
    expect(await within(row).findByText("완료")).toBeTruthy();
    expect(await within(row).findByText("장면 1개")).toBeTruthy();
    expect(await within(row).findByText("1 / 1")).toBeTruthy();
  });

  it("shows the current step when the page is opened while the server is already running", async () => {
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      const path = url.replace(`/api/projects/${id}`, "");
      if (init?.method === "POST") posts.push(path);
      if (path === "/analyze-all") return json(200, analyzeAll("scenes"));
      if (path === "/processing") return json(200, processing("COMPLETED", "COMPLETED"));
      if (path === "/scene-processing") return json(200, sceneRun("RUNNING", false));
      if (path === "/scene-diagnostics") return json(200, diagnostics("RUNNING"));
      if (path === "/scene-candidates") return json(200, { project_id: id, candidates: [] });
      return json(404, {});
    }));
    renderCard();
    expect(await screen.findByText("② 장면 찾는 중")).toBeTruthy();
    expect((screen.getByRole("button", { name: /전체 분석 중/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/이 페이지를 닫거나 다른 탭을 봐도 계속 진행/)).toBeTruthy();
    expect(posts).toEqual([]);
  });

  it("shows the server's message when the run stops", async () => {
    fakeServer({ phases: ["transcript", "failed"], error: "대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다." });
    renderCard();
    await userEvent.click(await screen.findByRole("button", { name: /전체 분석 시작/ }));
    expect(await screen.findByText("대사 단계를 마친 영상이 없어 장면 분석으로 넘어갈 수 없습니다.")).toBeTruthy();
    expect(screen.getByRole("button", { name: /전체 분석 다시 시작/ })).toBeTruthy();
  });
});
