import { createHash } from "node:crypto";
import { writeFileSync } from "node:fs";
import { expect, test, type APIRequestContext, type Download } from "@playwright/test";

// QA-06 post-apply verification on the approved demo project only (no upload, no other project touched).
const id = process.env.QA06_PROJECT_ID ?? "";
const apiRoot = process.env.QA06_API ?? "http://127.0.0.1:8000";
const editRequest = process.env.QA06_REQUEST ?? "움직임 위주로 15초 이내";
const resultFile = process.env.QA06_RESULT ?? "";

async function sha256Download(download: Download) {
  const hash = createHash("sha256"); let bytes = 0;
  for await (const chunk of await download.createReadStream()) { hash.update(chunk); bytes += chunk.length; }
  return { hash: hash.digest("hex"), bytes };
}
async function json(request: APIRequestContext, url: string) {
  const response = await request.get(url); expect(response.status()).toBe(200); return response.json();
}

test("QA-06 applied: scene analysis → NL request → save → render → download", async ({ page, request }) => {
  test.skip(!id, "QA06_PROJECT_ID required");
  test.setTimeout(30 * 60_000);
  const api = `${apiRoot}/projects/${id}`;
  const log: Record<string, unknown> = { project_id: id };
  expect((await json(request, `${api}/scene-edit-plan`)).candidate_ids).toEqual([]); // no pre-existing plan
  await page.goto(`/projects/${id}`);
  await expect(page.getByRole("button", { name: "장면 분석 시작" })).toBeEnabled({ timeout: 30_000 });

  let t = Date.now();
  await page.getByRole("button", { name: "장면 분석 시작" }).click();
  await expect.poll(async () => (await json(request, `${api}/scene-processing`)).run_status, { timeout: 15 * 60_000, intervals: [2000] }).toMatch(/^(COMPLETED|COMPLETED_WITH_WARNINGS|FAILED)$/);
  const scene = await json(request, `${api}/scene-processing`);
  log.scene = { status: scene.run_status, s: (Date.now() - t) / 1000, sources: scene.sources };
  expect(scene.run_status).toBe("COMPLETED");
  const candidates = (await json(request, `${api}/scene-candidates`)).candidates as Array<{ start_seconds: number; end_seconds: number; transcript_text: string | null }>;
  log.candidates = candidates.map((c) => [c.start_seconds, c.end_seconds, !!c.transcript_text]);
  expect(candidates.length).toBeGreaterThan(0);
  expect(candidates.every((c) => c.end_seconds - c.start_seconds >= 2.999)).toBe(true);
  await page.reload();
  await expect(page.getByText(`추천 장면 ${candidates.length}개`)).toBeVisible();
  await expect(page.getByLabel("추천 이유").first()).toBeVisible();

  await page.getByLabel("원하는 편집을 말로 요청하기").fill(editRequest);
  const suggested = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/edit-suggestions`));
  await page.getByRole("button", { name: "장면 제안 받기" }).click();
  const suggestion = await (await suggested).json();
  log.request = editRequest; log.suggestion = { ids: suggestion.candidate_ids.length, total: suggestion.total_seconds, reasons: suggestion.scenes.map((s: { reasons: string[] }) => s.reasons), notes: suggestion.notes };
  expect(suggestion.candidate_ids.length).toBeGreaterThan(0);
  expect((await json(request, `${api}/scene-edit-plan`)).candidate_ids).toEqual([]); // suggestion saves nothing
  await page.getByRole("button", { name: "제안을 선택 목록에 적용" }).click();
  const saved = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/scene-edit-plan`) && r.request().method() === "PUT");
  await page.getByRole("button", { name: "편집 계획 저장" }).click();
  expect((await saved).status()).toBe(200);
  expect((await json(request, `${api}/scene-edit-plan`)).candidate_ids).toEqual(suggestion.candidate_ids);

  t = Date.now();
  await page.getByRole("button", { name: "저장된 계획으로 렌더링" }).click();
  await expect.poll(async () => (await json(request, `${api}/rendering`)).status, { timeout: 20 * 60_000, intervals: [2000] }).toMatch(/^(COMPLETED|FAILED|INTERRUPTED|RECONCILIATION_REQUIRED)$/);
  const rendering = await json(request, `${api}/rendering`);
  log.render = { s: (Date.now() - t) / 1000, status: rendering.status, error: rendering.safe_error_code, render_id: rendering.render_id, duration: rendering.output?.duration_seconds,
    integrity: [rendering.integrity_status, rendering.subtitle_integrity_status, rendering.hard_subtitle_integrity_status], hard: rendering.hard_subtitle_status };
  if (resultFile) writeFileSync(resultFile, JSON.stringify(log, null, 1));
  expect(rendering.status).toBe("COMPLETED");
  expect(rendering.integrity_status).toBe("VERIFIED");

  await page.reload();
  await expect(page.getByRole("button", { name: /자막 없는 MP4 다운로드/ })).toBeEnabled({ timeout: 30_000 });
  const plainDl = page.waitForEvent("download");
  await page.getByRole("button", { name: /자막 없는 MP4 다운로드/ }).click();
  const plain = await sha256Download(await plainDl);
  expect((await request.get(`${apiRoot}${rendering.output.download_url}`)).headers().etag).toBe(`"sha256-${plain.hash}"`);
  log.plain = plain;
  if (rendering.hard_subtitle_download_available) {
    const hardDl = page.waitForEvent("download");
    await page.getByRole("button", { name: /한국어 하드 자막 MP4 다운로드/ }).click();
    const hard = await sha256Download(await hardDl);
    expect((await request.get(`${apiRoot}${rendering.hard_subtitle_download_url}`)).headers().etag).toBe(`"sha256-${hard.hash}"`);
    log.subtitled = hard;
  }
  if (resultFile) writeFileSync(resultFile, JSON.stringify(log, null, 1));
  console.log(`QA06_RESULT=${JSON.stringify(log)}`);
});
