import { expect, test, type Page } from "@playwright/test";

const project = "11111111-1111-4111-8111-111111111111";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const hex = renderId.replaceAll("-", "");

function completed(integrity: "VERIFIED" | "CORRUPT" | "UNVERIFIED") {
  const ok = integrity === "VERIFIED";
  return {
    project_id: project, status: "COMPLETED", render_id: renderId, is_active: false, succeeded: true, failed: false,
    safe_error_code: ok ? null : integrity === "CORRUPT" ? "RENDER_FILE_CORRUPT" : "RENDER_FILE_UNVERIFIED",
    download_available: ok,
    output: { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100,
      download_url: ok ? `/projects/${project}/renders/${hex}/download` : null },
    hard_subtitle_status: ok ? "NO_SUBTITLES" : "NO_SUBTITLES", hard_subtitle_error_code: null,
    hard_subtitle_download_available: false, hard_subtitle_download_url: null,
    integrity_status: integrity, subtitle_integrity_status: null, hard_subtitle_integrity_status: null,
  };
}

async function mock(page: Page, current: () => unknown, onDownload: () => { status: number; body: unknown }) {
  const counters = { writes: 0, status: 0 };
  await page.route(/\/api\/projects\//, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (route.request().method() !== "GET") { counters.writes++; return route.fulfill({ status: 500 }); }
    if (path.endsWith("/download")) { const response = onDownload(); return route.fulfill({ status: response.status, json: response.body }); }
    if (path.endsWith("/renders")) return route.fulfill({ json: { project_id: project, items: [current()], next_cursor: null } });
    if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: project, candidate_ids: [], invalid_candidate_ids: [] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: project, candidates: [] } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: project, run_status: "NOT_STARTED", total_sources: 0, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: project, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: project, project_status: "CREATED", total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0, sources: [] } });
    if (path.endsWith("/rendering")) { counters.status++; return route.fulfill({ json: current() }); }
    return route.fulfill({ json: { project_id: project, name: "QA-03", status: "CREATED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-11-03T00:00:00Z", updated_at: "2026-11-03T00:00:00Z", source_count: 0, processing: { total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0 } } });
  });
  return counters;
}

test("a file corrupted after status was read is refused by preview and the UI switches to the integrity reason", async ({ page }) => {
  let state: "VERIFIED" | "CORRUPT" = "VERIFIED";
  const counters = await mock(page, () => completed(state), () => {
    state = "CORRUPT";
    return { status: 409, body: { detail: { code: "RENDER_FILE_CORRUPT" } } };
  });
  await page.goto(`/projects/${project}`);
  await expect(page.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled();
  // The <video> Range request gets 409, playback fails, and the component re-reads /rendering.
  await expect(page.getByText(/기록한 SHA-256과 다릅니다/)).toBeVisible();
  await expect(page.getByLabel("최종 영상 미리보기")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeDisabled();
  await expect(page.getByText(/기본 파일 변형 감지/)).toBeVisible();
  expect(counters.status).toBeGreaterThan(1);
  expect(counters.writes).toBe(0);
});

test("a hash-less historical render is explained and never requested for playback", async ({ page }) => {
  let downloads = 0;
  const counters = await mock(page, () => completed("UNVERIFIED"), () => { downloads++; return { status: 409, body: { detail: { code: "RENDER_FILE_UNVERIFIED" } } }; });
  await page.goto(`/projects/${project}`);
  await expect(page.getByText(/SHA-256\)이 도입되기 전에 완료된 렌더/)).toBeVisible();
  await expect(page.getByText(/무결성 기록 없음/)).toBeVisible();
  await expect(page.getByRole("button", { name: "이 결과 보기" })).toBeDisabled();
  expect(downloads).toBe(0);
  expect(counters.writes).toBe(0);
});
