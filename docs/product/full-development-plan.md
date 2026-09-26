# Cutory Full Product Development Plan

> Status: Full Product Design Source of Truth
> Scope: Cutory가 최종적으로 무엇이 되어야 하는지를 정의한다. 현재 MVP 구현 상태나 Version Roadmap과는 다르다.

## 1. 목적

Cutory / AI Vlog Editor는 수 시간, 100개 이상의 원본 영상에서 사용자 의도와 촬영 내용, 장기 편집 취향, 현재 프로젝트 요구를 함께 이해하여 하나의 완성된 브이로그를 만드는 Multi-Agent AI Video Editing System이다.

```text
Scene Discovery
→ Story / Episode Planning
→ Caption / BGM / Color / Effect Planning
→ Fast Preview
→ AI Reviewer
→ User Review and Targeted Revision
→ Final Render
→ Optional Short-form Planning
```

핵심 제품 철학은 다음과 같다.

> 사용자의 창작 판단은 남기고, 반복적인 탐색과 편집 노동은 AI에게 맡긴다.

## 2. Typical Project

- Source Videos: 일반적으로 100개 이상
- Total Footage: 수 시간
- Edit Memo: 일부 영상에만 존재할 수 있음
- Input Variability: 길이, 품질, codec, 오디오 유무가 서로 다름
- Main Output: 일반적으로 15~25분 Main Vlog
- Target Duration: 사용자가 직접 지정 가능

촬영량이 많으면 시스템은 한 편으로 압축하거나 장소·주제·스토리 흐름에 따른 Episode 분할안을 제안한다. 분할은 사용자 확인 전에 자동 확정하지 않는다.

## 3. 핵심 제품 원칙

1. Memo-guided Editing과 Autonomous Scene Discovery를 동시에 지원하며, Memo가 있다는 이유로 Autonomous Discovery를 끄지 않는다.
2. Memo는 강한 사용자 의도 Evidence지만, Memo가 없어도 전체 footage에서 사건·반응·스토리를 발견한다.
3. 100+ 영상을 모두 같은 비용의 AI로 처리하지 않고 `Cheap → Expensive Analysis`를 따른다.
4. Agent는 판단하고 Tool은 검증 가능한 실행을 담당한다.
5. 확률적 결과는 ID를 선택하고, 시간·파일·렌더링은 deterministic validator와 Tool이 담당한다.
6. Preview, AI Review, User Review, Final Render를 분리한다.
7. 장기 선호는 명시적 동의 없이 한 번의 행동으로 변경하지 않는다.
8. 실패는 전체 재시작이 아닌 partial failure와 targeted retry로 다룬다.
9. 원본 영상·음성은 local-first, external-provider 최소 전송을 기본으로 한다.
10. 라이선스 적격성은 AI 추측이 아닌 구조화 DB field와 validator로 판단한다.

## 4. 전체 Component

| Component | 책임 | 상세 문서 |
| --- | --- | --- |
| Product/Journey | 사용자 문제, 최종 경험, 승인 경계 | [Product Vision](product-vision.md), [User Journey](user-journey.md) |
| Ingestion/Media | 100+ 영상 점진 업로드·분석 | [Large Video Processing](../architecture/large-video-processing.md) |
| Scene Agent | Memo+Autonomous 장면 후보와 Evidence | [Scene Agent](../agents/scene-agent.md) |
| Style Agent | Profile/Project/Instruction을 ResolvedStyle로 해석 | [Style Agent](../agents/style-agent.md) |
| Edit Planner | Event Group을 이야기, Episode, EditPlan으로 구성 | [Edit Planner](../agents/edit-planner.md) |
| Creative Agent | Caption/BGM/Color/Transition/SFX 실행 계획 | [Creative Agent](../agents/creative-agent.md) |
| Reviewer | 문제 근거와 retry target 지정 | [Reviewer](../agents/reviewer-agent.md) |
| Orchestrator | 상태, routing, wait, resume, bounded retry | [Orchestrator](../agents/orchestrator.md) |
| Tool/MCP | Agent 판단을 안전한 영상 처리로 실행 | [Tool Layer](../tools/tool-layer.md), [MCP](../mcp/mcp-architecture.md) |
| RAG/Memory | 편집 지식, 스타일 사례, BGM 검색, 명시적 선호 | [RAG](../rag/rag-architecture.md), [Database/Memory](../database/database-memory.md) |
| Privacy/License | 최소 전송, 보존, 라이선스 검증 | [Privacy/License](../privacy/privacy-license.md) |
| Frontend | 대량 업로드, 제안, preview, 수정, 승인 UX | [Frontend UX](../frontend/frontend-ux.md) |

