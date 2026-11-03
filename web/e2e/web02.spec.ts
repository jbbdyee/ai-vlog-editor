import { expect, test } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
const other = "33333333-3333-4333-8333-333333333333";
const sourceId = "22222222-2222-4222-8222-222222222222";
const candidateId = "44444444-4444-4444-8444-444444444444";
const project = (projectId: string) => ({ project_id: projectId, name: projectId === id ? "장면 QA" : "다른 프로젝트", status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } });
const processing = (projectId: string) => ({ project_id: projectId, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "COMPLETED", stages: [] }] });
const status = (projectId: string, runStatus: string) => ({ project_id: projectId, run_status: runStatus, total_sources: 1, processed_count: runStatus === "COMPLETED" ? 1 : 0, completed_count: runStatus === "COMPLETED" ? 1 : 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] });

test("scene run, candidate evidence, reload and project change use server state", async ({ page }) => {
  let started = false; let polls = 0;
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const pathname = new URL(route.request().url()).pathname;
    const projectId = pathname.includes(other) ? other : id;
    if (pathname.endsWith("/scene-process") && route.request().method() === "POST") { started = true; return route.fulfill({ status: 202, json: { project_id: projectId, accepted: true, status_url: `/projects/${projectId}/scene-processing` } }); }
    if (pathname.endsWith("/scene-processing")) { if (started && projectId === id) polls++; return route.fulfill({ json: status(projectId, projectId === other ? "NOT_STARTED" : started ? polls < 2 ? "RUNNING" : "COMPLETED" : "NOT_STARTED") }); }
    if (pathname.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: projectId, candidates: started && projectId === id && polls >= 2 ? [{ candidate_id: candidateId, source_video_id: sourceId, start_seconds: 5.54, end_seconds: 6.12, evidence: [{ modality: "transcript", evidence_type: "speech", count: 2 }] }] : [] } });
    if (pathname.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: projectId, sources: projectId === id ? [{ source_video_id: sourceId, status: "COMPLETED", has_record: true, candidate_count: started ? 1 : 0, abstain_reason: null, evidence_counts: { transcript: 2, visual: null }, evidence_type_counts: { speech: 2 }, evidence_intervals: [{ modality: "transcript", evidence_type: "speech", start_seconds: 5.5, end_seconds: 6.1 }], warnings: [] }] : [] } });
    if (pathname.endsWith("/processing")) return route.fulfill({ json: processing(projectId) });
    return route.fulfill({ json: project(projectId) });
  });
  await page.goto(`/projects/${id}`);
  await expect(page.getByText("현재 서버에서 실행 기록 없음")).toBeVisible();
  await page.getByRole("button", { name: "장면 분석 시작" }).click();
  await expect(page.getByText("분석 중", { exact: true })).toBeVisible();
  await expect(page.getByText("분석 실행 완료")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("5.54초 – 6.12초")).toBeVisible();
  await expect(page.getByText("관측 근거 1종").first()).toBeVisible();
  await expect(page.getByLabel("추천 이유").first()).toHaveAttribute("title", "transcript · speech 2");
  await expect(page.getByText("visual: 미확인")).toBeVisible();
  await page.getByText("원본 진단값 보기").click();
  await expect(page.getByText(/"start_seconds": 5.5/)).toBeVisible();
  await page.reload();
  await expect(page.getByText("분석 실행 완료")).toBeVisible();
  await expect(page.getByText("5.54초 – 6.12초")).toBeVisible();
  await page.goto(`/projects/${other}`);
  await expect(page.getByText("다른 프로젝트")).toBeVisible();
  await expect(page.getByText("현재 저장된 장면 후보가 없습니다.")).toBeVisible();
  await expect(page.getByText(candidateId, { exact: false })).toHaveCount(0);
});
