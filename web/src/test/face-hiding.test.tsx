import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { FaceHiding, MyFaceCard } from "@/features/faces/face-hiding";

const project = "11111111-1111-4111-8111-111111111111";
const render_id = "fc200993ebd64bc8a6423286d03e45b9";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const base = { project_id: project, status: "IDLE", done: 0, total: 0, error_code: null, latest_render_id: render_id, photo_count: 4, model_available: true, video: null };
const video = { render_id, duration_seconds: 480, file_size_bytes: 200 * 1024 * 1024, frames: 14400, frames_hidden: 3600, faces_hidden: 5000,
  frames_with_me: 9000, photo_count: 4, matches_render: true, url: `/projects/${project}/face-video/file?v=1` };
const photo = (id: string) => ({ id, filename: `${id}.jpg`, url: `/projects/my-face/${id}/image` });

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function show(node: ReactNode, answer: (url: string, init?: RequestInit) => Response) {
  const fetcher = vi.fn((url: string, init?: RequestInit) => Promise.resolve(answer(url, init)));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
  return fetcher;
}

describe("TODO 25 my face card", () => {
  it("shows registered faces and uploads a new photo", async () => {
    let photos = [photo("a1")];
    const fetcher = show(<MyFaceCard />, (_url, init) => {
      if (init?.method === "POST") photos = [...photos, photo("b2")];
      return response({ photos, model_available: true, threshold: 0.36 });
    });
    expect(await screen.findByAltText("내 얼굴 a1.jpg")).toHaveAttribute("src", "/api/projects/my-face/a1/image");
    await userEvent.upload(screen.getByLabelText("내 얼굴 사진 고르기"), new File(["x"], "me.jpg", { type: "image/jpeg" }));
    expect(await screen.findByAltText("내 얼굴 b2.jpg")).toBeInTheDocument();
    expect(screen.getByText(/등록 2장/)).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith("/api/projects/my-face", expect.objectContaining({ method: "POST" }));
  });

  it("explains a photo without a face", async () => {
    show(<MyFaceCard />, (_url, init) => init?.method === "POST"
      ? response({ detail: { code: "FACE_NOT_FOUND", message: "이 사진에서 얼굴을 찾지 못했습니다." } }, 422)
      : response({ photos: [], model_available: true, threshold: 0.36 }));
    await userEvent.upload(await screen.findByLabelText("내 얼굴 사진 고르기"), new File(["x"], "cat.jpg", { type: "image/jpeg" }));
    expect(await screen.findByText(/cat\.jpg: /)).toBeInTheDocument();
  });
});

describe("TODO 25 hiding other people's faces", () => {
  it("starts hiding faces on the last render", async () => {
    const fetcher = show(<FaceHiding projectId={project} renderKey={render_id} />, (_url, init) => init?.method === "POST"
      ? response({ ...base, status: "RUNNING", done: 900, total: 14400 }, 202) : response(base));
    await userEvent.click(await screen.findByRole("button", { name: "다른 사람 얼굴 가리기" }));
    expect(await screen.findByRole("status")).toHaveTextContent("확인함");
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${project}/face-video`, { method: "POST" });
  });

  it("asks for my face photos first", async () => {
    show(<FaceHiding projectId={project} renderKey={render_id} />, () => response({ ...base, photo_count: 0 }));
    expect(await screen.findByRole("button", { name: "다른 사람 얼굴 가리기" })).toBeDisabled();
    expect(screen.getByText(/내 얼굴 사진을 먼저 올려 주세요/)).toBeInTheDocument();
  });

  it("plays the finished video", async () => {
    show(<FaceHiding projectId={project} renderKey={render_id} />, () => response({ ...base, status: "COMPLETED", video }));
    expect(await screen.findByLabelText("얼굴 가린 롱폼 영상")).toHaveAttribute("src", `/api${video.url}`);
    expect(screen.getByRole("button", { name: "다시 가리기" })).toBeEnabled();
  });
});
