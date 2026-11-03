import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useParams } from "react-router-dom";
import { HomePage } from "@/features/projects/home-page";

const id = "11111111-1111-4111-8111-111111111111";
const item = { project_id: id, name: "", created_at: "2026-10-28T00:00:00Z", updated_at: "2026-10-28T00:00:00Z", source_count: 2, has_edit_plan: true, latest_render_status: null };
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
function Destination() { const { projectId } = useParams(); return <p>열린 프로젝트 {projectId}</p>; }
function renderHome() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><MemoryRouter><Routes><Route path="/" element={<HomePage />} /><Route path="/projects/:projectId" element={<Destination />} /></Routes></MemoryRouter></QueryClientProvider>);
}
beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("WEB-10 project list", () => {
  it("shows loading, an empty project name, DB summaries, and opens the selected project", async () => {
    let resolve!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
    renderHome();
    expect(screen.getByText("프로젝트 목록을 불러오는 중…")).toBeInTheDocument();
    resolve(json(200, { items: [item], next_offset: null }));
    const link = await screen.findByRole("link", { name: /이름 없는 프로젝트/ });
    expect(link).toHaveTextContent("영상 2개");
    expect(link).toHaveTextContent("편집 계획 있음");
    expect(link).toHaveTextContent("최근 렌더 기록: 없음");
    await userEvent.click(link);
    expect(screen.getByText(`열린 프로젝트 ${id}`)).toBeInTheDocument();
  });
  it("shows empty and API error states", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { items: [], next_offset: null })));
    renderHome();
    expect(await screen.findByText(/저장된 프로젝트가 없습니다/)).toBeInTheDocument();
  });
  it("uses the same fallback if a list item has no name", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(200, { items: [{ ...item, name: null }], next_offset: null })));
    renderHome();
    expect(await screen.findByRole("link", { name: /이름 없는 프로젝트/ })).toBeInTheDocument();
  });
  it("shows a failed list request without removing project creation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json(503, { detail: { code: "PROJECT_DATABASE_UNAVAILABLE" } })));
    renderHome();
    expect(await screen.findByText(/프로젝트 목록을 불러오지 못했습니다/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /프로젝트 만들기/ })).toBeInTheDocument();
  });
});
