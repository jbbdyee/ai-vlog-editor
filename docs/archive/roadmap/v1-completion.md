# Cutory v1 Completion

> Status: Completed
>
> Completion date: 2026-09-29
>
> Evaluation run: `cutory-v1-foundation-eval-v0.1-run1`

이 문서는 [v1 Detailed Plan](v1-plan.md)과 [v1 Foundation Evaluation](../../evaluation/results/cutory-v1-foundation-eval-v0.1.md)을 근거로 `v1 — Project & Large Video Foundation`을 공식 종료한다. 역사적 단일 영상 “MVP v1”과 Version Roadmap의 v1은 서로 다른 범위다.

## 1. Version Goal

v1의 목표는 하나의 Project에서 100개 이상의 SourceVideo를 관리할 수 있는 Project/Data/Processing Foundation을 만드는 것이었다. PostgreSQL에 처리 상태와 결과를 지속적으로 남기고, 완료 결과 재사용, Resume, Retry, Reprocess, Partial Failure, multi-source processing과 client-independent API 기반을 제공한다.

Scene Intelligence, Agent, MCP, RAG와 Creative Editing은 v1 목표가 아니었다.

## 2. What Was Built

- `backend/` 구조 migration과 기존 Baseline regression 경로 보존
- PostgreSQL 17.11, SQLAlchemy 2.x, Alembic 기반
- Project, SourceVideo, ProcessingStage, Transcript, EditMemo Product entity
- Project별 Local Original Source Storage와 SHA-256 source fingerprint
- Source ingestion과 machine-independent resource reference
- 기존 Probe, Audio Extraction, STT, Memo Detection 서비스의 Product 경로 연결
- Stage별 durable state와 결과 persistence
- 완료 결과 Resume, FAILED Stage Retry, 지정 Stage Reprocess
- stale `RUNNING` 명시적 복구와 downstream invalidation
- Project runner, source-level Partial Failure와 bounded concurrency
- FastAPI Project API, PostgreSQL 기반 status, in-process background execution

## 3. Final Architecture at v1

```text
Client (mobile-ready, client-independent)
  |
  v
FastAPI Project API
  |
  v
Application Services
  |-- Source Ingestion ------> Local Original Storage
  |-- Source Processing -----> Temporary Workspace
  |       |                   (ephemeral WAV)
  |       +-----------------> Media Probe / Audio / STT / Memo Services
  |-- Processing State
  `-- Project Processing
          |
          v
      PostgreSQL
      Project / SourceVideo / ProcessingStage / Transcript / EditMemo
```

이는 [Full Product Architecture](../architecture/full-architecture.md)의 v1 구현 부분이다. v1에는 LangGraph, Agent, MCP, Multi-Agent 또는 RAG가 없다. 최종 제품은 Mobile-first이며, v1은 특정 UI에 종속되지 않는 backend/API foundation을 만든 단계다.

## 4. Data / Processing Model

```text
Project
  `-- SourceVideo
        |-- ProcessingStage: PROBE -> AUDIO_EXTRACTION -> STT -> MEMO_DETECTION
        |-- Transcript
        `-- EditMemo
