import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { HomePage } from "@/features/projects/home-page";
import { ProjectPage } from "@/features/projects/project-page";
import { createProject, uploadSource, validateVideo } from "@/api/projects";

const id = "11111111-1111-4111-8111-111111111111";
const sourceId = "22222222-2222-4222-8222-222222222222";
const project = { project_id: id, name: "주말 기록", status: "CREATED", split_policy: "SINGLE", target_duration_seconds: null, instruction: null, created_at: "2026-10-25T00:00:00Z", updated_at: "2026-10-25T00:00:00Z", source_count: 1, processing: { total_sources: 1, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 1, progress_ratio: 0 } };
const source = { source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "REGISTERED", stages: [] };
const processing = { project_id: id, project_status: "CREATED", total_sources: 1, completed_count: 0, failed_count: 0, blocked_count: 0, remaining_count: 1, progress_ratio: 0, sources: [source] };

function json(status: number, data: unknown) { return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } }); }
function renderAt(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, refetchOnWindowFocus: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><Routes><Route path="/" element={<HomePage />} /><Route path="/projects/:projectId" element={<ProjectPage />} /></Routes></MemoryRouter></QueryClientProvider>);
}

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("project entry", () => {
  it("shows a connection error for an empty Vite proxy 5xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 500 })));
    await expect(createProject("offline check")).rejects.toMatchObject({ message: "서버에 연결할 수 없습니다.", status: 500 });
  });
  it("creates a project using the actual SINGLE request and navigates to its URL", async () => {
    const fetcher = vi.fn().mockImplementation((url: string, options?: RequestInit) => Promise.resolve(json(options?.method === "POST" ? 201 : 200, url.endsWith("/processing") ? processing : project))); vi.stubGlobal("fetch", fetcher);
    renderAt("/");
    await userEvent.type(screen.getByLabelText("프로젝트 이름"), "주말 기록");
    await userEvent.click(screen.getByRole("button", { name: /프로젝트 만들기/ }));
    await waitFor(() => expect(fetcher).toHaveBeenCalledWith("/api/projects", expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "주말 기록", split_policy: "SINGLE" }) })));
    await screen.findByText("촬영 영상 등록");
  });
  it("shows create failure and keeps the user on the entry screen", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string) => Promise.resolve(
      url.startsWith("/api/projects?") ? json(200, { items: [], next_offset: null }) : json(503, { detail: { code: "PROJECT_DATABASE_UNAVAILABLE" } })
    )));
    renderAt("/"); await userEvent.type(screen.getByLabelText("프로젝트 이름"), "새 프로젝트");
    await userEvent.click(screen.getByRole("button", { name: /프로젝트 만들기/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("PROJECT_DATABASE_UNAVAILABLE");
    expect(screen.getByText("프로젝트 ID로 열기")).toBeInTheDocument();
  });
  it("rejects malformed IDs and reports a missing project", async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(
      url.startsWith("/api/projects?") ? json(200, { items: [], next_offset: null }) : json(404, { detail: { code: "PROJECT_NOT_FOUND" } })
    )); vi.stubGlobal("fetch", fetcher);
    renderAt("/"); const input = screen.getByLabelText("프로젝트 ID");
    await userEvent.type(input, "wrong"); await userEvent.click(screen.getByRole("button", { name: /ID로 열기/ }));
    expect(screen.getByRole("alert")).toHaveTextContent("올바른 프로젝트 ID"); expect(fetcher).not.toHaveBeenCalledWith(`/api/projects/${id}`, undefined);
    await userEvent.clear(input); await userEvent.type(input, id); await userEvent.click(screen.getByRole("button", { name: /ID로 열기/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("프로젝트를 찾을 수 없습니다");
  });
});