## 5. 전체 흐름

```text
Frontend → FastAPI → Project/Ingestion
→ Incremental Media Processing → Cheap Deterministic Analysis
→ Scene Segmentation/Evidence → Candidate Reduction
→ Cross-video Event Grouping
→ Orchestrator
→ Scene / Style / Edit Planner / Creative Agents
→ MCP Client → Video Editing MCP Server → Deterministic Tools
→ Preview Render → Reviewer → Targeted Retry
→ User Review → Targeted Revision → Final Render
→ Optional Short-form Planning
```

PostgreSQL/Memory, Vector Retrieval/RAG, File/Object Storage, Temporary Workspace는 이 흐름의 구조화 상태·검색·binary·중간 산출물을 각각 담당한다.

## 6. 중요 정책

- 우선순위: `CurrentInstruction > ProjectStyle > UserStyleProfile > RetrievedStyleReference > SystemDefault`
- Reviewer: `PASS`, `PASS_WITH_WARNINGS`, `RETRY_REQUIRED`, `USER_DECISION_REQUIRED`
- Retry: targeted retry 기본 최대 2회, review cycle 기본 최대 3회. 정확한 횟수는 평가 후 조정 가능하다.
- Optional failure: BGM/Color enhancement/SFX/Shorts 실패는 warning과 결함 없는 fallback 출력으로 전체 실패를 피한다.
- Critical failure: 핵심 Scene 처리, Edit Planning, Core Render 실패는 명시적 중단/decision을 요구한다.
- Data lineage: FinalRender → CreativePlan version → EditPlan version → SceneCandidate → SourceVideo를 추적한다.

## 7. Main Vlog와 Short-form

Main Vlog가 기본 출력이며, 이후 Final Vlog Scene과 본편에서 사용하지 않은 Highlight, Behind, Reaction을 함께 활용해 Shorts/Reels 후보를 제안할 수 있다. Short-form은 완성본에서 임의의 30초를 자르는 기능으로 축소하지 않는다.

## 8. 현재 구현과의 경계

현재 FastAPI, Streamlit, `VideoProcessingPipeline`, fixed-window Baseline, Scene/VLM Spike는 Full Product 전체가 아니다. 이들은 Full Product 구조를 결정하기 전에 검증한 Baseline, feasibility, integration history로 보존한다. 현재 범위는 [MVP v1 Specification](../mvp-v1-spec.md), 실험 결과는 `evaluation/results/`, 실제 통합 검증은 `docs/integration-eval01-v0.1.md`와 `docs/browser-e2e-v0.1.md`를 따른다.

## 9. 하지 않는 일

- 이 문서에서 v1/v2/v3 구현 범위나 일정을 확정하지 않는다.
- 현재 구현되지 않았다는 이유로 Full Product 기능을 삭제하지 않는다.
- Agent가 raw shell, arbitrary FFmpeg, raw filesystem path를 다루게 하지 않는다.
- Evaluation의 Ground Truth와 Oracle을 사용자 실행 경로에 연결하지 않는다.

## 10. 향후 확장과 미결정

Version Roadmap, 정확한 모델/Provider, infra vendor, storage retention 기간, 과금 정책, 평가 dataset 규모, 배포 topology는 이 Full Design 확인 후 별도로 결정한다.
