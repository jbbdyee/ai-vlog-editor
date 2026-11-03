import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { SceneAnalysis } from "@/features/scenes/scene-analysis";
import type { ProcessingStatus } from "@/api/projects";

const id = "11111111-1111-4111-8111-111111111111";
const other = "33333333-3333-4333-8333-333333333333";
const sourceId = "22222222-2222-4222-8222-222222222222";
const ready: ProcessingStatus = { project_id: id, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "COMPLETED", stages: [] }] };
const run = (projectId = id, runStatus = "NOT_STARTED") => ({ project_id: projectId, run_status: runStatus, total_sources: 1, processed_count: runStatus === "NOT_STARTED" ? 0 : 1, completed_count: runStatus === "COMPLETED" ? 1 : 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] });
const candidate = (candidateId: string) => ({ candidate_id: candidateId, source_video_id: sourceId, start_seconds: 5.54, end_seconds: 6.12, evidence: [{ modality: "transcript", evidence_type: "speech", count: 2 }] });
const diagnostic = { source_video_id: sourceId, status: "COMPLETED", has_record: true, candidate_count: 1, abstain_reason: null, evidence_counts: { transcript: 2, visual: null }, evidence_type_counts: { speech: 2 }, evidence_intervals: [{ modality: "transcript", evidence_type: "speech", start_seconds: 5.5, end_seconds: 6.1 }], warnings: [] };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function mount(projectId = id, processing: ProcessingStatus = ready) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><SceneAnalysis key={projectId} projectId={projectId} processing={processing} /></QueryClientProvider>);
}
beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("scene analysis API and UI", () => {
  it("waits for completed source processing and does not invent a percent or ranking", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/scene-processing") ? run() : url.endsWith("/scene-candidates") ? { project_id: id, candidates: [] } : { project_id: id, sources: [] }))));
    mount(id, { ...ready, project_status: "PROCESSING", completed_count: 0, sources: [{ ...ready.sources[0], processing_status: "PROCESSING" }] });
    expect(await screen.findByText("현재 서버에서 실행 기록 없음")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "장면 분석 시작" })).toBeDisabled();
    expect(screen.getByText("현재 저장된 장면 후보가 없습니다.")).toBeInTheDocument();
    expect(screen.queryByText(/추천 점수/)).not.toBeInTheDocument();
  });

  it("accepts the run, follows server status and refreshes candidates and evidence", async () => {
    let active = false; let reads = 0; let candidateReads = 0;
    const fetcher = vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (url.endsWith("/scene-process") && options?.method === "POST") { active = true; return Promise.resolve(json(202, { project_id: id, accepted: true, status_url: `/projects/${id}/scene-processing` })); }
      if (url.endsWith("/scene-processing")) { if (active) reads++; return Promise.resolve(json(200, run(id, active ? reads < 2 ? "RUNNING" : "COMPLETED" : "NOT_STARTED"))); }
      if (url.endsWith("/scene-candidates")) { candidateReads++; return Promise.resolve(json(200, { project_id: id, candidates: active && reads >= 2 ? [candidate("44444444-4444-4444-8444-444444444444")] : [] })); }
      return Promise.resolve(json(200, { project_id: id, sources: [diagnostic] }));
    });
    vi.stubGlobal("fetch", fetcher); mount();
    await screen.findByText("현재 서버에서 실행 기록 없음");
    await userEvent.click(screen.getByRole("button", { name: "장면 분석 시작" }));
    await waitFor(() => expect(reads).toBeGreaterThanOrEqual(2), { timeout: 4000 });
    await screen.findByText("5.54초 – 6.12초");
    expect(candidateReads).toBeGreaterThanOrEqual(2);
    // Unknown evidence types are summarised in Korean; the raw codes stay available as a tooltip.
    expect(screen.getByText("관측 근거 1종")).toBeInTheDocument();
    expect(screen.getByLabelText("추천 이유")).toHaveAttribute("title", "transcript · speech 2");
    expect(screen.getByText("visual: 미확인")).toBeInTheDocument();
    await userEvent.click(screen.getByText("원본 진단값 보기"));
    expect(screen.getByText(/"start_seconds": 5.5/)).toBeInTheDocument();
  });

  it("shows zero candidates, failed runs and a safe backend error", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === "POST") return Promise.resolve(json(409, { detail: { code: "PROJECT_SCENE_PROCESSING_ALREADY_ACTIVE" } }));
      if (url.endsWith("/scene-processing")) return Promise.resolve(json(200, { ...run(id, "FAILED"), safe_error_code: "PROJECT_SCENE_RUN_FAILED" }));
      return Promise.resolve(json(200, url.endsWith("/scene-candidates") ? { project_id: id, candidates: [] } : { project_id: id, sources: [] }));
    }));
    mount();
    expect(await screen.findByText("분석 실행 실패")).toBeInTheDocument();
    expect(screen.getByText("이번 조회에서 장면 후보가 없습니다. 진단을 확인해 주세요.")).toBeInTheDocument();
    expect(screen.getByText(/PROJECT_SCENE_RUN_FAILED/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "장면 분석 시작" }));
    expect(await screen.findByText(/PROJECT_SCENE_PROCESSING_ALREADY_ACTIVE/)).toBeInTheDocument();
  });

  it("lists multiple candidates without mixing projects, including on a fresh mount", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => {
      const projectId = url.includes(other) ? other : id;
      const candidates = projectId === id ? [candidate("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), candidate("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")] : [candidate("cccccccc-cccc-4ccc-8ccc-cccccccccccc")];
      return Promise.resolve(json(200, url.endsWith("/scene-processing") ? run(projectId, "NOT_STARTED") : url.endsWith("/scene-candidates") ? { project_id: projectId, candidates } : { project_id: projectId, sources: [] }));
    }));
    const first = mount();
    expect(await screen.findAllByText("5.54초 – 6.12초")).toHaveLength(2);
    first.unmount();
    mount(other, { ...ready, project_id: other });
    expect(await screen.findAllByText("5.54초 – 6.12초")).toHaveLength(1);
    expect(screen.getByText(/cccccccc-cccc-4ccc-8ccc-cccccccccccc/)).toBeInTheDocument();
    expect(screen.queryByText(/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/)).not.toBeInTheDocument();
  });

  it("reports connection and diagnostics failures instead of claiming completion", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(url.endsWith("/scene-processing") ? new Response("", { status: 502 }) : json(500, { detail: { code: "SCENE_DIAGNOSTICS_READ_FAILED" } }))));
    mount();
    expect(await screen.findByText("서버에 연결할 수 없습니다.")).toBeInTheDocument();
    expect((await screen.findAllByText(/SCENE_DIAGNOSTICS_READ_FAILED/)).length).toBeGreaterThan(0);
    expect(screen.queryByText("분석 실행 완료")).not.toBeInTheDocument();
  });
});
