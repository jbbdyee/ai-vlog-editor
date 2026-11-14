import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LongformCaptions } from "@/features/edit/longform-captions";

const project = "11111111-1111-4111-8111-111111111111";
const render_id = "fc200993ebd64bc8a6423286d03e45b9";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const base = { project_id: project, status: "IDLE", step: "", done: 0, total: 0, error_code: null, latest_render_id: render_id, video: null };
const video = { render_id, duration_seconds: 179.8, file_size_bytes: 40 * 1024 * 1024, line_count: 40, thoughts: ["벌써 다리 후들", "집에 가고 싶다"],
  thought_engine: "ollama/gemma3:4b", matches_render: true, url: `/projects/${project}/captioned-video/file?v=1700000000` };

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function show(answer: (init?: RequestInit) => Response) {
  const fetcher = vi.fn((_url: string, init?: RequestInit) => Promise.resolve(answer(init)));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><LongformCaptions projectId={project} renderKey={render_id} /></QueryClientProvider>);
  return fetcher;
}

describe("TODO 21 long-form spoken captions", () => {
  it("starts burning the captions on the last render", async () => {
    const fetcher = show((init) => init?.method === "POST"
      ? response({ ...base, status: "RUNNING", step: "속마음 한마디 쓰기", total: 2 }, 202) : response(base));
    await userEvent.click(await screen.findByRole("button", { name: "말한 내용 자막 입히기" }));
    expect(await screen.findByRole("status")).toHaveTextContent("속마음 한마디 쓰기");
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${project}/captioned-video`, { method: "POST" });
  });

  it("plays the finished video and lists the thoughts", async () => {
    show(() => response({ ...base, status: "COMPLETED", video }));
    expect(await screen.findByLabelText("자막 입힌 롱폼 영상")).toHaveAttribute("src", `/api${video.url}`);
    expect(screen.getByText(/자막 40줄 · 속마음 2개/)).toBeInTheDocument();
    expect(screen.getByText("속마음: 벌써 다리 후들 · 집에 가고 싶다")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "자막 다시 입히기" })).toBeEnabled();
  });

  it("stays hidden until there is a render", async () => {
    const fetcher = show(() => response({ ...base, latest_render_id: null }));
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(screen.queryByRole("region", { name: "말한 내용 자막" })).toBeNull();
  });
});
