import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

const projectId = process.env.WEB08B_QA_PROJECT_ID;
const existingRenderId = process.env.WEB08B_QA_RENDER_ID;
test.skip(!projectId || !existingRenderId, "Set the isolated QA project and completed render IDs.");

test("completed variants remain playable and downloadable after real API restart", async ({ page, request }) => {
  const renderId = existingRenderId!.replaceAll("-", "");
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByText("이 프로젝트의 렌더 기록")).toBeVisible();
  const preview = page.getByLabel("최종 영상 미리보기");
  await expect(preview).toBeVisible();
  for (const [button, suffix, minTime] of [
    ["자막 없는 영상", "download", 1],
    ["한국어 하드 자막 영상", "subtitled/download", 2],
  ] as const) {
    await preview.getByRole("button", { name: button }).click();
    const video = preview.locator("video");
    await expect(video).toHaveAttribute("src", `/api/projects/${projectId}/renders/${renderId}/${suffix}`);
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.duration)).toBeGreaterThan(1);
    await video.evaluate(async (node: HTMLVideoElement, seek: number) => { node.currentTime = seek; await node.play(); }, minTime);
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.currentTime)).toBeGreaterThan(minTime + 0.1);
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);
  }
  await preview.locator("video").evaluate((node: HTMLVideoElement) => { node.pause(); node.controls = false; });
  await preview.locator("video").screenshot({ path: "test-results/web08b-subtitled.png" });
  for (const [label, suffix] of [["자막 없는 MP4 다운로드", "download"], ["한국어 하드 자막 MP4 다운로드", "subtitled/download"]] as const) {
    const api = await request.get(`http://127.0.0.1:8001/projects/${projectId}/renders/${renderId}/${suffix}`);
    expect(api.status()).toBe(200);
    const expected = createHash("sha256").update(await api.body()).digest("hex");
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: label }).click();
    const download = await ready;
    const hash = createHash("sha256");
    for await (const chunk of await download.createReadStream()) hash.update(chunk);
    expect(hash.digest("hex")).toBe(expected);
  }
});
