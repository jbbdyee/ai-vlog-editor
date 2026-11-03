import { expect, test } from "@playwright/test";

const projectId = process.env.WEB06_PROJECT_ID;
test.skip(!projectId, "Set WEB06_PROJECT_ID to an existing isolated local project with source videos.");

test("registered MOV sources and candidate range play through real FastAPI", async ({ page }) => {
  await page.goto(`/projects/${projectId}`);
  const player = page.locator("video[aria-label$='재생']");
  await expect(player).toBeVisible();
  const source = page.getByLabel("원본 영상", { exact: true });
  await expect(source.locator("option")).toHaveCount(2);
  const media = player.locator("xpath=.");
  const first = await media.evaluate((element: HTMLVideoElement) => new Promise<{ duration: number; width: number; height: number; error: number | null }>((resolve) => {
    const result = () => ({ duration: element.duration, width: element.videoWidth, height: element.videoHeight, error: element.error?.code ?? null });
    if (element.readyState >= 1 || element.error) return resolve(result());
    element.addEventListener("loadedmetadata", () => resolve(result()), { once: true });
    element.addEventListener("error", () => resolve(result()), { once: true });
  }));
  console.log("WEB06_FIRST_MEDIA", first);
  expect(first.error).toBeNull();
  expect(first.width).toBeGreaterThan(0);
  expect(first.height).toBeGreaterThan(0);
  await media.evaluate(async (element: HTMLVideoElement) => { element.currentTime = 5; await element.play(); });
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(5);
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);
  await source.selectOption({ index: 1 });
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.duration)).toBeGreaterThan(20);
  await media.evaluate(async (element: HTMLVideoElement) => { element.currentTime = 8; await element.play(); });
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(8);
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);
  await page.getByRole("button", { name: "이 구간 미리보기" }).first().click();
  await expect(page.getByText(/후보 2\.44–2\.62초/)).toBeVisible();
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThanOrEqual(2.60);
  await expect.poll(() => media.evaluate((element: HTMLVideoElement) => element.paused)).toBe(true);
  expect(await media.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeLessThanOrEqual(2.63);
});
