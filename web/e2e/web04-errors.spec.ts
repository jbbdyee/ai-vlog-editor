import { expect, test } from "@playwright/test";

const projectId = "11111111-1111-4111-8111-111111111111";
const otherId = "33333333-3333-4333-8333-333333333333";
const candidateId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const sourceId = "22222222-2222-4222-8222-222222222222";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const renderHex = renderId.replaceAll("-", "");

test("home describes implemented workflow and reports backend connection failure", async ({ page }) => {
  await page.route("**/api/projects", (route) => route.abort("failed"));
  await page.goto("/");
  await expect(page.getByText(/사용할 장면의 순서를 저장한 뒤/)).toBeVisible();
  await expect(page.getByText("Creative workspace · local")).toBeVisible();
  await page.getByLabel("프로젝트 이름").fill("연결 실패 QA");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  await expect(page.getByRole("alert")).toContainText("서버에 연결할 수 없습니다");
  await expect(page).toHaveURL("/");
});

test("a missing subtitle and failed base download stay visible without cross-project result mixing", async ({ page }) => {
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const id = path.includes(otherId) ? otherId : projectId;
    if (path.includes("/renders/") && path.endsWith("/download")) return route.fulfill({ status: 404, json: { detail: { code: "RENDER_NOT_FOUND" } } });
    if (path.endsWith("/rendering")) return route.fulfill({ json: { project_id: id, status: id === projectId ? "COMPLETED" : "NOT_STARTED", render_id: id === projectId ? renderId : null, is_active: false, succeeded: id === projectId, failed: false, safe_error_code: null, download_available: id === projectId, output: id === projectId ? { filename: "final.mp4", duration_seconds: 1, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100, download_url: `/projects/${id}/renders/${renderHex}/download` } : null, hard_subtitle_status: id === projectId ? "FAILED" : "NOT_STARTED", hard_subtitle_error_code: id === projectId ? "SUBTITLE_RENDER_FAILED" : null, hard_subtitle_download_available: false, hard_subtitle_download_url: null } });
    if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: id, candidate_ids: id === projectId ? [candidateId] : [], invalid_candidate_ids: [] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: id, candidates: id === projectId ? [{ candidate_id: candidateId, source_video_id: sourceId, start_seconds: 1, end_seconds: 2, evidence: [] }] : [] } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: id, run_status: "NOT_STARTED", total_sources: 1, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: id, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: id, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "COMPLETED", stages: [] }] } });
    return route.fulfill({ json: { project_id: id, name: "오류 QA", status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } } });
  });
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByText(/SUBTITLE_RENDER_FAILED/)).toBeVisible();
  await expect(page.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeDisabled();
  await page.getByRole("button", { name: "자막 없는 MP4 다운로드" }).click();
  await expect(page.getByRole("alert").filter({ hasText: "RENDER_NOT_FOUND" })).toContainText("RENDER_NOT_FOUND");
  await page.goto(`/projects/${otherId}`);
  await expect(page.getByText("현재 서버에서 실행 기록 없음").last()).toBeVisible();
  await expect(page.getByText(renderId)).toHaveCount(0);
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
});
