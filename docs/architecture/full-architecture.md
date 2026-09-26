# Cutory Full Product Architecture

## 목적

100+ 원본을 점진적으로 분석하고 Multi-Agent 판단을 안전한 Tool 실행으로 연결해 Preview, Review, Final Render를 만드는 전체 경계를 정의한다.

## 전체 구조

```text
Frontend
  ↓
FastAPI
  ↓
Project / Ingestion Layer
  ↓
100+ Video Incremental Media Processing
  ↓
Cheap Deterministic Analysis
  ↓
Scene Segmentation / Evidence / Candidate Reduction
  ↓
Cross-video Event Grouping
  ↓
LangGraph Orchestrator
  ↓
Scene Agent / Style Agent / Edit Planner / Creative Agent
  ↓
MCP Client → Video Editing MCP Server
  ↓
Tools / Existing Python Services / FFmpeg / STT
  ↓
Preview Render → Reviewer Agent → Targeted Retry
  ↓
User Review → Targeted Revision → Final Render
  ↓
Optional Short-form Planning

Side systems:
PostgreSQL / Memory
Vector Retrieval / RAG
File/Object Storage
Temporary Workspace
```

## 책임 분리

- Frontend: project setup, aggregated progress, proposal/preview/revision/approval UX
- FastAPI: user/frontend 계약, 인증·권한의 향후 경계, application service 호출
- Project/Ingestion: source ID, upload state, project instruction, resumable work registration
- Media Processing: probe, audio, STT, shot/audio/quality 신호
- Agent Layer: 의미 판단과 plan/selection
- MCP/Tool Layer: capability 계약, deterministic validation/execution
- Reviewer: 검증과 재시도 대상 지정
- Storage: structured state, binary, vector, temporary artifacts 분리

## Target Repository Structure

다음은 Full Product가 장기적으로 지향하는 target structure이며 현재 Repository 상태가 아니다.

```text
ai-vlog-editor/
├─ backend/
│  ├─ app/
│  │  ├─ api/
│  │  ├─ agents/
│  │  │  ├─ scene/
│  │  │  ├─ style/
│  │  │  ├─ planner/
│  │  │  ├─ creative/
│  │  │  └─ reviewer/
│  │  ├─ orchestrator/
│  │  ├─ tools/
│  │  ├─ mcp/
│  │  ├─ retrieval/
│  │  ├─ services/
│  │  ├─ schemas/
│  │  ├─ repositories/
│  │  └─ core/
│  └─ tests/
├─ frontend/
├─ evaluation/
│  ├─ datasets/
│  ├─ experiments/
│  └─ results/
├─ docs/
└─ README.md
```

이 구조는 현재 코드의 즉시 migration을 의미하지 않는다. 실제 migration 순서와 범위는 Full Design 검토 후 Version Roadmap에서 결정한다. Baseline/Evaluation 코드를 삭제하지 않고, migration 과정에서 기존 테스트와 개발 history를 보존한다.

## 주요 흐름

1. SourceVideo를 안전한 resource ID로 저장한다.
2. cheap analysis로 metadata, STT, Memo, shot, audio, quality, Scene segment/Evidence를 만든다.
3. 후보를 축소하고 필요한 구간만 LLM/VLM으로 심층 분석한다.
4. 파일을 넘어 SAME_EVENT/CONTINUATION/REACTION_TO/ALTERNATIVE 관계로 EventGroup을 만든다.
5. Style Agent와 Edit Planner가 ResolvedStyle, EpisodePlan, EditPlan, CreativeIntent를 만든다.
6. Creative Agent가 Approved Catalog을 사용해 CreativePlan을 만든다.
7. deterministic renderer가 Preview를 만들고 Reviewer가 검사한다.
8. bounded targeted retry 후 User Review에 진입한다.
9. 사용자 승인 후 Final Render와 선택적 Short-form Planning을 수행한다.

## Preview / Review / Final 경계

`EditPlan → CreativePlan → Fast Preview → AI Reviewer → User Review → Revision(optional) → User Approval → Final Render`의 순서를 유지한다. Reviewer는 plan을 직접 수정하지 않고 issue와 target을 반환한다. 사용자 수정은 변경 범위만 재계산한다.

## 상태와 Resume

Orchestrator의 대표 상태는 `CREATED → UPLOADING → MEDIA_ANALYZING → SCENE_ANALYZING → STYLE_RESOLVING → PLANNING → WAITING_FOR_SPLIT_DECISION? → CREATIVE_PLANNING → PREVIEW_RENDERING → REVIEWING → RETRYING? → WAITING_FOR_USER_REVIEW → REVISING? → FINAL_RENDERING → SHORT_FORM_PLANNING? → COMPLETED`다. Node 산출물은 version과 reference로 저장해 resume한다.

## 다른 Component와의 관계

LangGraph는 workflow를, FastAPI는 product API를, MCP는 Agent↔Capability 계약을 담당한다. 세 역할을 섞지 않는다. RAG는 검색이 필요한 지식/사례/BGM에만 사용하고 workflow state와 profile은 relational DB에 둔다.

## 실패 처리

- Partial source failure: source 단위 warning/제외, project 진행 유지
- Critical planning/core rendering: workflow 중단 또는 user decision
- Optional creative/short-form: 경고 후 degradation
- Agent/provider failure: 경계 내 bounded retry, 초과 시 안전한 terminal state
- Tool result: resource ID, validation, idempotency/deduplication으로 중복 실행 제한

## 하지 않는 일

- Agent 간 무제한 자유 대화
- Agent의 raw FFmpeg/shell/filesystem 실행
- 전체 원본의 무조건적 외부 Provider 전송
- AI Reviewer PASS를 사용자 승인으로 간주

## 향후 확장

배포 topology, queue/worker 선택, DB/Object Storage vendor, 모델 routing은 Version Roadmap과 운영 요구가 확정된 후 결정한다.
