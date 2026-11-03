import { expect, test } from "@playwright/test";

const id = process.env.WEB02_QA_PROJECT_ID;

test("real scene analysis, candidates and diagnostics through Chrome", async ({ page, request }) => {
  test.skip(!id, "Set WEB02_QA_PROJECT_ID to an isolated project with completed source processing.");
  const api = `http://127.0.0.1:8000/projects/${id}`;
  const sourceBefore = await (await request.get(`${api}/processing`)).json();
  expect(sourceBefore.completed_count).toBeGreaterThan(0);
  const candidatesBefore = await (await request.get(`${api}/scene-candidates`)).json();
  console.log(`SCENE_CANDIDATES_BEFORE=${candidatesBefore.candidates.length}`);

  await page.goto(`/projects/${id}`);
  await expect(page.getByText("장면 분석", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "장면 분석 시작" })).toBeEnabled();
  const responsePromise = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/scene-process`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "장면 분석 시작" }).click();
  const response = await responsePromise;
  expect(response.status()).toBe(202);
  expect((await response.json()).accepted).toBe(true);
  await expect.poll(async () => (await (await request.get(`${api}/scene-processing`)).json()).run_status as string, { timeout: 180_000, intervals: [2000] }).toMatch(/^(COMPLETED|COMPLETED_WITH_WARNINGS|FAILED)$/);

  const final = await (await request.get(`${api}/scene-processing`)).json();
  const candidates = await (await request.get(`${api}/scene-candidates`)).json();
  const diagnostics = await (await request.get(`${api}/scene-diagnostics`)).json();
  console.log(`SCENE_STATUS=${final.run_status};PROCESSED=${final.processed_count};COMPLETED=${final.completed_count};ABSTAINED=${final.abstained_count};FAILED=${final.failed_count};CANDIDATES=${candidates.candidates.length};DIAGNOSTICS=${diagnostics.sources.length}`);
  expect(final.run_status).not.toBe("FAILED");
  expect(final.processed_count).toBeGreaterThan(0);
  expect(diagnostics.sources.length).toBeGreaterThan(0);
  await expect(page.getByText(final.run_status === "COMPLETED" ? "분석 실행 완료" : "분석 완료 · 일부 주의 필요")).toBeVisible();
  if (candidates.candidates.length > 0) {
    for (const candidate of candidates.candidates) await expect(page.getByText(`후보 ${candidate.candidate_id}`)).toBeVisible();
  } else {
    await expect(page.getByText("이번 조회에서 장면 후보가 없습니다. 진단을 확인해 주세요.")).toBeVisible();
  }
  await page.getByText("원본 진단값 보기").first().click();
  await expect(page.getByText(/"evidence_counts"/).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText(final.run_status === "COMPLETED" ? "분석 실행 완료" : "분석 완료 · 일부 주의 필요")).toBeVisible();
  await expect(page.getByRole("list", { name: "장면 후보 목록" }).locator("li")).toHaveCount(candidates.candidates.length);
});

test("persisted candidates remain visible after the dedicated API process restarts", async ({ page, request }) => {
  test.skip(!id || process.env.WEB02_AFTER_RESTART !== "1", "Run read-only after restarting the dedicated QA API process.");
  const api = `http://127.0.0.1:8000/projects/${id}`;
  const run = await (await request.get(`${api}/scene-processing`)).json();
  expect(run.run_status).toBe("NOT_STARTED");
  const candidates = await (await request.get(`${api}/scene-candidates`)).json();
  expect(candidates.candidates.length).toBeGreaterThan(0);
  await page.goto(`/projects/${id}`);
  await expect(page.getByText("현재 서버에서 실행 기록 없음")).toBeVisible();
  await expect(page.getByRole("list", { name: "장면 후보 목록" }).locator("li")).toHaveCount(candidates.candidates.length);
  await expect(page.getByText(/이 상태는 현재 서버 프로세스의 실행 기록입니다/)).toBeVisible();
  console.log(`PERSISTED_AFTER_RESTART=${candidates.candidates.length}`);
});
