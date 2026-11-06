import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { expect, test, type Download, type Page } from "@playwright/test";

// P1 SRT download on the real 5173 → 8000 stack. Read-only: GET requests only, no render/plan/analysis.
// SRT_PROJECT_ID = an existing project with a COMPLETED, verified render. Optional SRT_RESULT = JSON output path.
const id = process.env.SRT_PROJECT_ID ?? "";
const apiRoot = process.env.SRT_API ?? "http://127.0.0.1:8000";
const resultFile = process.env.SRT_RESULT ?? "";

async function sha256Download(download: Download) {
  const hash = createHash("sha256"); let bytes = 0;
  for await (const chunk of await download.createReadStream()) { hash.update(chunk); bytes += chunk.length; }
  return { hash: hash.digest("hex"), bytes, filename: download.suggestedFilename() };
}

function guardReadOnly(page: Page, seen: string[]) {
  page.on("request", (r) => { if (r.url().includes("/api/") && r.method() !== "GET") seen.push(`${r.method()} ${r.url()}`); });
}

test("SRT button downloads the verified SRT; MP4 buttons unchanged", async ({ page, request }) => {
  test.skip(!id, "SRT_PROJECT_ID required");
  const writes: string[] = []; guardReadOnly(page, writes);
  const rendering = await (await request.get(`${apiRoot}/projects/${id}/rendering`)).json();
  expect(rendering.status).toBe("COMPLETED");
  expect(rendering.subtitle_download_available).toBe(true);
  const etag = async (url: string) => (await request.get(`${apiRoot}${url}`)).headers().etag;
  await page.goto(`/projects/${id}`);
  const srtButton = page.getByRole("button", { name: "자막(SRT) 다운로드" });
  await expect(srtButton).toBeEnabled({ timeout: 30_000 });
  const srtRequest = page.waitForRequest((r) => r.url().endsWith(`/api${rendering.subtitle_download_url}`));
  const srtDl = page.waitForEvent("download");
  await srtButton.click();
  await srtRequest;
  const srt = await sha256Download(await srtDl);
  expect(srt.filename).toBe("final.srt");
  expect(await etag(rendering.subtitle_download_url)).toBe(`"sha256-${srt.hash}"`);

  const plainDl = page.waitForEvent("download");
  await page.getByRole("button", { name: "자막 없는 MP4 다운로드" }).click();
  const plain = await sha256Download(await plainDl);
  expect(plain.filename).toBe("final.mp4");
  expect(await etag(rendering.output.download_url)).toBe(`"sha256-${plain.hash}"`);

  const hardDl = page.waitForEvent("download");
  await page.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" }).click();
  const hard = await sha256Download(await hardDl);
  expect(hard.filename).toBe("final-subtitled.mp4");
  expect(await etag(rendering.hard_subtitle_download_url)).toBe(`"sha256-${hard.hash}"`);

  await page.screenshot({ path: test.info().outputPath("srt-buttons.png"), fullPage: true });
  expect(writes).toEqual([]);
  if (resultFile) writeFileSync(resultFile, JSON.stringify({ render_id: rendering.render_id, srt, plain, hard, writes }, null, 1));
});

test("SRT button is disabled without the new fields and reports a blocked download (simulated in the browser)", async ({ page }) => {
  test.skip(!id, "SRT_PROJECT_ID required");
  const writes: string[] = []; guardReadOnly(page, writes);
  // Older-server shape: drop the new fields from the status response (browser-side only).
  await page.route(`**/api/projects/${id}/rendering`, async (route) => {
    const response = await route.fetch(); const body = await response.json();
    delete body.subtitle_download_available; delete body.subtitle_download_url;
    await route.fulfill({ response, json: body });
  });
  await page.goto(`/projects/${id}`);
  await expect(page.getByRole("button", { name: "자막 없는 MP4 다운로드" })).toBeEnabled({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "자막(SRT) 다운로드" })).toBeDisabled();
  await page.unroute(`**/api/projects/${id}/rendering`);

  // Server refuses the SRT (simulated 409): message shown, nothing saved.
  await page.route("**/api/**/subtitles/download", (route) =>
    route.fulfill({ status: 409, json: { detail: { code: "SUBTITLE_FILE_CORRUPT" } } }));
  await page.reload();
  const button = page.getByRole("button", { name: "자막(SRT) 다운로드" });
  await expect(button).toBeEnabled({ timeout: 30_000 });
  await button.click();
  await expect(page.getByText(/SRT 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다/)).toBeVisible();
  expect(writes).toEqual([]);
});
