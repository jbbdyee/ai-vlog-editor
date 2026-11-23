import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
    await userEvent.click(screen.getByRole("button", { name: "더 보기" }));
    expect(screen.getByText(/Claude 1번/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "닫기" }));
    
    await userEvent.click(screen.getByRole("button", { name: "되돌리기 (1)" }));
    expect(await screen.findByRole("button", { name: "컷 2, 4.0초" })).toBeInTheDocument();
  });

  it("moves on to the next cut when a cut runs to the end of its source file", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "컷 1, 6.0초" }));
    const player = screen.getByLabelText("편집안 재생") as HTMLVideoElement;
    fireEvent.loadedMetadata(player);
    fireEvent.ended(player);
    expect(await screen.findByText(/^컷 2 · 4\.0초/)).toBeInTheDocument();
    expect(player.currentTime).toBe(10);
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
    await userEvent.click(screen.getByRole("button", { name: "더 보기" }));
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

    await userEvent.click(await screen.findByRole("button", { name: "더 보기" }));
    expect(await screen.findByText(candidate.text)).toBeInTheDocument();
    expect(screen.getByText(`근거: ${candidate.why}`)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "규칙으로" }));
    expect(await screen.findByRole("button", { name: `규칙 지우기: ${candidate.text}` })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "아니야" })).not.toBeInTheDocument();
    expect(answered).toEqual([{ key: "other_voice:keep", accept: true }]);
  });

  it("TODO 32: remakes the plan from a fresh recommendation, and undo is offered", async () => {
    const sent: unknown[] = [];
    const directionBodies: unknown[] = [];
    const scene = (index: number, start: number) => ({ candidate_id: ids[index], source_video_id: source, source_filename: "0789.MP4",
      start_seconds: start, end_seconds: start + 3, clip_start_seconds: start, clip_end_seconds: start + 3 });
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/story-direction")) directionBodies.push(init?.body ? JSON.parse(String(init.body)) : null);
      if (url.endsWith("/story-direction")) return Promise.resolve(response({ project_id: project, title: "학원 하루", summary: "", engine: "rule", notes: [],
        chapters: [{ title: "오전", description: "", reason: "", total_seconds: 6, scenes: [scene(0, 0), scene(2, 20)] }],
        target_minutes: 1, recommended_minutes: 1, length_reason: "", length_options: [1], total_seconds: 6, max_seconds: 60, footage_seconds: 60 }));
      if (url.endsWith("/chat-edit/remake")) {
        sent.push(JSON.parse(String(init?.body)));
        return Promise.resolve(response(view(4, [{ id: "r1", role: "assistant", text: "추천으로 다시 만들었어: 컷 2개, 00:06.", at_seconds: null, done: [], skipped: [], engine: "rule", error: null, changed: [], undo: false }], 1)));
      }
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);
    await userEvent.click(await screen.findByRole("button", { name: "더 보기" }));
    await userEvent.click(await screen.findByRole("button", { name: "8분" }));
    await userEvent.click(await screen.findByRole("button", { name: "이 길이로 다시 만들기" }));
    expect(await screen.findByText(/추천으로 다시 만들었어/)).toBeInTheDocument();
    expect(directionBodies[0]).toEqual({ target_minutes: 8 });  // TODO 32-3: the chosen length goes to the server
    expect(sent[0]).toEqual({ clips: [{ candidate_id: ids[0], start_seconds: 0, end_seconds: 3 }, { candidate_id: ids[2], start_seconds: 20, end_seconds: 23 }] });
    expect(screen.getByRole("button", { name: "되돌리기 (1)" })).toBeEnabled();
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

  it("TODO 35: plays the light 720p copy once it is made and says how many are ready", async () => {
    const asked: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/previews")) {
        asked.push(JSON.parse(String(init?.body)));
        return Promise.resolve(response({ total: 2, ready: [source], making: null, failed: ["44444444-4444-4444-8444-444444444444"] }));
      }
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "더 보기" }));
    expect(await screen.findByText("휴대폰용 미리보기 준비됨 1/2 · 못 만든 영상 1개")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("편집안 재생").getAttribute("src")).toBe(`/api/projects/${project}/sources/${source}/preview`));
    expect(asked).toEqual([{ first: [source] }]);
  });
  it("TODO 41-1: shows what Claude finishing would send and its estimated price, without calling it", async () => {
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (init?.method === "POST") posts.push(url);
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/finishing")) return Promise.resolve(response({ model: "claude-sonnet-5-5", cuts: 76, pictures: 228, chunks: 3,
        input_tokens: 60000, output_tokens: 7000, output_tokens_high: 18400, usd_low: 0.19, usd_high: 0.3,
        rules: ["한 컷은 5.5초 안팎"], has_brief: true, reference: ["자막 한 번에 5.5자 안팎"], cuts_with_effects: 2 }));
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "더 보기" }));
    expect(await screen.findByLabelText("예상 금액")).toHaveTextContent("예상 약 280~440원");
    const sends = screen.getByLabelText("함께 보내는 것");
    expect(sends).toHaveTextContent("컷 76개 · 컷마다 사진 3장(모두 228장)");
    expect(sends).toHaveTextContent("내 규칙 1개: 한 컷은 5.5초 안팎");
    expect(sends).toHaveTextContent("좋아하는 영상 숫자: 자막 한 번에 5.5자 안팎");
    expect(sends).toHaveTextContent("이미 효과를 넣은 컷 2개는 그대로");
    expect(posts.filter((url) => url.includes("finishing"))).toEqual([]);
  });

  it("TODO 41-2: calls Claude only after the price is confirmed and lists the suggestions", async () => {
    const posts: string[] = [];
    const estimate = { model: "claude-sonnet-5-5", cuts: 3, pictures: 9, chunks: 1, input_tokens: 3000, output_tokens: 500,
      output_tokens_high: 900, usd_low: 0.01, usd_high: 0.02, rules: [], has_brief: false, reference: [], cuts_with_effects: 0 };
    vi.stubGlobal("fetch", vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      if (url.endsWith("/finishing") && init?.method === "POST") {
        posts.push(String(init.body));
        return Promise.resolve(response({ ...estimate, made_at: "2026-11-23T13:00:00Z", spent_usd: 0.012, spent_model: "claude-sonnet-5-5",
          titles: ["콧구멍 벌렁 주의"], suggestions: [{ number: 2, candidate_id: ids[1], zoom: "push", why: "놀라는 얼굴",
            texts: [{ kind: "react", text: "벌렁", at: 1.2 }, { kind: "narr", text: "근데 갑자기", at: 2 }], sounds: [{ name: "띠용", at: 1.2 }] }] }));
      }
      if (url.endsWith("/finishing")) return Promise.resolve(response(estimate));
      return Promise.resolve(response(view(4)));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    await userEvent.click(await screen.findByRole("button", { name: "더 보기" }));
    await userEvent.click(await screen.findByRole("button", { name: "손질 시작" }));
    expect(posts).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "부르기" }));
    const list = await screen.findByLabelText("Claude 제안");
    expect(posts).toEqual([JSON.stringify({ run: true })]);
    expect(list).toHaveTextContent("제안 1컷 · 든 돈 약 20원($0.012) · 아직 편집에 안 넣었어요");
    expect(list).toHaveTextContent("2번 컷 · 놀라는 얼굴");
    expect(list).toHaveTextContent("🔍 천천히 줌 💬 '벌렁' 1.2초 💬 (근데 갑자기) 2.0초 🔊 띠용 1.2초");
    expect(screen.getByLabelText("훅 제목 후보")).toHaveTextContent("콧구멍 벌렁 주의");
    expect(screen.getByRole("button", { name: "다시 손질 받기" })).toBeInTheDocument();
  });

  it("TODO 37: keeps only the latest exchange on screen and shows a dot on ⋯ for a rule candidate", async () => {
    const chat = [
      { id: "u1", role: "user", text: "[00:01] 1번 빼", at_seconds: 1, done: [], skipped: [], engine: null, error: null, changed: [], undo: false },
      { id: "a1", role: "assistant", text: "옛날 답", at_seconds: null, done: [], skipped: [], engine: "rule", error: null, changed: [], undo: false },
      { id: "u2", role: "user", text: "[00:06] 이 장면 짧게", at_seconds: 6, done: [], skipped: [], engine: null, error: null, changed: [], undo: false },
      { id: "a2", role: "assistant", text: "새 답", at_seconds: null, done: [], skipped: [], engine: "rule", error: null, changed: [], undo: false },
    ];
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED" }));
      return Promise.resolve(response({ ...view(4, chat, 2), rule_candidates: [{ key: "k", text: "규칙 하나", why: "이유" }] }));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}/chat-edit`]}><Routes>
      <Route path="projects/:projectId/chat-edit" element={<ChatEditPage />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText("새 답")).toBeInTheDocument();
    expect(screen.queryByText("옛날 답")).not.toBeInTheDocument();
    expect(screen.getByLabelText("새 규칙 후보")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "되돌리기 (2)" })).toBeEnabled();
    await userEvent.click(screen.getByRole("button", { name: "지난 대화 2개 보기" }));
    expect(screen.getByText("옛날 답")).toBeInTheDocument();
  });
});
