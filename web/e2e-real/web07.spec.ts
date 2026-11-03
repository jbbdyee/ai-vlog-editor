import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

const projectId = process.env.WEB07_QA_PROJECT_ID;
const renderId = process.env.WEB07_QA_RENDER_ID?.replaceAll("-", "");
test.skip(!projectId || !renderId, "Use the read-only WEB-07 QA render fixture.");

test("actual QA MP4 variants play, seek and still download", async ({ page, request }) => {
  await page.goto(`/projects/${projectId}`);
  const preview = page.getByLabel("최종 영상 미리보기");
  await expect(preview).toBeVisible();
  const plain = preview.locator("video");
  await expect(plain).toHaveAttribute("src", `/api/projects/${projectId}/renders/${renderId}/download`);
  await expect.poll(() => plain.evaluate((video: HTMLVideoElement) => video.duration)).toBeGreaterThan(5);
  await plain.evaluate(async (video: HTMLVideoElement) => { video.currentTime = 1; await video.play(); });
  await expect.poll(() => plain.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(1.1);
  await expect.poll(() => plain.evaluate((video: HTMLVideoElement) => video.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);

  await preview.getByRole("button", { name: "한국어 하드 자막 영상" }).click();
  const subtitled = preview.locator("video");
  await expect(subtitled).toHaveAttribute("src", `/api/projects/${projectId}/renders/${renderId}/subtitled/download`);
  await expect.poll(() => subtitled.evaluate((video: HTMLVideoElement) => video.duration)).toBeGreaterThan(5);
  await subtitled.evaluate(async (video: HTMLVideoElement) => { video.currentTime = 2; await video.play(); });
  await expect.poll(() => subtitled.evaluate((video: HTMLVideoElement) => video.currentTime)).toBeGreaterThan(2.1);
  await expect.poll(() => subtitled.evaluate((video: HTMLVideoElement) => video.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);
  await subtitled.evaluate((video: HTMLVideoElement) => { video.pause(); video.controls = false; video.style.width = "1000px"; });
  await subtitled.screenshot({ path: "test-results/web07-subtitled.png" });

  for (const [label, suffix] of [["자막 없는 MP4 다운로드", "download"], ["한국어 하드 자막 MP4 다운로드", "subtitled/download"]] as const) {
    const response = await request.get(`http://127.0.0.1:8000/projects/${projectId}/renders/${renderId}/${suffix}`);
    expect(response.status()).toBe(200);
    const expectedHash = createHash("sha256").update(await response.body()).digest("hex");
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: label }).click();
    const download = await downloadPromise;
    const hash = createHash("sha256");
    for await (const chunk of await download.createReadStream()) hash.update(chunk);
    expect(hash.digest("hex")).toBe(expectedHash);
  }
});
