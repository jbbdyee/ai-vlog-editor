import { createHash } from "node:crypto";
import { createReadStream, mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Download } from "@playwright/test";
import { prepareVideoFrame } from "./capture-video-frame";

// Portfolio demo: one real video from upload to MP4 download in real Chrome.
// Isolated stack only: DEMO_API must be the isolated API (never the dev 8000), baseURL its own Vite.
const sourcePath = process.env.DEMO_SOURCE ?? "";
const apiRoot = process.env.DEMO_API ?? "";
const editRequest = process.env.DEMO_REQUEST ?? "움직임 위주로 15초 이내";
const shots = process.env.DEMO_SHOTS ?? "";

async function sha256File(file: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
async function sha256Download(download: Download): Promise<{ hash: string; bytes: number }> {
  const hash = createHash("sha256"); let bytes = 0;
  for await (const chunk of await download.createReadStream()) { hash.update(chunk); bytes += chunk.length; }
  return { hash: hash.digest("hex"), bytes };
}
async function json(request: APIRequestContext, url: string) {
  const response = await request.get(url);
  expect(response.status()).toBe(200);
  return response.json();
}

test("DEMO-01 one real video: upload → AI scenes → natural-language edit → render → download", async ({ page, request }) => {
  test.skip(!sourcePath || !apiRoot || apiRoot.endsWith(":8000"), "requires DEMO_SOURCE and an isolated DEMO_API");
  test.setTimeout(45 * 60_000);
  if (shots) mkdirSync(shots, { recursive: true });
  const shot = async (name: string) => { if (shots) await page.screenshot({ path: path.join(shots, `${name}.png`), fullPage: false }); };
  const log: Record<string, unknown> = {};
  const sourceHash = await sha256File(sourcePath);

  await page.goto("/");
  await page.getByLabel("프로젝트 이름").fill(`포트폴리오 시연 ${new Date().toISOString().slice(0, 16)}`);
  const created = page.waitForResponse((r) => r.url().endsWith("/api/projects") && r.request().method() === "POST");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  const id = (await (await created).json()).project_id as string;
  log.project_id = id;
  await expect(page.getByText("촬영 영상 등록")).toBeVisible();
  const api = `${apiRoot}/projects/${id}`;

  let t = Date.now();
  await page.getByLabel("영상 파일").setInputFiles(sourcePath);
  const uploaded = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/sources`) && r.request().method() === "POST", { timeout: 600_000 });
  await page.getByRole("button", { name: "파일 등록" }).click();
  expect((await uploaded).status()).toBe(201);
  await expect(page.getByText("서버 등록 완료", { exact: false })).toBeVisible();
  log.upload_s = (Date.now() - t) / 1000;

  t = Date.now();
  await page.getByRole("button", { name: "영상 처리 시작" }).click();
  await expect.poll(async () => (await json(request, `${api}/processing`)).project_status, { timeout: 30 * 60_000, intervals: [5000] }).toMatch(/COMPLETED|FAILED/);
  const processing = await json(request, `${api}/processing`);
  expect(processing.project_status).toBe("COMPLETED");
  log.processing_s = (Date.now() - t) / 1000;
  await page.reload();
  await shot("01-processed");

  t = Date.now();
  await page.getByRole("button", { name: "장면 분석 시작" }).click();
  await expect.poll(async () => (await json(request, `${api}/scene-processing`)).run_status, { timeout: 20 * 60_000, intervals: [3000] }).toMatch(/^COMPLETED|FAILED/);
  log.scene_s = (Date.now() - t) / 1000;
  const candidates = (await json(request, `${api}/scene-candidates`)).candidates as Array<{ candidate_id: string; start_seconds: number; end_seconds: number; transcript_text: string | null; evidence: Array<{ evidence_type: string }> }>;
  log.candidates = candidates.map((c) => ({ start: c.start_seconds, end: c.end_seconds, speech: c.transcript_text, types: [...new Set(c.evidence.map((e) => e.evidence_type))] }));
  expect(candidates.length).toBeGreaterThan(0);
  expect(candidates.every((c) => c.end_seconds - c.start_seconds >= 2.999)).toBe(true);
  await page.reload();
  await expect(page.getByText(`추천 장면 ${candidates.length}개`)).toBeVisible();
  await expect(page.getByLabel("추천 이유").first()).toBeVisible();
  await page.locator("#scene-analysis").scrollIntoViewIfNeeded();
  await shot("02-ai-scenes");

  // Preview one recommended scene in the source player.
  await page.getByRole("button", { name: "이 구간 미리보기" }).first().click();
  await expect(page.locator("#source-preview video")).toBeVisible();
  await shot("03-preview");

  // Natural-language request → suggestion → apply → save.
  await page.locator("#scene-selection").scrollIntoViewIfNeeded();
  await page.getByLabel("원하는 편집을 말로 요청하기").fill(editRequest);
  const suggested = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/edit-suggestions`));
  await page.getByRole("button", { name: "장면 제안 받기" }).click();
  const suggestion = await (await suggested).json();
  log.request = editRequest; log.suggestion = suggestion;
  expect(suggestion.candidate_ids.length).toBeGreaterThan(0);
  await expect(page.getByLabel("편집 제안")).toBeVisible();
  await shot("04-nl-suggestion");
  await page.getByRole("button", { name: "제안을 선택 목록에 적용" }).click();
  const saved = page.waitForResponse((r) => r.url().endsWith(`/api/projects/${id}/scene-edit-plan`) && r.request().method() === "PUT");
  await page.getByRole("button", { name: "편집 계획 저장" }).click();
  expect((await saved).status()).toBe(200);
  expect((await json(request, `${api}/scene-edit-plan`)).candidate_ids).toEqual(suggestion.candidate_ids);
  await expect(page.getByRole("region", { name: "렌더 전 편집 계획 검토" })).toContainText(`저장된 장면 ${suggestion.candidate_ids.length}개`);

  t = Date.now();
  await page.getByRole("button", { name: "저장된 계획으로 렌더링" }).click();
  await expect.poll(async () => (await json(request, `${api}/rendering`)).status, { timeout: 20 * 60_000, intervals: [2000] }).toMatch(/COMPLETED|FAILED/);
  const rendering = await json(request, `${api}/rendering`);
  log.render_s = (Date.now() - t) / 1000; log.rendering = rendering;
  expect(rendering.status).toBe("COMPLETED");
  expect(rendering.integrity_status).toBe("VERIFIED");
  await page.reload();
  await page.locator("#edit-render").scrollIntoViewIfNeeded();
  await expect(page.getByRole("button", { name: /자막 없는 MP4 다운로드/ })).toBeEnabled({ timeout: 30_000 });
  await page.getByRole("button", { name: "한국어 하드 자막 영상" }).click();
  await prepareVideoFrame(page.locator('#edit-render video[aria-label="한국어 하드 자막 최종 영상 재생"]'));
  await shot("05-rendered");

  const plainDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: /자막 없는 MP4 다운로드/ }).click();
  const plain = await sha256Download(await plainDownload);
  const serverPlain = await request.get(`${apiRoot}${rendering.output.download_url}`);
  expect(serverPlain.headers().etag).toBe(`"sha256-${plain.hash}"`);
  log.plain = plain;
  if (rendering.hard_subtitle_download_available) {
    const hardDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: /한국어 하드 자막 MP4 다운로드/ }).click();
    log.subtitled = await sha256Download(await hardDownload);
  }
  expect(await sha256File(sourcePath)).toBe(sourceHash); // the original is never modified
  if (shots) writeFileSync(path.join(shots, "demo-result.json"), JSON.stringify(log, null, 1));
  console.log(`DEMO01_RESULT=${JSON.stringify({ ...log, candidates: (log.candidates as unknown[]).length })}`);
});
