import { expect, test } from "@playwright/test";

const projectId = process.env.WEB08B_QA_PROJECT_ID;
test.skip(!projectId, "Set the restored isolated QA project ID.");

test("real isolated render is persisted before the API restart", async ({ page, request }) => {
  test.setTimeout(600_000);
  await page.goto(`/projects/${projectId}`);
  const existingId = process.env.WEB08B_QA_RENDER_ID;
  if (!existingId) {
    const render = page.getByRole("button", { name: "저장된 계획으로 렌더링" });
    await expect(render).toBeEnabled();
    await render.click();
    await expect(page.getByText(/렌더 요청이 접수됐습니다/)).toBeVisible();
  }
  let status: Record<string, unknown> = {};
  await expect.poll(async () => {
    const response = await request.get(`http://127.0.0.1:8001/projects/${projectId}/rendering`);
    status = await response.json();
    return status.status;
  }, { timeout: 480_000, intervals: [1000, 2000, 5000] }).toBe("COMPLETED");
  expect(status.download_available).toBe(true);
  expect(status.hard_subtitle_download_available).toBe(true);
  const id = status.render_id;
  expect(typeof id).toBe("string");
  if (existingId) expect(String(id)).toBe(existingId);
  else console.log(`WEB08B_QA_RENDER_ID=${id}`);
  await page.getByRole("region", { name: "편집 및 렌더링" }).getByRole("button", { name: "상태 다시 조회" }).click();
  await expect(page.getByLabel("최종 영상 미리보기")).toBeVisible();
});