```

원본 binary는 PostgreSQL에 저장하지 않는다. SourceVideo는 원본 파일명, storage-relative reference, SHA-256 fingerprint와 media metadata를 보존한다. ProcessingStage는 실행 상태이며 Transcript와 EditMemo는 실행 결과다. Original Source는 Project lifetime 자산이고 Temporary Workspace의 WAV는 processing lifetime 자산이다.

## 5. API Surface

Product API:

- `POST /projects`
- `GET /projects/{project_id}`
- `POST /projects/{project_id}/sources`
- `POST /projects/{project_id}/process`
- `GET /projects/{project_id}/processing`

Historical/Regression Baseline API:

- `GET /health`
- `POST /videos/upload`
- `POST /videos/process`
- `GET /videos/clips/{run_id}/{clip_id}`

두 API 계열은 목적이 다르다. Project API는 v1 Product foundation이고, `/videos/*`는 단일 영상 Baseline과 기존 E2E 회귀 자산이다.

## 6. Resume / Retry / Reprocess

- **Resume**: input/result validity가 확인된 완료 결과는 재사용하고 미완료 지점부터 진행한다.
- **Retry**: `FAILED` Stage를 사용자가 명시적으로 다시 실행한다.
- **Reprocess**: 변경 사유가 있을 때 지정한 완료 Stage부터 다시 처리한다.
- **Stale recovery**: `RUNNING`을 자동으로 실패라고 추측하지 않는다. 명시적으로 stale 상태를 복구한 뒤 Retry할 수 있다.

Dependency는 `PROBE → AUDIO_EXTRACTION → STT → MEMO_DETECTION`이다. upstream 결과를 무효화하면 downstream 결과도 재사용하지 않는다.

## 7. Large Project Processing

Project runner는 같은 Project의 SourceVideo를 안정적인 순서로 처리하고 유효한 완료 Source를 재사용한다. Source 하나의 실패가 다른 Source 처리를 중단하지 않으며, 결과는 completed/failed/blocked/remaining으로 집계된다. `max_concurrency`로 동시성을 제한하고 Source별 SQLAlchemy Session을 분리한다. 기본 동시성은 1이다.

현재 실행 경계는 in-process `ThreadPoolExecutor`다. PostgreSQL state는 지속되지만 실행 작업 자체는 durable queue가 아니다.

## 8. Evaluation Evidence

[v1 Foundation Evaluation](../../evaluation/results/cutory-v1-foundation-eval-v0.1.md)은 **Synthetic Scale Evaluation**이다. 실제 대형 영상 120개 처리 결과가 아니다.

| 검증 항목 | 결과 |
|---|---:|
| Synthetic Source / ProcessingStage | 120 / 480 |
| First run | 120 completed |
| Second run | 120 reused |
| Duplicate processing | 0 |
| Partial failure | 9 completed / 1 failed, processing continued |
| Crash/restart | completed reused, `RUNNING` blocked, `READY` continued |
| Retry / Reprocess | PASS |
| Zero Memo | valid result |
| Temporary artifacts | 0 remaining |
| Original source | preserved |
| API / DB consistency | PASS |
| Bounded concurrency | configured limit respected |
| SQLAlchemy Session isolation | PASS |

평가 run ID는 `cutory-v1-foundation-eval-v0.1-run1`이다. 당시 회귀 결과는 backend 307 정상, Windows symlink 1 environment-blocked, frontend 19 passed였다.

## 9. Completion Gate

| Gate | 판정 | 근거 유형 |
|---|---|---|
| Target backend structure migration | PASS | regression/integration |
| Existing Baseline regression preserved | PASS | regression |
| PostgreSQL persistence | PASS | integration |
| Project create/read | PASS | integration/current evaluation |
| Multiple SourceVideo registration | PASS | integration/current evaluation |
| ProcessingStage persistence | PASS | integration/current evaluation |
| Real Media Probe | PASS | historical real-media evidence |
| Real Audio Extraction | PASS | historical real-media evidence |
| Real STT | PASS | historical real-media evidence |
| Real Memo Detection | PASS | historical real-media evidence |
| Transcript persistence | PASS | integration |
| EditMemo persistence | PASS | integration |
| Valid Completed Stage reuse | PASS | current evaluation |
| Failed Stage retry | PASS | current evaluation |
| Stale `RUNNING` recovery | PASS | current evaluation |
| Reprocess path | PASS | current evaluation |
| Downstream invalidation | PASS | current evaluation |
| Source-level Partial Failure | PASS | current evaluation |
| Project/Source/Stage state consistency | PASS | current evaluation |
| Original/Temporary lifecycle separation | PASS | integration/current evaluation |
| Temporary cleanup on success/failure | PASS | current evaluation + historical real-media evidence |
| 100+ synthetic Source scale scenario | PASS | current evaluation |
| Small real-media integration scenario | PASS | historical real-media evidence |
| Crash/resume scenario | PASS | current evaluation |
| Duplicate processing verification | PASS | current evaluation |
| Bounded processing structure | PASS | current evaluation |
| Project-based FastAPI flow | PASS | integration/current evaluation |
| Existing `/videos/process` regression decision documented | PASS | architecture/regression documentation |
| Evaluation documentation | PASS | current evaluation |
| v1 Failure Analysis | PASS | this completion record |
| Privacy/local-first review | PASS | design/integration review |
| v2 handoff contract documented | PASS | this completion record |

v1 Detailed Plan이 요구한 Completion Gate는 모두 PASS다. 실제 media 동작 근거 중 일부는 별도의 historical real-media evidence이며, synthetic scale 결과와 합쳐 “현재 실제 영상 120개를 처리했다”고 해석하지 않는다.

## 10. Failure Analysis / Known Limitations

### In-process execution

Project background processing은 `ThreadPoolExecutor` 기반이다. process 종료 시 execution 자체는 durable하지 않다. DB state와 manual Resume 기반은 남지만 queue/worker와 startup automatic resume는 없다.

### Heavy-media scale

120 Source 검증은 synthetic/state scale이다. 실제 100개 이상 대형 MOV의 total processing time, CPU, RAM, GPU/VRAM, disk I/O와 STT throughput은 측정하지 않았다.

### Windows symlink test

`test_symlink_escape_is_not_served`는 Windows의 symlink 생성 권한 문제 `WinError 1314`로 테스트 본문 전에 environment-blocked였다. PASS가 아니며 테스트와 security validation은 삭제·완화·skip하지 않았다.

### Default concurrency

Project runner 기본 동시성은 1이다. fake processor로 최대 2의 bounded behavior는 검증했지만 실제 faster-whisper workload의 병렬 안전성과 성능은 검증하지 않았다.

### Local Storage

Original Source는 Local Storage에 저장한다. Object Storage와 production storage topology는 아직 없다. 이는 v1의 의도된 범위다.

## 11. Intentionally Deferred

다음은 미완성으로 누락된 것이 아니라 [Version Roadmap](version-roadmap.md)의 후속 Version 범위다.

- Autonomous Scene Discovery, Scene Agent, Event Grouping, VLM Scene Understanding
- Tool/MCP, LangGraph, Multi-Agent, RAG
- Creative Agent, Reviewer, Style Memory
- Full Mobile App, Short-form
- distributed queue/worker, Object Storage, production deployment

## 12. Historical Baseline Evidence

- [eval_01 Real-media Pipeline Integration](../integration-eval01-v0.1.md)
- [Browser End-to-End Integration](../browser-e2e-v0.1.md)

이 기록은 실제 `eval_01.MOV`의 Probe → Audio → STT → Memo → clip과 Browser E2E 근거다. 현재 Windows의 Step 9에서 다시 실행한 결과가 아니며, v1 Synthetic Scale Evaluation과 구분한다.

기존 fixed-window baseline, transcript block retrieval, semantic block selection, audio boundary refinement, visual motion refinement, Gemini VLM proposal selection, Ollama/local VLM 실험과 5-frame contact sheet spike는 삭제할 실패작이 아니다. v2의 baseline, evidence generator, proposal strategy와 failure evidence로 보존한다. 특히 다음 교훈을 유지한다.

- audio activity ≠ semantic event boundary
- visual motion ≠ semantic relevance

## 13. v2 Handoff

다음 단계는 코드 구현이 아니라 `v2 — Tool / MCP & Scene Intelligence` Detailed Design이다.

v2가 그대로 이어받는 v1 자산:

- Project, SourceVideo, ProcessingStage, Transcript, EditMemo
- Original Source Storage와 Temporary Workspace 경계
- Media Probe, Audio Extraction, STT, Memo Detection
- Resume/Retry/Reprocess, Project runner, Partial Failure
- FastAPI Project API와 PostgreSQL state/lineage

v2가 새로 설계할 영역:

- Tool Layer와 Video Editing MCP Server
- Memo-guided Scene Retrieval과 Autonomous Scene Discovery
- SceneEvidence, QualityFlags, candidate reduction
- Cheap → Expensive analysis와 선택적 LLM/VLM
- SceneRelation과 cross-video Event Grouping

v2는 Tool/MCP와 Scene Intelligence foundation이다. 전체 Scene Agent, Style Agent, Edit Planner와 Orchestrator는 v3에서 본격적으로 다룬다.

## 14. Final v1 Status

**Cutory v1 — Project & Large Video Foundation: Completed.**

Project/Data/Processing foundation과 명시된 v1 Completion Gate는 충족됐다. 알려진 실행·성능·환경 제약은 위에 공개적으로 남겼다. 다음 작업은 v2 구현이 아니라 v2 Detailed Design이며, 설계가 확정되기 전 Agent/MCP/RAG 등을 임의로 도입하지 않는다.
