import { expect, type Locator } from "@playwright/test";

/** Decode a frame after seeking before taking a portfolio screenshot. */
export async function prepareVideoFrame(video: Locator): Promise<void> {
  await expect(video).toBeVisible();
  await video.evaluate(async (element: HTMLVideoElement) => {
    if (element.readyState < HTMLMediaElement.HAVE_METADATA) {
      await new Promise<void>((resolve, reject) => {
        element.addEventListener("loadedmetadata", () => resolve(), { once: true });
        element.addEventListener("error", () => reject(new Error("Video metadata failed to load")), { once: true });
      });
    }
    element.muted = true;
    const target = Math.min(3.5, Math.max(0, element.duration - 0.5));
    if (target > 0) {
      element.currentTime = target;
      await new Promise<void>((resolve, reject) => {
        element.addEventListener("seeked", () => resolve(), { once: true });
        element.addEventListener("error", () => reject(new Error("Video seek failed")), { once: true });
      });
    }
    await element.play();
    if ("requestVideoFrameCallback" in element) {
      await new Promise<void>((resolve) => element.requestVideoFrameCallback(() => resolve()));
    }
    element.pause();
  });
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) =>
    element.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    (element.getVideoPlaybackQuality?.().totalVideoFrames ?? 0) > 0), { timeout: 15_000 }).toBe(true);
}
