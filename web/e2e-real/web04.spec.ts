import { createHash } from "node:crypto";
import { createReadStream } from "node:fs";
import path from "node:path";
import { expect, test, type APIRequestContext, type Download } from "@playwright/test";

const clips = ["P1_S01_take01.MOV", "P1_S02_take01.MOV"];
const sourcePaths = clips.map((name) => path.resolve(import.meta.dirname, "../../evaluation/data/P1", name));
const apiRoot = "http://127.0.0.1:8000";

async function sha256File(file: string): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of createReadStream(file)) hash.update(chunk);
  return hash.digest("hex");
}
async function sha256Download(download: Download): Promise<string> {
  const hash = createHash("sha256");
  for await (const chunk of await download.createReadStream()) hash.update(chunk);
  return hash.digest("hex");
}
async function readJson(request: APIRequestContext, url: string) {
  const response = await request.get(url);
  expect(response.status()).toBe(200);
  return response.json();
}

test("WEB-04 real two-source browser journey", async ({ page, request }) => {
  const originalHashes = await Promise.all(sourcePaths.map(sha256File));
  let id = process.env.WEB04_RESUME_PROJECT_ID;
  if (!id) {
    await page.goto("/");
    await expect(page.getByLabel("프로젝트 이름")).toBeVisible();
    await page.getByLabel("프로젝트 이름").fill(`WEB-04 두 영상 QA ${Date.now()}`);
    const createdResponse = page.waitForResponse((response) => response.url().endsWith("/api/projects") && response.request().method() === "POST");
    await page.getByRole("button", { name: "프로젝트 만들기" }).click();
    const created = await createdResponse;
    expect(created.status()).toBe(201);
    id = (await created.json()).project_id as string;
    console.log(`WEB04_PROJECT_ID=${id}`);
  }
  await page.goto(`/projects/${id}`);
  await expect(page.getByText("촬영 영상 등록")).toBeVisible();
  const api = `${apiRoot}/projects/${id}`;

  for (let index = 0; index < sourcePaths.length; index++) {
    const before = await readJson(request, `${api}/processing`);
    if (before.sources.some((item: { original_filename: string }) => item.original_filename === clips[index])) continue;
    await page.getByLabel("영상 파일").setInputFiles(sourcePaths[index]);
    const responsePromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/sources`) && response.request().method() === "POST", { timeout: 180_000 });
    await page.getByRole("button", { name: "파일 등록" }).click();
    const response = await responsePromise;
    expect(response.status()).toBe(201);
    const registered = await response.json();
    console.log(`WEB04_SOURCE_${index + 1}=${registered.source_video_id};NAME=${registered.original_filename}`);
    await expect(page.getByText(`서버 등록 완료 · ${clips[index]}`, { exact: false })).toBeVisible();
  }
  const registered = await readJson(request, `${api}/processing`);
  expect(registered.total_sources).toBe(2);
  const sourceIds = Object.fromEntries(registered.sources.map((item: { original_filename: string; source_video_id: string }) => [item.original_filename, item.source_video_id]));

  if (registered.completed_count < 2) {
    const acceptedPromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/process`) && response.request().method() === "POST");
    await page.getByRole("button", { name: "영상 처리 시작" }).click();
    expect((await acceptedPromise).status()).toBe(202);
  }
  await expect.poll(async () => (await readJson(request, `${api}/processing`)).completed_count as number, { timeout: 180_000, intervals: [2000] }).toBe(2);
  const processed = await readJson(request, `${api}/processing`);
  expect(processed.failed_count).toBe(0);
  console.log(`WEB04_PROCESS=${processed.project_status};COMPLETED=${processed.completed_count}`);
  await page.reload();
  await expect(page.getByText("P1_S01_take01.MOV", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("P1_S02_take01.MOV", { exact: true }).first()).toBeVisible();

  let candidates = await readJson(request, `${api}/scene-candidates`);
  if (candidates.candidates.length === 0) {
    const acceptedPromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/scene-process`) && response.request().method() === "POST");
    await page.getByRole("button", { name: "장면 분석 시작" }).click();
    expect((await acceptedPromise).status()).toBe(202);
    await expect.poll(async () => (await readJson(request, `${api}/scene-processing`)).run_status as string, { timeout: 180_000, intervals: [2000] }).toMatch(/^(COMPLETED|COMPLETED_WITH_WARNINGS|FAILED)$/);
  }
  candidates = await readJson(request, `${api}/scene-candidates`);
  const diagnostics = await readJson(request, `${api}/scene-diagnostics`);
  expect(candidates.candidates.length).toBeGreaterThan(1);
  expect(diagnostics.sources.length).toBe(2);
  for (const sourceId of Object.values(sourceIds)) expect(candidates.candidates.some((item: { source_video_id: string }) => item.source_video_id === sourceId)).toBe(true);
  console.log(`WEB04_SCENE_CANDIDATES=${candidates.candidates.length};DIAGNOSTICS=${diagnostics.sources.length}`);
  await expect(page.getByRole("list", { name: "장면 후보 목록" }).locator("li")).toHaveCount(candidates.candidates.length);
  await page.getByText("원본 진단값 보기").first().click();
  await expect(page.getByText(/"evidence_counts"/).first()).toBeVisible();

  const selected = clips.map((name) => [...candidates.candidates].filter((item: { source_video_id: string }) => item.source_video_id === sourceIds[name]).sort((left: { start_seconds: number; end_seconds: number }, right: { start_seconds: number; end_seconds: number }) => (right.end_seconds - right.start_seconds) - (left.end_seconds - left.start_seconds))[0]);
  for (const candidate of selected) {
    await page.getByRole("list", { name: "선택 가능한 장면" }).locator("li").filter({ hasText: candidate.candidate_id }).getByRole("button", { name: "장면 선택" }).click();
  }
  await page.getByRole("button", { name: "2번 위로" }).click();
  await expect(page.getByText("저장되지 않은 변경사항이 있습니다.")).toBeVisible();
  const savePromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/scene-edit-plan`) && response.request().method() === "PUT");
  await page.getByRole("button", { name: "편집 계획 저장" }).click();
  expect((await savePromise).status()).toBe(200);
  const expectedOrder = [selected[1].candidate_id, selected[0].candidate_id];
  expect((await readJson(request, `${api}/scene-edit-plan`)).candidate_ids).toEqual(expectedOrder);
  await page.reload();
  await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li").first()).toContainText(expectedOrder[0]);
  await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li").last()).toContainText(expectedOrder[1]);
  console.log(`WEB04_PLAN_ORDER=${expectedOrder.join(",")}`);

  const postPromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/render`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "저장된 계획으로 렌더링" }).click();
  expect((await postPromise).status()).toBe(202);
  const runAtReload = await readJson(request, `${api}/rendering`);
  console.log(`WEB04_RENDER_AT_RELOAD=${runAtReload.status}`);
  await page.reload();
  await expect(page.getByText("최종 영상 렌더링")).toBeVisible();
  if (runAtReload.is_active) {
    await expect(page.getByRole("button", { name: "렌더링 중…" })).toBeDisabled();
    const duplicate = await request.post(`${api}/render`);
    expect(duplicate.status()).toBe(409);
    console.log(`WEB04_DUPLICATE_RENDER=${duplicate.status()}`);
  }
  await expect.poll(async () => (await readJson(request, `${api}/rendering`)).status as string, { timeout: 180_000, intervals: [2000] }).toMatch(/^(COMPLETED|FAILED)$/);
  const final = await readJson(request, `${api}/rendering`);
  console.log(`WEB04_RENDER=${final.status};ID=${final.render_id};SUBTITLE=${final.hard_subtitle_status};ERROR=${final.hard_subtitle_error_code}`);
  expect(final.status).toBe("COMPLETED");
  expect(final.download_available).toBe(true);
  expect(final.hard_subtitle_download_available).toBe(true);
  await expect(page.getByText("렌더 완료", { exact: true })).toBeVisible({ timeout: 10_000 });

  for (const [name, downloadPath, buttonName] of [
    ["final.mp4", final.output.download_url, "자막 없는 MP4 다운로드"],
    ["final-subtitled.mp4", final.hard_subtitle_download_url, "한국어 하드 자막 MP4 다운로드"],
  ] as const) {
    const apiResponse = await request.get(`${apiRoot}${downloadPath}`);
    expect(apiResponse.status()).toBe(200);
    expect(apiResponse.headers()["content-type"]).toContain("video/mp4");
    const apiHash = createHash("sha256").update(await apiResponse.body()).digest("hex");
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: buttonName }).click();
    const download = await downloadPromise;
    expect(download.suggestedFilename()).toBe(name);
    expect(await sha256Download(download)).toBe(apiHash);
    console.log(`WEB04_DOWNLOAD=${name};SHA256=${apiHash}`);
  }
  expect(await Promise.all(sourcePaths.map(sha256File))).toEqual(originalHashes);
  console.log(`WEB04_ORIGINAL_SHA256=${originalHashes.join(",")}`);
});
