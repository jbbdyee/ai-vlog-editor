import path from "node:path";
import { expect, test } from "@playwright/test";

const videoPath = path.resolve(import.meta.dirname, "../../evaluation/data/P1/P1_S01_take01.MOV");
const absentId = "99999999-9999-4999-8999-999999999999";

test("real FastAPI, PostgreSQL and P1-S01 browser flow", async ({ page, request }) => {
  const label = `WEB-01B QA ${Date.now()}`;
  await page.goto("/");
  await expect(page.getByLabel("프로젝트 이름")).toBeVisible();

  await page.getByLabel("프로젝트 ID").fill(absentId);
  await page.getByRole("button", { name: "ID로 열기" }).click();
  await expect(page.getByRole("alert")).toContainText("PROJECT_NOT_FOUND");

  await page.getByLabel("프로젝트 이름").fill(label);
  const createdResponse = page.waitForResponse((response) => response.url().endsWith("/api/projects") && response.request().method() === "POST");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  const created = await createdResponse;
  expect(created.status()).toBe(201);
  const project = await created.json();
  const id = project.project_id as string;
  console.log(`REAL_PROJECT_ID=${id}`);
  await expect(page).toHaveURL(`/projects/${id}`);

  await page.getByLabel("영상 파일").setInputFiles({ name: "invalid.txt", mimeType: "text/plain", buffer: Buffer.from("not a video") });
  await expect(page.getByRole("alert")).toContainText("MOV 또는 MP4");
  await expect(page.getByRole("button", { name: "파일 등록" })).toBeDisabled();

  await page.getByLabel("영상 파일").setInputFiles(videoPath);
  const uploadResponse = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/sources`) && response.request().method() === "POST", { timeout: 120_000 });
  await page.getByRole("button", { name: "파일 등록" }).click();
  const uploaded = await uploadResponse;
  expect(uploaded.status()).toBe(201);
  const source = await uploaded.json();
  console.log(`REAL_SOURCE_ID=${source.source_video_id}`);
  await expect(page.getByText(/서버 등록 완료/)).toBeVisible();
  await expect(page.getByText(source.source_video_id, { exact: true })).toBeVisible();

  const processResponse = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/process`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "영상 처리 시작" }).click();
  const accepted = await processResponse;
  expect(accepted.status()).toBe(202);
  expect((await accepted.json()).accepted).toBe(true);
  const duplicate = await request.post(`http://127.0.0.1:8000/projects/${id}/process`);
  console.log(`DUPLICATE_PROCESS_STATUS=${duplicate.status()}`);
  expect(duplicate.status()).toBe(409);

  await expect.poll(async () => {
    const response = await request.get(`http://127.0.0.1:8000/projects/${id}/processing`);
    const data = await response.json();
    return data.project_status as string;
  }, { timeout: 180_000, intervals: [2000] }).toMatch(/^(COMPLETED|COMPLETED_WITH_WARNINGS|FAILED)$/);
  const finalResponse = await request.get(`http://127.0.0.1:8000/projects/${id}/processing`);
  const final = await finalResponse.json();
  console.log(`FINAL_STATUS=${final.project_status};COMPLETED=${final.completed_count};FAILED=${final.failed_count};BLOCKED=${final.blocked_count}`);
  await expect(page.getByText(final.project_status, { exact: true })).toBeVisible();
  await page.reload();
  await expect(page.getByText(final.project_status, { exact: true })).toBeVisible();
  await page.goto("/");
  await page.getByLabel("프로젝트 ID").fill(id);
  await page.getByRole("button", { name: "ID로 열기" }).click();
  await expect(page).toHaveURL(`/projects/${id}`);
  await expect(page.getByText(final.project_status, { exact: true })).toBeVisible();
  await page.screenshot({ path: "test-results/web01b-real-final.png", fullPage: true });
});

test("real backend rejection and upload cancellation in an isolated QA project", async ({ page, request }) => {
  const id = process.env.WEB01B_QA_PROJECT_ID;
  test.skip(!id, "Set WEB01B_QA_PROJECT_ID to an isolated QA project created by the real flow.");
  await page.goto(`/projects/${id}`);
  await expect(page.getByText("촬영 영상 등록")).toBeVisible();
  const before = await (await request.get(`http://127.0.0.1:8000/projects/${id}/processing`)).json();

  await page.getByLabel("영상 파일").setInputFiles({ name: "invalid.mp4", mimeType: "video/mp4", buffer: Buffer.from("invalid media") });
  const rejectedResponse = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/sources`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "파일 등록" }).click();
  expect((await rejectedResponse).status()).toBe(415);
  await expect(page.getByRole("alert")).toContainText("INVALID_SOURCE_MEDIA");

  const cdp = await page.context().newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 100, downloadThroughput: 2_000_000, uploadThroughput: 100_000 });
  await page.getByLabel("영상 파일").setInputFiles(videoPath);
  await page.getByRole("button", { name: "파일 등록" }).click();
  await expect(page.getByRole("button", { name: "업로드 취소" })).toBeVisible();
  await page.getByRole("button", { name: "업로드 취소" }).click();
  await expect(page.getByRole("alert")).toContainText("업로드를 취소했습니다");
  await cdp.send("Network.emulateNetworkConditions", { offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
  await page.getByRole("button", { name: "상태 다시 조회" }).click();
  const after = await (await request.get(`http://127.0.0.1:8000/projects/${id}/processing`)).json();
  console.log(`CANCEL_SOURCE_COUNT_BEFORE=${before.total_sources};AFTER=${after.total_sources}`);
  expect(after.total_sources).toBe(before.total_sources);
});

test("backend disconnection is shown without a success state", async ({ page }) => {
  test.skip(process.env.WEB01B_BACKEND_DOWN !== "1", "Run only after stopping the dedicated QA backend.");
  await page.goto("/");
  await page.getByLabel("프로젝트 이름").fill("offline check");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  await expect(page.getByRole("alert")).toContainText("서버에 연결할 수 없습니다");
  await expect(page).toHaveURL("/");
});
