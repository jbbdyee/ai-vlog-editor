import { expect, test } from "@playwright/test";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

for (const width of [320, 375, 390, 430, 1440]) {
  test(`WEB-11 scene order fits ${width}px and survives reload`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    let saved: string[] = [];
    let posts = 0;
    await page.route(/\/api\/projects\//, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/scene-edit-plan")) {
        if (route.request().method() === "PUT") saved = (route.request().postDataJSON() as { candidate_ids: string[] }).candidate_ids;
        return route.fulfill({ json: { project_id: project, candidate_ids: saved, invalid_candidate_ids: [] } });
      }
      if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: project, candidates: [a, b].map((id, index) => ({ candidate_id: id, source_video_id: source, start_seconds: index + 1, end_seconds: index + 2, evidence: [] })) } });
      if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: project, run_status: "NOT_STARTED", total_sources: 1, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
      if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: project, sources: [] } });
      if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: project, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: source, original_filename: "clip.MOV", processing_status: "COMPLETED", stages: [] }] } });
      if (path.endsWith("/rendering")) return route.fulfill({ json: { project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null } });
      if (path.endsWith("/renders")) return route.fulfill({ json: { project_id: project, items: [], next_cursor: null } });
      if (path.endsWith("/render") && route.request().method() === "POST") { posts++; return route.fulfill({ status: 500 }); }
      return route.fulfill({ json: { project_id: project, name: "WEB-11 QA", status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-28T00:00:00Z", updated_at: "2026-10-28T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } } });
    });
    await page.goto(`/projects/${project}`);
    await expect(page.getByText("선택한 장면 0개 / 후보 2개")).toBeVisible();
    await page.getByRole("button", { name: "장면 선택" }).first().click();
    await page.getByRole("button", { name: "장면 선택" }).click();
    await expect(page.getByText("선택한 장면 2개 / 후보 2개")).toBeVisible();
    await expect(page.getByRole("button", { name: "1번 위로" })).toBeDisabled();
    await expect(page.getByRole("button", { name: "2번 아래로" })).toBeDisabled();
    await page.getByRole("button", { name: "2번 위로" }).click();
    await expect(page.getByText("저장되지 않은 변경사항이 있습니다.")).toBeVisible();
    await page.getByRole("button", { name: "편집 계획 저장" }).click();
    await expect(page.getByText("편집 계획 저장 완료.")).toBeVisible();
    expect(saved).toEqual([b, a]);
    await page.reload();
    await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li").first()).toContainText("2.00–3.00초");
    expect(posts).toBe(0);
    const bounds = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth }));
    expect(bounds.scroll).toBeLessThanOrEqual(bounds.client + 1);
  });
}
