import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { ProjectHome } from "@/features/projects/project-home";

const project = "11111111-1111-4111-8111-111111111111";
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
const cut = (n: number, length: number) => ({ number: n, candidate_id: `33333333-3333-4333-8333-33333333333${n}`, source_video_id: project, source_filename: "a.MP4",
  start_seconds: 0, end_seconds: length, timeline_start: 0, length, speech: "", caption: null });

describe("TODO 37 project home", () => {
  it("shows a cover, one big button into the edit room, three check lines and the rest behind 더 보기", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith(`/projects/${project}`)) return Promise.resolve(response({ project_id: project, name: "학원 하루", status: "COMPLETED", created_at: "2026-11-12T09:00:00Z" }));
      if (url.endsWith("/processing")) return Promise.resolve(response({ project_id: project, project_status: "COMPLETED", total_sources: 35, completed_count: 34, failed_count: 1, blocked_count: 0, sources: [] }));
      if (url.endsWith("/day-brief")) return Promise.resolve(response({ text: "학원에서 멘토링하고 저녁 먹은 날" }));
      if (url.endsWith("/chat-edit")) return Promise.resolve(response({ project_id: project, cuts: [cut(1, 300), cut(2, 165)], total_seconds: 465, unused: [{}, {}, {}], messages: [], undo_count: 0, brains: [], default_brain: null, usage: [], dropped: 0, last: null }));
      if (url.endsWith("/taste-scores")) return Promise.resolve(response({ scenes: 182, counts: { "0": 58, "1": 55, "2": 58, "3": 11 } }));
      if (url.endsWith("/rendering")) return Promise.resolve(response({ project_id: project, status: "NOT_STARTED", is_active: false, output: null }));
      return Promise.resolve(response({ detail: "Not Found" }, 404));
    }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[`/projects/${project}`]}><Routes>
      <Route path="projects/:projectId" element={<ProjectHome />} />
    </Routes></MemoryRouter></QueryClientProvider>);

    expect(await screen.findByText(/원본 35개/)).toBeInTheDocument();
    expect(await screen.findByText(/편집안 07:45 준비됨/)).toBeInTheDocument();
    expect(screen.getByText(/컷 2개/)).toBeInTheDocument();
    expect(screen.getByText(/완성 영상 아직 없음/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "대표 장면" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /편집 이어하기/ })).toHaveAttribute("href", `/projects/${project}/chat-edit`);
    expect(screen.queryByRole("link", { name: "영상 더 넣기" })).not.toBeInTheDocument();
    expect(screen.getAllByRole("link")).toHaveLength(2);

    await userEvent.click(screen.getByRole("button", { name: /더 보기/ }));
    expect(screen.getByRole("link", { name: "영상 더 넣기" })).toHaveAttribute("href", `/projects/${project}/tools#upload`);
    expect(await screen.findByText("학원에서 멘토링하고 저녁 먹은 날")).toBeInTheDocument();
    expect(await screen.findByText(/꼭 남김 11/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "모든 도구" })).toHaveAttribute("href", `/projects/${project}/tools`);
  });
});
