import { beforeEach, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { EditRender } from "@/features/edit/edit-render";

const projectId = "11111111-1111-4111-8111-111111111111";
const candidateId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const sourceId = "22222222-2222-4222-8222-222222222222";
const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });

beforeEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("blocks rendering when scene reanalysis removes a saved candidate without changing the saved plan", async () => {
  let activeCandidate = true;
  const fetcher = vi.fn().mockImplementation((url: string) => Promise.resolve(json(
    url.endsWith("/scene-candidates") ? { project_id: projectId, candidates: activeCandidate ? [{ candidate_id: candidateId, source_video_id: sourceId, start_seconds: 1, end_seconds: 2, evidence: [] }] : [] } :
      url.endsWith("/scene-edit-plan") ? { project_id: projectId, candidate_ids: [candidateId], invalid_candidate_ids: activeCandidate ? [] : [candidateId] } :
        { project_id: projectId, status: "NOT_STARTED", render_id: null, is_active: false, succeeded: false, failed: false, safe_error_code: null, download_available: false, output: null, hard_subtitle_status: "NOT_STARTED", hard_subtitle_error_code: null, hard_subtitle_download_available: false, hard_subtitle_download_url: null },
  )));
  vi.stubGlobal("fetch", fetcher);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><EditRender projectId={projectId} /></QueryClientProvider>);
  expect(await screen.findByText("저장된 편집 계획입니다.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeEnabled();
  activeCandidate = false;
  await client.invalidateQueries({ queryKey: ["scene-candidates", projectId] });
  await client.invalidateQueries({ queryKey: ["scene-edit-plan", projectId] });
  await waitFor(() => expect(screen.getByText(`무효 후보 · ${candidateId}`)).toBeInTheDocument());
  expect(screen.getByRole("button", { name: "저장된 계획으로 렌더링" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "편집 계획 저장" })).toBeDisabled();
  expect(fetcher.mock.calls.filter((call) => call[1]?.method === "PUT")).toHaveLength(0);
});