describe("upload contract", () => {
  it("accepts MOV and MP4, rejects invalid type, empty and oversized files", () => {
    expect(validateVideo(new File(["movie"], "a.MOV", { type: "video/quicktime" }))).toBeNull();
    expect(validateVideo(new File(["movie"], "a.mp4", { type: "video/mp4" }))).toBeNull();
    expect(validateVideo(new File(["movie"], "a.txt", { type: "text/plain" }))).toMatch(/MOV/);
    expect(validateVideo(new File(["movie"], "a.mp4", { type: "text/plain" }))).toMatch(/일치/);
    expect(validateVideo(new File([], "a.mp4", { type: "video/mp4" }))).toMatch(/빈 파일/);
    const huge = new File(["x"], "huge.mp4", { type: "video/mp4" });
    Object.defineProperty(huge, "size", { value: 4 * 1024 ** 3 + 1 });
    expect(validateVideo(huge)).toMatch(/4 GiB/);
  });

  class FakeXHR {
    static instances: FakeXHR[] = [];
    upload: { onprogress: ((event: ProgressEvent) => void) | null } = { onprogress: null };
    onload: (() => void) | null = null; onerror: (() => void) | null = null; onabort: (() => void) | null = null; onloadend: (() => void) | null = null;
    responseType = ""; status = 0; response: unknown = null; url = ""; body: Document | XMLHttpRequestBodyInit | null = null;
    constructor() { FakeXHR.instances.push(this); }
    open(_method: string, url: string) { this.url = url; }
    send(body: Document | XMLHttpRequestBodyInit | null) { this.body = body; }
    abort() { this.onabort?.(); this.onloadend?.(); }
    finish(status: number, body: unknown) { this.status = status; this.response = body; this.onload?.(); this.onloadend?.(); }
  }
  it("reports byte transfer separately and accepts only the server registration response", async () => {
    FakeXHR.instances = []; vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const updates: Array<number | null> = [];
    const result = uploadSource(id, new File(["data"], "clip.MOV", { type: "video/quicktime" }), new AbortController().signal, (value) => updates.push(value));
    const xhr = FakeXHR.instances[0];
    expect(xhr.url).toBe(`/api/projects/${id}/sources`); expect(xhr.body).toBeInstanceOf(FormData);
    xhr.upload.onprogress?.({ lengthComputable: true, loaded: 2, total: 4 } as ProgressEvent);
    expect(updates).toEqual([50]);
    xhr.finish(201, { project_id: id, source_video_id: sourceId, original_filename: "clip.MOV", processing_status: "REGISTERED" });
    await expect(result).resolves.toMatchObject({ source_video_id: sourceId });
  });
  it("handles upload cancellation and server failure without claiming registration", async () => {
    FakeXHR.instances = []; vi.stubGlobal("XMLHttpRequest", FakeXHR);
    const abort = new AbortController();
    const cancelled = uploadSource(id, new File(["x"], "clip.MOV"), abort.signal, () => {});
    abort.abort(); await expect(cancelled).rejects.toMatchObject({ name: "AbortError" });
    const failed = uploadSource(id, new File(["x"], "clip.MOV"), new AbortController().signal, () => {});
    FakeXHR.instances.at(-1)!.finish(415, { detail: { code: "INVALID_SOURCE_MEDIA" } });
    await expect(failed).rejects.toMatchObject({ code: "INVALID_SOURCE_MEDIA" });
  });
});

describe("source processing screen", () => {
  it("loads an existing project and persisted source state after a fresh page load", async () => {
    const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(json(200, url.endsWith("/processing") ? { ...processing, project_status: "COMPLETED", completed_count: 1, sources: [{ ...source, processing_status: "COMPLETED" }] } : project)));
    vi.stubGlobal("fetch", fetcher); renderAt(`/projects/${id}`);
    expect(await screen.findByText("clip.MOV")).toBeInTheDocument();
    expect(screen.getByText("처리 완료")).toBeInTheDocument();
    expect(fetcher).toHaveBeenCalledWith(`/api/projects/${id}/processing`, undefined);
  });
  it("shows accepted processing as pending, then follows server status", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === "POST") return Promise.resolve(json(202, { project_id: id, accepted: true, status_url: `/projects/${id}/processing` }));
      if (url.endsWith("/processing")) { reads++; return Promise.resolve(json(200, reads < 2 ? processing : { ...processing, project_status: "COMPLETED", completed_count: 1, sources: [{ ...source, processing_status: "COMPLETED" }] })); }
      return Promise.resolve(json(200, project));
    }));
    renderAt(`/projects/${id}`); await screen.findByText("clip.MOV");
    await userEvent.click(screen.getByRole("button", { name: /영상 처리 시작/ }));
    await waitFor(() => expect(reads).toBeGreaterThanOrEqual(2));
    expect(screen.getByText("처리 완료")).toBeInTheDocument();
  });
  it("shows processing API failure and does not mark success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation((url: string, options?: RequestInit) => {
      if (options?.method === "POST") return Promise.resolve(json(409, { detail: { code: "PROJECT_PROCESSING_ALREADY_ACTIVE" } }));
      return Promise.resolve(json(200, url.endsWith("/processing") ? processing : project));
    }));
    renderAt(`/projects/${id}`); await screen.findByText("clip.MOV");
    await userEvent.click(screen.getByRole("button", { name: /영상 처리 시작/ }));
    expect(await screen.findByText(/PROJECT_PROCESSING_ALREADY_ACTIVE/)).toBeInTheDocument();
  });
});
