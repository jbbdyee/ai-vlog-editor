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
