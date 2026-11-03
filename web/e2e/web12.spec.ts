import { expect, test } from "@playwright/test";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const a = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const b = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";

for (const width of [320, 375, 390, 430, 1440]) {
  test(`WEB-12 saved review fits ${width}px and never starts a render`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    let posts = 0;
    await page.route(/\/api\/projects\//, async (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: project, candidate_ids: [b, a], invalid_candidate_ids: [] } });
      if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: project, candidates: [
        { candidate_id: a, source_video_id: source, start_seconds: 1.1, end_seconds: 2.35, evidence: [] },
        { candidate_id: b, source_video_id: source, start_seconds: 4, end_seconds: 6.5, evidence: [] },
      ] } });
      if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: project, run_status: "NOT_STARTED", total_sources: 1, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
      if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: project, sources: [] } });
      if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: project, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: source, original_filename: "긴 이름의 촬영 원본.MOV", processing_status: "COMPLETED", stages: [] }] } });
      if (path.endsWith("/rendering")) return route.fulfill({ json: { project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null } });
      if (path.endsWith("/renders")) return route.fulfill({ json: { project_id: project, items: [], next_cursor: null } });
      if (path.endsWith("/render") && route.request().method() === "POST") { posts++; return route.fulfill({ status: 500 }); }
      return route.fulfill({ json: { project_id: project, name: "WEB-12 QA", status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-28T00:00:00Z", updated_at: "2026-10-28T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } } });
    });
    await page.goto(`/projects/${project}`);
    const review = page.getByRole("region", { name: "렌더 전 편집 계획 검토" });
    await expect(review.getByText("저장된 장면 2개 · 예상 길이 3.75초")).toBeVisible();
    await expect(review.getByRole("listitem").first()).toContainText("4.00–6.50초 · 길이 2.50초");
    await expect(review.getByRole("link", { name: "장면 선택·순서 수정" })).toHaveAttribute("href", "#scene-selection");
    const bounds = await page.evaluate(() => {
      const review = document.querySelector('[aria-label="렌더 전 편집 계획 검토"]')!.getBoundingClientRect();
      return { scroll: document.documentElement.scrollWidth, client: document.documentElement.clientWidth, left: review.left, right: review.right };
    });
    expect(bounds.scroll).toBeLessThanOrEqual(bounds.client + 1);
    expect(bounds.left).toBeGreaterThanOrEqual(-1);
    expect(bounds.right).toBeLessThanOrEqual(width + 1);
    expect(posts).toBe(0);
  });
}
