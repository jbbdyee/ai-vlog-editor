import { expect, test } from "@playwright/test";

const id = "11111111-1111-4111-8111-111111111111";
const sourceId = "22222222-2222-4222-8222-222222222222";
const project = { project_id: id, name: "주말 기록", status: "CREATED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 1, progress_ratio: 0 } };
const source = { source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "REGISTERED", stages: [] };
const processing = { project_id: id, project_status: "CREATED", total_sources: 1, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 1, progress_ratio: 0, sources: [source] };

test("create, upload, process and restore the server status after reload", async ({ page }) => {
  let registered = false;
  let active = false;
  let reads = 0;
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    const method = route.request().method();
    if (path === "/api/projects" && method === "POST") return route.fulfill({ status: 201, json: project });
    if (path.endsWith("/sources") && method === "POST") { registered = true; return route.fulfill({ status: 201, json: { project_id: id, source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "REGISTERED", duplicate_fingerprint_in_project: false } }); }
    if (path.endsWith("/process") && method === "POST") { active = true; return route.fulfill({ status: 202, json: { project_id: id, accepted: true, status_url: `/projects/${id}/processing` } }); }
    if (path.endsWith("/scene-processing")) return route.fulfill({ json: { project_id: id, run_status: "NOT_STARTED", total_sources: 1, processed_count: 0, completed_count: 0, abstained_count: 0, failed_count: 0, blocked_count: 0, skipped_count: 0, safe_error_code: null, sources: [] } });
    if (path.endsWith("/scene-candidates")) return route.fulfill({ json: { project_id: id, candidates: [] } });
    if (path.endsWith("/scene-diagnostics")) return route.fulfill({ json: { project_id: id, sources: [] } });
    if (path.endsWith("/processing")) {
      if (active) reads++;
      return route.fulfill({ json: { ...processing, total_sources: registered ? 1 : 0, sources: registered ? [source] : [], project_status: active ? (reads < 2 ? "PROCESSING" : "COMPLETED") : "CREATED", completed_count: active && reads >= 2 ? 1 : 0 } });
    }
    return route.fulfill({ json: project });
  });
  await page.goto("/");
  await page.getByLabel("프로젝트 이름").fill("주말 기록");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  await expect(page).toHaveURL(`/projects/${id}`);
  await expect(page.getByText("촬영 영상 등록")).toBeVisible();
  await page.getByLabel("영상 파일").setInputFiles({ name: "clip.MOV", mimeType: "video/quicktime", buffer: Buffer.from("synthetic") });
  await page.getByRole("button", { name: "파일 등록" }).click();
  await expect(page.getByText("clip.MOV").first()).toBeVisible();
  await expect(page.getByText(/서버 등록 완료/)).toBeVisible();
  await page.getByRole("button", { name: "영상 처리 시작" }).click();
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible({ timeout: 8000 });
  await page.reload();
  await expect(page.getByText("COMPLETED", { exact: true })).toBeVisible();
});

test("invalid file and API errors are visible", async ({ page }) => {
  await page.route(/\/api\/projects(?:\/|$)/, async (route) => {
    if (route.request().method() === "POST") return route.fulfill({ status: 503, json: { detail: { code: "PROJECT_DATABASE_UNAVAILABLE" } } });
    return route.fulfill({ status: 404, json: { detail: { code: "PROJECT_NOT_FOUND" } } });
  });
  await page.goto("/");
  await page.getByLabel("프로젝트 이름").fill("실패 사례");
  await page.getByRole("button", { name: "프로젝트 만들기" }).click();
  await expect(page.getByRole("alert")).toContainText("PROJECT_DATABASE_UNAVAILABLE");
  await page.getByLabel("프로젝트 ID").fill(id);
  await page.getByRole("button", { name: "ID로 열기" }).click();
  await expect(page.getByRole("alert").last()).toContainText("PROJECT_NOT_FOUND");
});
