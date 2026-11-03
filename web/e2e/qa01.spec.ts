import { expect, test } from "@playwright/test";

const project = "11111111-1111-4111-8111-111111111111";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";

test("history API error is visible while the latest completed render remains available", async ({ page }) => {
  let writes = 0;
  await page.route(/\/api\/projects\//, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") { writes++; return route.fulfill({ status: 500 }); }
    if (path.endsWith("/renders")) return route.fulfill({ status: 503, json: { detail: { code: "HISTORY_UNAVAILABLE" } } });
    if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: project, candidate_ids: [], invalid_candidate_ids: [] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: project, candidates: [] } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: project, run_status: "NOT_STARTED", total_sources: 0, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: project, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: project, project_status: "CREATED", total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0, sources: [] } });
    if (path.endsWith("/rendering")) return route.fulfill({ json: {
      project_id: project, status: "COMPLETED", render_id: renderId, is_active: false,
      succeeded: true, failed: false, safe_error_code: null, download_available: true,
      output: { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100,
        download_url: `/projects/${project}/renders/${renderId.replaceAll("-", "")}/download` },
      hard_subtitle_status: "NO_SUBTITLES", hard_subtitle_error_code: null,
      hard_subtitle_download_available: false, hard_subtitle_download_url: null,
    } });
    return route.fulfill({ json: { project_id: project, name: "QA-01", status: "CREATED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-28T00:00:00Z", updated_at: "2026-10-28T00:00:00Z", source_count: 0, processing: { total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0 } } });
  });
  await page.goto(`/projects/${project}`);
  await expect(page.getByText(/이전 렌더 기록을 표시할 수 없습니다/)).toBeVisible();
  await expect(page.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  expect(writes).toBe(0);
});
