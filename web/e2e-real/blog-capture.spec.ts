import { mkdirSync } from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { expect, test, type Page } from "@playwright/test";
import { prepareVideoFrame } from "./capture-video-frame";

// Blog screenshots. Real UI part is READ-ONLY: any non-GET /api request fails the test (no LLM/VLM/render/save).
// BLOG_OUT = output root (temporary/blog-cutory), BLOG_PAGES = folder of local capture pages, BLOG_PROJECT_ID = Pexels demo project.
const out = process.env.BLOG_OUT ?? "";
const pages = process.env.BLOG_PAGES ?? "";
const id = process.env.BLOG_PROJECT_ID ?? "";
const dir = (sub: string) => { const d = path.join(out, sub); mkdirSync(d, { recursive: true }); return d; };

function readOnly(page: Page) {
  const writes: string[] = [];
  page.on("request", (r) => { if (r.url().includes("/api/") && r.method() !== "GET") writes.push(`${r.method()} ${r.url()}`); });
  return writes;
}

test.describe("real Cutory UI (read-only)", () => {
  test.use({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 });
  test.skip(!out || !id, "BLOG_OUT and BLOG_PROJECT_ID required");

  test("ep1 project list (other projects masked)", async ({ page }) => {
    const writes = readOnly(page);
    await page.goto("/");
    const list = page.getByRole("region", { name: "기존 프로젝트 목록" });
    const cards = list.locator("a[href^='/projects/']");
    await expect(cards.first()).toBeVisible({ timeout: 30_000 });
    const others = cards.filter({ hasNot: page.locator(`text=${id}`) });
    await list.screenshot({ path: path.join(dir("actual-ui"), "ep1-project-list-demo-only-others-masked.png"),
      mask: [others], maskColor: "#1e293b" });
    expect(writes).toEqual([]);
  });

  test("ep2 ep3 ep6 project page sections", async ({ page }) => {
    test.setTimeout(120_000);
    const writes = readOnly(page);
    await page.goto(`/projects/${id}`);
    await expect(page.getByText(/추천 장면 \d+개/)).toBeVisible({ timeout: 30_000 });
    const ui = dir("actual-ui");

    const diag = page.locator("ul[aria-label='Evidence 진단 목록']");
    await expect(diag.locator("li").first()).toBeVisible({ timeout: 30_000 });
    // Grid rows stretch this card to the tall candidate column; let it take its own height (content unchanged).
    await page.addStyleTag({ content: "#scene-analysis [data-slot=card]{align-self:start}" });
    const diagCard = page.locator("[data-slot=card]").filter({ has: page.getByRole("heading", { name: "소스별 Evidence 진단" }) });
    await diagCard.screenshot({ path: path.join(ui, "ep2-evidence-diagnostics-panel.png") });
    await diag.locator("summary").first().click(); // client-side <details> toggle only
    await diagCard.screenshot({ path: path.join(ui, "ep2-evidence-diagnostics-panel-expanded.png") });

    const firstTwo = page.locator("ul[aria-label='장면 후보 목록'] > li");
    await firstTwo.nth(2).screenshot({ path: path.join(ui, "ep2-scene-candidate-card-cake.png") });

    const order = page.locator("ol[aria-label='선택한 장면 순서']").locator("..");
    await order.scrollIntoViewIfNeeded();
    await order.screenshot({ path: path.join(ui, "ep3-saved-scene-order-two-cakes.png") });

    const render = page.locator("#edit-render > div").nth(1);
    await expect(render.getByRole("button", { name: "자막(SRT) 다운로드" })).toBeEnabled({ timeout: 30_000 });
    await render.getByRole("button", { name: "한국어 하드 자막 영상" }).click();
    await prepareVideoFrame(render.locator('video[aria-label="한국어 하드 자막 최종 영상 재생"]'));
    await render.screenshot({ path: path.join(ui, "ep6-render-complete-hardsub-frame-three-downloads.png") });
    const buttons = render.getByRole("button", { name: "자막(SRT) 다운로드" }).locator("xpath=ancestor::div[1]/..");
    await buttons.screenshot({ path: path.join(ui, "ep6-download-buttons-mp4-hardsub-srt.png") });
    expect(writes).toEqual([]);
  });
});

test.describe("local capture pages (artifact figures, real code, real terminal output)", () => {
  test.use({ deviceScaleFactor: 2 });
  test.skip(!out || !pages, "BLOG_OUT and BLOG_PAGES required");

  test("artifact tabs", async ({ page }) => {
    await page.setViewportSize({ width: 980, height: 900 });
    await page.emulateMedia({ colorScheme: "light" });
    const views: Array<[string, string]> = [["architecture", "ep1"], ["pipeline", "ep2"], ["hybrid", "ep3"],
      ["food-fix", "ep4"], ["render", "ep5"], ["integrity", "ep6"], ["ops", "ep7"]];
    const art = dir("architecture-artifacts");
    for (const [view, ep] of views) {
      await page.goto(`${pathToFileURL(path.join(pages, "artifact.html")).href}#${view}`);
      await page.evaluate(() => document.fonts.ready);
      const section = page.locator(`#v-${view}`);
      await expect(section).toBeVisible();
      await expect(section.getByText("설명용 재구성").first()).toBeVisible();
      await section.screenshot({ path: path.join(art, `${ep}-artifact-${view}-with-capture-guide.png`) });
      const style = await page.addStyleTag({ content: ".guide{display:none!important}" });
      await section.screenshot({ path: path.join(art, `${ep}-artifact-${view}-figure-only.png`) });
      await style.evaluate((node) => node.remove());
    }
  });

  test("code and terminal pages", async ({ page }) => {
    await page.setViewportSize({ width: 1180, height: 900 });
    const code = dir("code-and-tests");
    for (const name of ["code-ep4-guard-visual-request", "code-ep4-test-food-gate", "term-ep4-test-llm-interpreter",
      "term-ep6-test-srt-download", "term-ep7-test-backend-all", "term-ep7-test-vitest", "term-ep7-run8000-checkonly",
      "term-ep7-server-handover-log"]) {
      await page.goto(pathToFileURL(path.join(pages, `${name}.html`)).href);
      await page.evaluate(() => document.fonts.ready);
      const ep = name.match(/ep\d/)![0];
      await page.locator(".w").screenshot({ path: path.join(code, `${ep}-${name.replace(`-${ep}`, "")}.png`) });
    }
  });
});
