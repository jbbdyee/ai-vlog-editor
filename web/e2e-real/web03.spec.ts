import { createHash } from "node:crypto";
import { expect, test } from "@playwright/test";

const id = process.env.WEB03_QA_PROJECT_ID;

test("real edit plan, render and both downloads through Chrome and FastAPI", async ({ page, request }) => {
  test.skip(!id, "Set WEB03_QA_PROJECT_ID to an isolated project with processed real media and scene candidates.");
  const api = `http://127.0.0.1:8000/projects/${id}`;
  const candidates = await (await request.get(`${api}/scene-candidates`)).json();
  expect(candidates.candidates.length).toBeGreaterThanOrEqual(2);
  const beforePlan = await (await request.get(`${api}/scene-edit-plan`)).json();
  const beforeRender = await (await request.get(`${api}/rendering`)).json();
  test.skip((beforePlan.candidate_ids.length !== 0 || beforeRender.status !== "NOT_STARTED") && process.env.WEB03_ALLOW_RERENDER !== "1", "This QA project was already used; set WEB03_ALLOW_RERENDER only for an explicit isolated retry.");
  const selected = [...candidates.candidates].filter((item: { start_seconds: number }) => item.start_seconds >= 4.6 && item.start_seconds < 7).slice(0, 2);
  expect(selected).toHaveLength(2);

  await page.goto(`/projects/${id}`);
  if (process.env.WEB03_ALLOW_RERENDER === "1") {
    for (const candidateId of beforePlan.candidate_ids as string[]) {
      await page.getByRole("list", { name: "선택 가능한 장면" }).locator("li").filter({ hasText: candidateId }).getByRole("button", { name: "선택 해제" }).click();
    }
  }
  for (const candidate of selected) {
    await page.getByRole("list", { name: "선택 가능한 장면" }).locator("li").filter({ hasText: candidate.candidate_id }).getByRole("button", { name: "장면 선택" }).click();
  }
  await expect(page.getByText("저장되지 않은 변경사항이 있습니다.")).toBeVisible();
  const saveResponse = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/scene-edit-plan`) && response.request().method() === "PUT");
  await page.getByRole("button", { name: "편집 계획 저장" }).click();
  expect((await saveResponse).status()).toBe(200);
  await expect(page.getByText("저장된 편집 계획입니다.")).toBeVisible();
  const savedPlan = await (await request.get(`${api}/scene-edit-plan`)).json();
  expect(savedPlan.candidate_ids).toEqual(selected.map((item: { candidate_id: string }) => item.candidate_id));
  expect(savedPlan.invalid_candidate_ids).toEqual([]);
  await page.reload();
  await expect(page.getByRole("list", { name: "선택한 장면 순서" }).locator("li")).toHaveCount(2);

  const postResponse = page.waitForResponse((response) => response.url().endsWith(`/api/projects/${id}/render`) && response.request().method() === "POST");
  await page.getByRole("button", { name: "저장된 계획으로 렌더링" }).click();
  expect((await postResponse).status()).toBe(202);
  await expect(page.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled({ timeout: 1000 }).catch(() => { /* A short render can complete before this assertion. */ });
  await expect.poll(async () => (await (await request.get(`${api}/rendering`)).json()).status as string, { timeout: 180_000, intervals: [2000] }).toMatch(/^(COMPLETED|FAILED)$/);
  const final = await (await request.get(`${api}/rendering`)).json();
  console.log(`WEB03_RENDER_STATUS=${final.status};RENDER_ID=${final.render_id};SUBTITLE_STATUS=${final.hard_subtitle_status};SUBTITLE_ERROR=${final.hard_subtitle_error_code}`);
  expect(final.status).toBe("COMPLETED");
  expect(final.download_available).toBe(true);
  await expect(page.getByText("렌더 완료", { exact: true })).toBeVisible({ timeout: 10_000 });
  const plain = await request.get(`http://127.0.0.1:8000${final.output.download_url}`);
  expect(plain.status()).toBe(200);
  expect(plain.headers()["content-type"]).toContain("video/mp4");
  const plainHash = createHash("sha256").update(await plain.body()).digest("hex");
  const plainDownload = page.waitForEvent("download");
  await page.getByRole("button", { name: "자막 없는 MP4 다운로드" }).click();
  const plainFile = await plainDownload;
  expect(plainFile.suggestedFilename()).toBe("final.mp4");
  const plainRead = await plainFile.createReadStream();
  const plainChunks: Buffer[] = [];
  for await (const chunk of plainRead) plainChunks.push(Buffer.from(chunk));
  expect(createHash("sha256").update(Buffer.concat(plainChunks)).digest("hex")).toBe(plainHash);

  if (final.hard_subtitle_download_available) {
    const subtitled = await request.get(`http://127.0.0.1:8000${final.hard_subtitle_download_url}`);
    expect(subtitled.status()).toBe(200);
    expect(subtitled.headers()["content-type"]).toContain("video/mp4");
    const subtitleHash = createHash("sha256").update(await subtitled.body()).digest("hex");
    const subtitleDownload = page.waitForEvent("download");
    await page.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" }).click();
    const subtitleFile = await subtitleDownload;
    expect(subtitleFile.suggestedFilename()).toBe("final-subtitled.mp4");
    const subtitleRead = await subtitleFile.createReadStream();
    const subtitleChunks: Buffer[] = [];
    for await (const chunk of subtitleRead) subtitleChunks.push(Buffer.from(chunk));
    expect(createHash("sha256").update(Buffer.concat(subtitleChunks)).digest("hex")).toBe(subtitleHash);
  } else {
    await expect(page.getByRole("button", { name: "한국어 하드 자막 MP4 다운로드" })).toBeDisabled();
  }
  console.log(`WEB03_PLAIN_SHA256=${plainHash}`);
});
