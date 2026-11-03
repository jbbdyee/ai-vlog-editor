import { devices, expect, test, type Page } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
const sourceId = "22222222-2222-4222-8222-222222222222";
const candidateId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const renderId = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const name = "아주긴프로젝트제목띄어쓰기없는긴문자열";
const filename = "very-long-unbroken-source-filename-with-korean-영상-촬영본.MOV";

async function mockProject(page: Page) {
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/scene-edit-plan")) return route.fulfill({ json: { project_id: id, candidate_ids: [candidateId], invalid_candidate_ids: [] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: id, candidates: [{ candidate_id: candidateId, source_video_id: sourceId, start_seconds: 1, end_seconds: 3, evidence: [] }] } });
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: id, run_status: "COMPLETED", total_sources: 1, processed_count: 1, completed_count: 1, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: id, sources: [] } });
    if (path.endsWith("/processing")) return route.fulfill({ json: { project_id: id, project_status: "COMPLETED", total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1, sources: [{ source_video_id: sourceId, original_filename: filename, processing_status: "COMPLETED", stages: [] }] } });
    if (path.endsWith("/rendering")) return route.fulfill({ json: { project_id: id, status: "COMPLETED", render_id: renderId, is_active: false, succeeded: true, failed: false, safe_error_code: null, download_available: true, output: { filename: "final.mp4", duration_seconds: 2, video_codec: "h264", audio_codec: "aac", file_size_bytes: 100, download_url: `/projects/${id}/renders/${renderId.replaceAll("-", "")}/download` }, hard_subtitle_status: "AVAILABLE", hard_subtitle_error_code: null, hard_subtitle_download_available: true, hard_subtitle_download_url: `/projects/${id}/renders/${renderId.replaceAll("-", "")}/subtitled/download` } });
    if (path.endsWith("/renders")) return route.fulfill({ json: { project_id: id, items: [], next_cursor: null } });
    if (path.includes("/media") || path.endsWith("/download")) return route.fulfill({ status: 404, body: "mock media unavailable" });
    return route.fulfill({ json: { project_id: id, name, status: "COMPLETED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-27T00:00:00Z", updated_at: "2026-10-27T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 1, failed_count: 0, blocked_count: 0, remaining_count: 0, progress_ratio: 1 } } });
  });
}

async function assertNoPageOverflow(page: Page) {
  const result = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    page: document.documentElement.scrollWidth,
    offenders: [...document.querySelectorAll<HTMLElement>("body *")]
      .filter((node) => { const rect = node.getBoundingClientRect(); return !node.closest(".overflow-hidden") && rect.width > 0 && (rect.right > innerWidth + 1 || rect.left < -1); })
      .slice(0, 8).map((node) => `${node.tagName}.${node.className?.toString().slice(0, 60)}`),
  }));
  expect(result.page, JSON.stringify(result)).toBeLessThanOrEqual(result.viewport + 1);
  expect(result.offenders, JSON.stringify(result)).toEqual([]);
}

for (const width of [320, 375, 390, 430, 1440]) {
  test(`${width}px home and full project layout remain within viewport`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    await page.goto("/");
    await expect(page.getByRole("heading", { name: /장면을 찾는 일부터/ })).toBeVisible();
    await assertNoPageOverflow(page);
    await mockProject(page);
    await page.goto(`/projects/${id}`);
    await expect(page.getByRole("heading", { name })).toBeVisible();
    await expect(page.getByRole("heading", { name: "촬영 영상 등록" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "최종 영상 렌더링" })).toBeVisible();
    await expect(page.getByText("추천 장면 1개")).toBeVisible();
    await expect(page.getByText("소스 진단 0건")).toBeVisible();
    await expect(page.getByText(filename).first()).toBeVisible();
    await assertNoPageOverflow(page);
    const steps = await page.getByRole("navigation", { name: "영상 작업 단계" }).getByRole("link").evaluateAll((links) => links.map((link) => {
      const rect = link.getBoundingClientRect();
      return { left: rect.left, right: rect.right };
    }));
    expect(steps).toHaveLength(5);
    expect(steps.every(({ left, right }) => left >= -1 && right <= width + 1)).toBe(true);
    if (width === 320 || width === 1440) await page.screenshot({ path: `test-results/web09-${width}.png`, fullPage: true });
    await page.getByRole("navigation", { name: "영상 작업 단계" }).getByRole("link", { name: /편집·렌더/ }).click();
    await expect(page).toHaveURL(/#edit-render$/);
    await assertNoPageOverflow(page);
    if (width < 640) {
      const navTop = await page.getByRole("navigation", { name: "영상 작업 단계" }).evaluate((node) => node.getBoundingClientRect().top);
      expect(navTop).toBeGreaterThanOrEqual(0);
      expect(navTop).toBeLessThan(90);
    }
    await expect(page.getByRole("button", { name: "편집 계획 저장" })).toBeVisible();
    await expect(page.locator("video")).toHaveCount(2);
    const playerWidths = await page.locator("video").evaluateAll((players) => players.map((player) => player.getBoundingClientRect().width));
    expect(playerWidths.every((playerWidth) => playerWidth <= width)).toBe(true);
  });
}

test.describe("iPhone 13 mini mobile viewport", () => {
  test.use({ isMobile: true, hasTouch: true, deviceScaleFactor: 3, userAgent: devices["iPhone 13 Mini"].userAgent });

  for (const width of [300, 375]) {
    test(`${width}px layout and visible component bounds`, async ({ page }) => {
      await page.setViewportSize({ width, height: 629 });
      await page.goto("/");
      await assertNoPageOverflow(page);
      await mockProject(page);
      await page.goto(`/projects/${id}`);
      await expect(page.getByRole("heading", { name })).toBeVisible();
      await assertNoPageOverflow(page);
      if (width === 375) await page.screenshot({ path: "test-results/web09b-iphone-375.png", fullPage: true });
      const boxes = await page.evaluate(() => {
        const selectors = ["html", "body", "#root", "main", "nav", "#upload", "#video-file", "#processing"];
        return { visualWidth: visualViewport?.width ?? innerWidth, layoutWidth: document.documentElement.clientWidth,
          boxes: selectors.map((selector) => { const rect = document.querySelector(selector)!.getBoundingClientRect(); return { selector, left: rect.left, right: rect.right }; }) };
      });
      expect(boxes.layoutWidth).toBe(width);
      expect(boxes.visualWidth).toBe(width);
      for (const box of boxes.boxes) {
        expect(box.left, `${width}px ${box.selector} left`).toBeGreaterThanOrEqual(-1);
        expect(box.right, `${width}px ${box.selector} right`).toBeLessThanOrEqual(width + 1);
      }
      await page.getByRole("navigation", { name: "영상 작업 단계" }).getByRole("link", { name: /영상 등록/ }).click();
      await expect(page).toHaveURL(/#upload$/);
      await assertNoPageOverflow(page);
    });
  }
});
