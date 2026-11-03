import { expect, test } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
for (const width of [320, 375, 390, 430, 1440]) {
  test(`project list fits ${width}px and opens a project`, async ({ page }) => {
    await page.setViewportSize({ width, height: 780 });
    await page.route("**/api/projects?*", (route) => route.fulfill({ json: { items: [{ project_id: id, name: "긴프로젝트이름띄어쓰기없는긴제목".repeat(3), created_at: "2026-10-28T00:00:00Z", updated_at: "2026-10-28T00:00:00Z", source_count: 2, has_edit_plan: true, latest_render_status: null }], next_offset: null } }));
    await page.route(`**/api/projects/${id}**`, (route) => route.fulfill({ status: 404, json: { detail: { code: "PROJECT_NOT_FOUND" } } }));
    await page.goto("/");
    const card = page.getByRole("link", { name: /긴프로젝트이름/ });
    await expect(card).toBeVisible();
    const bounds = await page.evaluate(() => ({ page: document.documentElement.scrollWidth, viewport: document.documentElement.clientWidth }));
    expect(bounds.page).toBeLessThanOrEqual(bounds.viewport + 1);
    const box = await card.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(width + 1);
    await card.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}$`));
  });
}
