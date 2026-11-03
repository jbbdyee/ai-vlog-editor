import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

// QA-04: real Chrome → isolated Vite (CUTORY_API_PROXY_TARGET) → isolated FastAPI → real FFmpeg outputs.
const projectId = process.env.QA04_PROJECT_ID;
const renderUuid = process.env.QA04_RENDER_ID;
const mode = process.env.QA04_MODE ?? "clean";
const api = process.env.QA04_API ?? "http://127.0.0.1:8002";
test.skip(!projectId || !renderUuid, "Set QA04_PROJECT_ID and QA04_RENDER_ID for the isolated QA-04 project.");

test(`QA-04 real render integrity in Chrome (${mode})`, async ({ page, request }) => {
  const renderId = renderUuid!.replaceAll("-", "");
  await page.goto(`/projects/${projectId}`);
  await expect(page.getByText("이 프로젝트의 렌더 기록")).toBeVisible();
  if (mode === "corrupt") {
    await expect(page.getByText(/기록한 SHA-256과 다릅니다/)).toBeVisible();
    await expect(page.getByText(/기본 파일 변형 감지/)).toBeVisible();
    await expect(page.getByLabel("최종 영상 미리보기")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeDisabled();
    const blocked = await request.get(`${api}/projects/${projectId}/renders/${renderId}/download`, { headers: { Range: "bytes=0-" } });
    expect(blocked.status()).toBe(409);
    await page.screenshot({ path: "test-results/qa04-corrupt.png", fullPage: true });
    return;
  }
  const preview = page.getByLabel("최종 영상 미리보기");
  await expect(preview).toBeVisible();
  for (const [button, suffix] of [["자막 없는 영상", "download"], ["한국어 하드 자막 영상", "subtitled/download"]] as const) {
    await preview.getByRole("button", { name: button }).click();
    const video = preview.locator("video");
    await expect(video).toHaveAttribute("src", `/api/projects/${projectId}/renders/${renderId}/${suffix}`);
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.duration)).toBeGreaterThan(5);
    await video.evaluate(async (node: HTMLVideoElement) => { node.muted = true; node.currentTime = 3.6; await node.play(); });
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.currentTime)).toBeGreaterThan(3.8);
    await expect.poll(() => video.evaluate((node: HTMLVideoElement) => node.getVideoPlaybackQuality().totalVideoFrames)).toBeGreaterThan(0);
    await video.evaluate((node: HTMLVideoElement) => { node.pause(); node.controls = false; });
    await video.screenshot({ path: `test-results/qa04-${suffix.replace("/", "-")}.png` });
  }
  for (const [label, suffix] of [["자막 없는 MP4 다운로드", "download"], ["한국어 하드 자막 MP4 다운로드", "subtitled/download"]] as const) {
    const direct = await request.get(`${api}/projects/${projectId}/renders/${renderId}/${suffix}`);
    expect(direct.status()).toBe(200);
    const etag = direct.headers()["etag"];
    const ready = page.waitForEvent("download");
    await page.getByRole("button", { name: label }).click();
    const download = await ready;
    const hash = createHash("sha256");
    for await (const chunk of await download.createReadStream()) hash.update(chunk);
    expect(`"sha256-${hash.digest("hex")}"`).toBe(etag);
  }
});
