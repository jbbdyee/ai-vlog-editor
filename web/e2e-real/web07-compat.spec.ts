import { expect, test } from "@playwright/test";

const projectId = process.env.WEB07_QA_PROJECT_ID;
const renderId = process.env.WEB07_QA_RENDER_ID?.replaceAll("-", "");
test.skip(!projectId || !renderId, "Existing QA render IDs are required.");

test("existing render download URLs can stream in Chrome", async ({ page }) => {
  await page.goto(`/projects/${projectId}`);
  for (const suffix of ["download", "subtitled/download"]) {
    const outcome = await page.evaluate(async (url) => {
      const video = document.createElement("video");
      video.preload = "metadata";
      video.src = url;
      document.body.append(video);
      const result = await new Promise<{ duration: number; error: number | null }>((resolve) => {
        video.addEventListener("loadedmetadata", () => resolve({ duration: video.duration, error: null }), { once: true });
        video.addEventListener("error", () => resolve({ duration: 0, error: video.error?.code ?? -1 }), { once: true });
      });
      video.remove();
      return result;
    }, `/api/projects/${projectId}/renders/${renderId}/${suffix}`);
    console.log(suffix, outcome);
    expect(outcome.error).toBeNull();
    expect(outcome.duration).toBeGreaterThan(5);
  }
});
