import { expect, test } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
const other = "33333333-3333-4333-8333-333333333333";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const hex = renderId.replaceAll("-", "");
const source = "22222222-2222-4222-8222-222222222222";

test("save ordered scenes, render and download both MP4 variants with server state", async ({ page }) => {
  let saved: string[] = []; let renderStarted = false; let polls = 0; let renderPosts = 0;
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    const projectId = path.includes(other) ? other : id;
    if (path.endsWith("/scene-edit-plan")) {
      if (route.request().method() === "PUT") saved = (route.request().postDataJSON() as { candidate_ids: string[] }).candidate_ids;
      return route.fulfill({ json: { project_id: projectId, candidate_ids: projectId === id ? saved : [], invalid_candidate_ids: [] } });
    }
    if (path.endsWith("/render") && route.request().method() === "POST") { renderStarted = true; renderPosts++; return route.fulfill({ status: 202, json: { project_id: projectId, accepted: true, status_url: `/projects/${projectId}/rendering` } }); }
    if (path.endsWith("/rendering")) {
      if (renderStarted) polls++;
      const done = renderStarted && polls >= 2;
      return route.fulfill({ json: { project_id: projectId, status: !renderStarted ? "NOT_STARTED" : done ? "COMPLETED" : "RUNNING", render_id: done ? renderId : null, is_active: renderStarted && !done, succeeded: done, failed: false, safe_error_code: null, download_available: done, output: done ? { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100, download_url: `/projects/${projectId}/renders/${hex}/download` } : null, hard_subtitle_status: done ? "AVAILABLE" : "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: done, hard_subtitle_download_url: done ? `/projects/${projectId}/renders/${hex}/subtitled/download` : null } });
    }
    if (path.includes("/renders/") && path.endsWith("/download")) return route.fulfill({ status: 200, contentType: "video/mp4", body: "synthetic-test-mp4-bytes" });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: projectId, candidates: projectId === id ? [a, b].map((candidateId, index) => ({ candidate_id: candidateId, source_video_id: source, start_seconds: index * 2 + 1, end_seconds: index * 2 + 2, evidence: [] })) : [] } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: projectId, run_status: "NOT_STARTED", total_sources: 1, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: projectId, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: projectId, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: source, original_filename: "clip.MOV", processing_status: "COMPLETED", stages: [] }] } });
    return route.fulfill({ json: { project_id: projectId, name: projectId === id ? "WEB-03 QA" : "다른 프로젝트", status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } } });
  });
  await page.goto(`/projects/${id}`);
  await page.getByRole("button", { name: "장면 선택" }).first().click();
  await page.getByRole("button", { name: "장면 선택" }).click();
  await page.getByRole("button", { name: "2번 위로" }).click();
  await expect(page.getByText("저장되지 않은 변경사항이 있습니다.")).toBeVisible();
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  await page.getByRole("button", { name: "편집 계획 저장" }).click();
  await expect(page.getByText("편집 계획 저장 완료.")).toBeVisible();
  expect(saved).toEqual([b, a]);
  await page.reload();
  await expect(page.getByText("저장된 편집 계획입니다.")).toBeVisible();
  await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li").first()).toContainText("clip.MOV · 3.00–4.00초");
  await page.getByRole("button", { name: "저장된 계획으로 렌더링" }).click();
  await expect(page.getByText("렌더 완료", { exact: true })).toBeVisible({ timeout: 10_000 });
  expect(renderPosts).toBe(1);
  const plainDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "자막 없는 MP4 다운로드" }).click();
  expect((await plainDownload).suggestedFilename()).toBe("final.mp4");
  const subtitleDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" }).click();
  expect((await subtitleDownload).suggestedFilename()).toBe("final-subtitled.mp4");
  await page.goto(`/projects/${other}`);
  await expect(page.getByText("다른 프로젝트")).toBeVisible();
  await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
});

test("invalid saved scene blocks save and render until user fixes the draft", async ({ page }) => {
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: id, candidate_ids: [b], invalid_candidate_ids: [b] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: id, candidates: [{ candidate_id: a, source_video_id: source, start_seconds: 1, end_seconds: 2, evidence: [] }] } });
    if (path.endsWith("/rendering")) return route.fulfill({ json: { project_id: id, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: id, run_status: "NOT_STARTED", total_sources: 0, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: id, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: id, project_status: "CREATED", total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0, sources: [] } });
    return route.fulfill({ json: { project_id: id, name: "무효 계획 QA", status: "CREATED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-26T00:00:00Z", updated_at: "2026-10-26T00:00:00Z", source_count: 0, processing: { total_sources: 0, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 0 } } });
  });
  await page.goto(`/projects/${id}`);
  await expect(page.getByText(`무효 후보 · ${b}`)).toBeVisible();
  await expect(page.getByRole("button", { name: "편집 계획 저장" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
});
