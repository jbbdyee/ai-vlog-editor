import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ChatEditPage } from "@/features/chat-edit/chat-edit-page";

const project = "11111111-1111-4111-8111-111111111111";
const source = "22222222-2222-4222-8222-222222222222";
const ids = ["33333333-3333-4333-8333-333333333331", "33333333-3333-4333-8333-333333333332", "33333333-3333-4333-8333-333333333333"];
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function view(secondLength: number, messages: unknown[] = [], undoCount = 0) {
  const lengths = [6, secondLength, 5];
  let at = 0;
  const cuts = lengths.map((length, index) => {
    const cut = { number: index + 1, candidate_id: ids[index], source_video_id: source, source_filename: "0789.MP4", start_seconds: 10 * index,
      end_seconds: 10 * index + length, timeline_start: at, length, speech: `[나] 대사 ${index + 1}`, caption: "교실" };
    at += length;
    return cut;
  });
  return { project_id: project, cuts, total_seconds: at, unused: [], messages, undo_count: undoCount,
    brains: [{ key: "claude", label: "Claude · claude-haiku-5-5" }, { key: "ollama", label: "로컬 AI · gemma3:4b" }],
    default_brain: "claude", usage: [{ key: "claude", calls: 1, input_tokens: 3000, output_tokens: 200, usd: 0.0004 }], dropped: 0, last: null };
}

beforeEach(() => {
  vi.restoreAllMocks(); vi.unstubAllGlobals();
  Object.defineProperty(HTMLMediaElement.prototype, "load", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLMediaElement.prototype, "pause", { configurable: true, value: vi.fn() });
  Object.defineProperty(HTMLMediaElement.prototype, "play", { configurable: true, value: vi.fn(() => Promise.resolve()) });
});

