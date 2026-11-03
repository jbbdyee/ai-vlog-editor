import { mkdirSync } from "node:fs";
import path from "node:path";
import { expect, test } from "@playwright/test";
import { prepareVideoFrame } from "./capture-video-frame";

// Portfolio screenshots of an existing project (read-only: only the suggestion button is pressed, nothing is saved).
const id = process.env.CAPTURE_PROJECT_ID ?? "";
const out = process.env.CAPTURE_DIR ?? "";
const editRequest = process.env.CAPTURE_REQUEST ?? "음식이 보이는 장면만";

test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });

test("portfolio captures", async ({ page }) => {
  test.skip(!id || !out, "CAPTURE_PROJECT_ID and CAPTURE_DIR required");
  test.setTimeout(180_000);
  mkdirSync(out, { recursive: true });
  const shot = (name: string) => path.join(out, name);
  await page.goto(`/projects/${id}`);
  await expect(page.getByText(/추천 장면 \d+개/)).toBeVisible({ timeout: 30_000 });
  await page.screenshot({ path: shot("00-project-overview.png") });

  const sceneCard = page.locator("#scene-analysis");
  await expect(sceneCard.getByLabel("AI 화면 분석").nth(1)).toBeVisible({ timeout: 30_000 }); // persisted VLM captions
  await sceneCard.getByLabel("장면 후보 목록").scrollIntoViewIfNeeded();
  await sceneCard.locator("div.grid > div").first().screenshot({ path: shot("01-ai-scenes-vlm-captions.png") });

  const selection = page.locator("#scene-selection");
  await selection.getByLabel("원하는 편집을 말로 요청하기").fill(editRequest);
  const suggested = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/edit-suggestions`));
  await selection.getByRole("button", { name: "장면 제안 받기" }).click();
  expect((await suggested).status()).toBe(200);
  await expect(selection.getByText(/AI 해석 · /)).toBeVisible();
  await selection.getByRole("region", { name: "자연어 편집 요청" }).screenshot({ path: shot("02-natural-language-suggestion.png") });

  const render = page.locator("#edit-render > div").nth(1);
  await expect(render.getByRole("button", { name: /자막 없는 MP4 다운로드/ })).toBeEnabled({ timeout: 30_000 });
  await render.getByRole("button", { name: "한국어 하드 자막 영상" }).click();
  await prepareVideoFrame(render.locator('video[aria-label="한국어 하드 자막 최종 영상 재생"]'));
  await render.screenshot({ path: shot("03-render-result-download.png") });
});
