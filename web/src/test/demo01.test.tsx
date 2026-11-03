import { beforeEach, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";
import { sceneReasons } from "@/api/scenes";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const dance = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const talk = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const candidates = [
  { candidate_id: dance, source_video_id: source, start_seconds: 10, end_seconds: 14, transcript_text: "같이 춤 춰요",
    evidence: [{ modality: "VISUAL", evidence_type: "VISUAL_ACTIVITY", count: 1 }, { modality: "TRANSCRIPT", evidence_type: "TRANSCRIPT_STRUCTURE", count: 1 }] },
  { candidate_id: talk, source_video_id: source, start_seconds: 20, end_seconds: 23, transcript_text: null,
    evidence: [{ modality: "AUDIO", evidence_type: "AUDIO_ACTIVITY", count: 1 }, { modality: "QUALITY", evidence_type: "LONG_SILENCE", count: 1 }] },
];
let saved: string[] = [];
let suggestionStatus = 200;
const idle = { project_id: project, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null };

beforeEach(() => {
  saved = []; suggestionStatus = 200;
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/scene-candidates")) return json({ project_id: project, candidates });
    if (url.endsWith("/scene-edit-plan") && init?.method === "PUT") { saved = JSON.parse(String(init.body)).candidate_ids; return json({ project_id: project, candidate_ids: saved, invalid_candidate_ids: [] }); }
    if (url.endsWith("/scene-edit-plan")) return json({ project_id: project, candidate_ids: saved, invalid_candidate_ids: [] });
    if (url.endsWith("/edit-suggestions")) {
      if (suggestionStatus === 404) return json({ detail: "Not Found" }, 404);
      expect(JSON.parse(String(init?.body))).toEqual({ request: "춤 장면만 10초 이내" });
      return json({ project_id: project, candidate_ids: [dance], scenes: [{ candidate_id: dance, reasons: ["'춤' 언급", "움직임 근거"] }], total_seconds: 4, target_seconds: 10, max_count: null, keywords: ["춤"], excluded: [], categories: ["motion"], order: "chronological", notes: ["전사에서 찾지 못한 단어: 고양이"], engine: "llm:ollama/gemma3:4b", interpretation: "춤 장면만 10초 이내", mood: "lively", fallback_reason: null });
    }
    if (url.endsWith("/rendering")) return json(idle);
    if (url.includes("/renders")) return json({ project_id: project, items: [], next_cursor: null });
    throw new Error(`unexpected ${url}`);
  }));
});

function mount() {
  render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><EditRender projectId={project} /></QueryClientProvider>);
}

it("maps evidence to Korean reasons and cautions", () => {
  expect(sceneReasons(candidates[0])).toEqual({ reasons: ["말하는 구간", "화면 움직임"], cautions: [] });
  expect(sceneReasons(candidates[1])).toEqual({ reasons: ["소리가 살아나는 구간"], cautions: ["상대적 오디오 활동 감소 · 실제 무음 미확인"] });
  expect(sceneReasons({ evidence: [
    { modality: "QUALITY", evidence_type: "LONG_SILENCE", count: 1 },
    { modality: "AUDIO", evidence_type: "CONFIRMED_SILENCE", count: 1 },
  ] })).toEqual({ reasons: [], cautions: ["긴 무음 포함"] });
});

it("shows reasons and speech, applies a natural-language suggestion and saves it through the plan", async () => {
  mount();
  await screen.findByText("“같이 춤 춰요”");
  const list = screen.getByRole("list", { name: "선택 가능한 장면" });
  expect(within(list).getByText("“같이 춤 춰요”")).toBeInTheDocument();
  expect(within(list).getByText("화면 움직임")).toBeInTheDocument();
  expect(within(list).getByText("상대적 오디오 활동 감소 · 실제 무음 미확인")).toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("원하는 편집을 말로 요청하기"), { target: { value: "춤 장면만 10초 이내" } });
  fireEvent.click(screen.getByRole("button", { name: "장면 제안 받기" }));
  expect(await screen.findByText(/'춤' 언급 · 움직임 근거/)).toBeInTheDocument();
  expect(screen.getByText("전사에서 찾지 못한 단어: 고양이")).toBeInTheDocument();
  expect(screen.getByText("AI 해석 · ollama/gemma3:4b")).toBeInTheDocument();
  expect(screen.getByText("해석: 춤 장면만 10초 이내")).toBeInTheDocument();
  expect(screen.getByText("분위기 활기참")).toBeInTheDocument();
  expect(saved).toEqual([]); // suggesting never saves
  fireEvent.click(screen.getByRole("button", { name: "제안을 선택 목록에 적용" }));
  expect(screen.getByText("저장되지 않은 변경사항이 있습니다.")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "편집 계획 저장" }));
  await waitFor(() => expect(saved).toEqual([dance]));
});

it("explains when the running server predates edit suggestions", async () => {
  suggestionStatus = 404;
  mount();
  await screen.findByLabelText("원하는 편집을 말로 요청하기");
  fireEvent.change(screen.getByLabelText("원하는 편집을 말로 요청하기"), { target: { value: "아무거나" } });
  fireEvent.click(screen.getByRole("button", { name: "장면 제안 받기" }));
  expect(await screen.findByText(/서버 업데이트 후 사용할 수 있습니다/)).toBeInTheDocument();
});