describe("TODO 26 chat editing screen", () => {
  it("stamps the paused time, shows the changed cut on the strip and undoes it", async () => {
    const sent: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/chat-edit/undo")) return Promise.resolve(response(view(4, [], 0)));
      if (url.endsWith("/chat-edit") && init?.method === "POST") {
        sent.push(JSON.parse(String(init.body)));
        return Promise.resolve(response(view(2.7, [
          { role: "user", text: "[00:06] 이 장면 짧게", at_seconds: 6, done: [], skipped: [], engine: null, error: null, changed: [], undo: false },
          { role: "assistant", text: "바로 고쳤어.", at_seconds: null, done: ["2번 컷 4.0초 → 2.7초"], skipped: [], engine: "rule", error: null, changed: [ids[1]], undo: false },
        ], 1)));
      }
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "컷 2, 4.0초" }));
    fireEvent.pause(screen.getByLabelText("편집안 재생"));
    expect(screen.getByText("[00:06]")).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("고칠 내용"), "이 장면 짧게");
    await userEvent.click(screen.getByRole("button", { name: "고치기" }));

    expect(await screen.findByText("✓ 2번 컷 4.0초 → 2.7초")).toBeInTheDocument();
    expect(sent).toEqual([{ message: "[00:06] 이 장면 짧게", at_seconds: 6, brain: "claude" }]);
    expect(screen.getByRole("button", { name: "컷 2, 2.7초, 방금 고침" })).toBeInTheDocument();
    expect(screen.getByText("규칙으로 바로")).toBeInTheDocument();
    expect(screen.getByText(/Claude 1번/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "되돌리기 (1)" }));
    expect(await screen.findByRole("button", { name: "컷 2, 4.0초" })).toBeInTheDocument();
  });

  it("TODO 27: picks a 다른 장면 picture and saves a sentence as a rule chip", async () => {
    const picked: unknown[] = [];
    let rules: { id: string; text: string }[] = [];
    const offer = [
      { id: "u1", role: "user", text: "[00:06] 다른 장면으로", at_seconds: 6, done: [], skipped: [], engine: null, error: null, changed: [], undo: false },
      { id: "a1", role: "assistant", text: "2번 컷(4.0초) 대신 넣을 장면이야. 눌러서 골라 줘.", at_seconds: null, done: [], skipped: [], engine: "rule", error: null, changed: [], undo: false,
        for_cut: 2, picked: null, choices: [
          { candidate_id: ids[0], source_video_id: source, start_seconds: 50, end_seconds: 53, kind: "unused", label: "안 쓴 장면 1 · 0801" },
          { candidate_id: ids[1], source_video_id: source, start_seconds: 30, end_seconds: 34, kind: "same", label: "같은 영상 30–34초" }] },
    ];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/projects/edit-rules") && init?.method === "POST") {
        rules = [{ id: "r1", text: JSON.parse(String(init.body)).text.replace(/^\[\d+:\d+\]\s*/, "") }];
        return Promise.resolve(response({ rules }));
      }
      if (url.endsWith("/projects/edit-rules")) return Promise.resolve(response({ rules }));
      if (url.endsWith("/chat-edit/pick")) {
        picked.push(JSON.parse(String(init?.body)));
        return Promise.resolve(response(view(4, [...offer.slice(0, 1), { ...offer[1], picked: 1 },
          { id: "a2", role: "assistant", text: "골라 준 장면으로 바꿨어.", at_seconds: null, done: ["2번 컷 4.0초 → 같은 영상 30–34초 (4.0초)로 바꿈"], skipped: [], engine: "rule", error: null, changed: [ids[1]], undo: false }], 1)));
      }
      return Promise.resolve(response(view(4, offer)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    const picture = await screen.findByRole("img", { name: "같은 영상 30–34초" });
    expect(picture.getAttribute("src")).toBe(`/api/projects/${project}/sources/${source}/thumb?at=32.000`);
    expect(screen.getByRole("button", { name: "그대로 두기" })).toBeInTheDocument();
    await userEvent.click(picture);
    expect(await screen.findByText("✓ 2번 컷 4.0초 → 같은 영상 30–34초 (4.0초)로 바꿈")).toBeInTheDocument();
    expect(picked).toEqual([{ message_id: "a1", choice: 1 }]);
    expect(screen.getByText("실제로 한 일")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "규칙으로 저장" }));
    expect(await screen.findByRole("button", { name: "규칙 지우기: 다른 장면으로" })).toBeInTheDocument();
    expect(screen.getByText("규칙으로 저장됨")).toBeInTheDocument();
  });

  it("TODO 28: shows a rule candidate from my choices and accepts it as a rule chip", async () => {
    const answered: unknown[] = [];
    let rules: { id: string; text: string }[] = [];
    const candidate = { key: "other_voice:keep", text: "다른 사람 목소리가 나오는 장면(친구 수다)은 살린다", why: "다른 사람 목소리가 나오는 장면을 3번 살렸고(사진에서 고름 3), 뺀 건 0번" };
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/projects/edit-rules")) return Promise.resolve(response({ rules }));
      if (url.endsWith("/chat-edit/rule-candidates")) {
        answered.push(JSON.parse(String(init?.body)));
        rules = [{ id: "r1", text: candidate.text }];
        return Promise.resolve(response({ ...view(4), rule_candidates: [] }));
      }
      return Promise.resolve(response({ ...view(4), rule_candidates: [candidate] }));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText(candidate.text)).toBeInTheDocument();
    expect(screen.getByText(`근거: ${candidate.why}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "규칙으로" }));
    expect(await screen.findByRole("button", { name: `규칙 지우기: ${candidate.text}` })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "아니야" })).not.toBeInTheDocument();
    expect(answered).toEqual([{ key: "other_voice:keep", accept: true }]);
  });

  it("offers to start from the recommended story direction when there is no plan", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      return Promise.resolve(response({ ...view(4), cuts: [], total_seconds: 0 }));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);
    expect(await screen.findByRole("button", { name: "추천 편집 방향으로 첫 편집안 만들기" })).toBeInTheDocument();
  });
});
