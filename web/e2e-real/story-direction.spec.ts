import path from "node:path";
import { expect, test } from "@playwright/test";

// TODO 1 on the real 5173 → 8000 stack: press "추천 편집 방향 만들기" and see chapters.
// STORY_IDS = comma-separated project ids. STORY_SHOT = optional folder for a screenshot of the card only (no video frames).
// The only allowed non-GET request is the read-only POST /story-direction (local Ollama call, nothing saved).
const ids = (process.env.STORY_IDS ?? "").split(",").filter(Boolean);
const shot = process.env.STORY_SHOT ?? "";

for (const id of ids) {
  test(`story direction for ${id.slice(0, 8)}`, async ({ page }) => {
    const writes: string[] = [];
    page.on("request", (r) => {
      if (r.url().includes("/api/") && r.method() !== "GET" && !r.url().endsWith(`/projects/${id}/story-direction`)) writes.push(`${r.method()} ${r.url()}`);
    });
    await page.goto(`/projects/${id}`);
    const card = page.locator("#story-direction");
    await card.scrollIntoViewIfNeeded();
    const response = page.waitForResponse((r) => r.url().endsWith(`/projects/${id}/story-direction`), { timeout: 120_000 });
    await card.getByRole("button", { name: /추천 편집 방향 만들기/ }).click();
    expect((await response).status()).toBe(200);
    await expect(card.getByText(/챕터 1\./)).toBeVisible({ timeout: 30_000 });
    await expect(card.getByRole("button", { name: "미리보기" }).first()).toBeVisible();
    if (shot) await card.screenshot({ path: path.join(shot, `story-direction-${id.slice(0, 8)}.png`) });
    // TODO 2: fill the edit plan (unsaved) in chapter order — no save request may be sent.
    await card.getByRole("button", { name: /이 방향으로 편집 계획 만들기/ }).click();
    const plan = page.locator("#scene-selection");
    await expect(plan.getByText(/챕터 순서대로 채웠습니다/)).toBeVisible();
    await expect(plan.getByRole("list", { name: "선택한 장면 순서" }).getByText(/챕터 1\./).first()).toBeVisible();
    await expect(plan.getByText("저장되지 않은 변경사항이 있습니다.")).toBeVisible();
    if (shot) await plan.getByRole("list", { name: "선택한 장면 순서" }).screenshot({ path: path.join(shot, `edit-plan-${id.slice(0, 8)}.png`) });
    expect(writes).toEqual([]);
  });
}
