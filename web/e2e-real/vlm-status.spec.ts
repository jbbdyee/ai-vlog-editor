import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

// P1 VLM status restore on the real 5173 → 8000 stack. Read-only: no clicks on analysis buttons, any non-GET /api request fails.
// VLM_DONE_ID = project whose captions are stored (expects 8/8). VLM_EMPTY_ID = project with candidates but no captions.
// VLM_SHOT = optional output folder for a screenshot of the demo project's status (demo only; no personal projects captured).
const done = process.env.VLM_DONE_ID ?? "";
const empty = process.env.VLM_EMPTY_ID ?? "";
const shot = process.env.VLM_SHOT ?? "";

function guardReadOnly(page: Page) {
  const writes: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/") && r.method() !== "GET") writes.push(`${r.method()} ${r.url()}`); });
  return writes;
}

test("restored COMPLETED status is shown for stored captions", async ({ page }) => {
  test.skip(!done, "VLM_DONE_ID required");
  const writes = guardReadOnly(page);
  const vision = page.waitForResponse((r) => r.url().endsWith(`/projects/${done}/scene-vision`) && r.request().method() === "GET");
  await page.goto(`/projects/${done}`);
  expect(await (await vision).json()).toMatchObject({ status: "COMPLETED", total: 8, captioned: 8, state_source: "DATABASE" });
  const region = page.getByRole("region", { name: "AI 화면 분석" });
  await expect(region).toContainText("gemma3:4b · 분석 8/8", { timeout: 30_000 });
  await expect(region).not.toContainText("실패");
  await expect(region.getByRole("button", { name: "AI 화면 분석 (VLM)" })).toBeEnabled();
  if (shot) {
    await region.screenshot({ path: path.join(shot, "vlm-status-restored-demo-region.png") });
    const card = page.locator("[data-slot=card]").filter({ has: page.getByRole("heading", { name: "AI 추천 장면" }) });
    await card.locator("[data-slot=card-header]").evaluate((el) => el.scrollIntoView());
    await page.screenshot({ path: path.join(shot, "vlm-status-restored-demo-viewport.png") });
  }
  expect(writes).toEqual([]);
});

test("project without captions keeps the not-started guidance", async ({ page }) => {
  test.skip(!empty, "VLM_EMPTY_ID required");
  const writes = guardReadOnly(page);
  const vision = page.waitForResponse((r) => r.url().endsWith(`/projects/${empty}/scene-vision`) && r.request().method() === "GET");
  await page.goto(`/projects/${empty}`);
  expect(await (await vision).json()).toMatchObject({ status: "NOT_STARTED", captioned: 0, state_source: "DATABASE" });
  const region = page.getByRole("region", { name: "AI 화면 분석" });
  await expect(region).toContainText("대표 프레임 3장으로 장면마다 보이는 것을 설명합니다.", { timeout: 30_000 });
  await expect(region).not.toContainText("분석 0/");
  expect(writes).toEqual([]); // no screenshot: this is not the public demo project
});
