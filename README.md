# 🎬 AI Vlog Editor

> Working product name: **Cutory** (WIP)
>
> 사용자의 편집 의도는 남기고, 반복적인 영상 편집 노동은 AI에게 맡깁니다.

AI Vlog Editor는 촬영 중 남긴 음성 편집 메모를 이용해 긴 브이로그 원본에서 필요한 장면을 찾고, 실제 영상 결과물로 만드는 프로젝트입니다.

사용자의 창작 판단을 AI가 대신하는 것보다, 사용자가 이미 내린 판단을 탐색·구조화·실행하는 데 집중합니다.

## Core Idea

촬영하면서 다음과 같이 편집 의도를 남깁니다.

> “AI야 방금 장면 꼭 살려줘.”

시스템은 업로드된 영상에서 해당 발화와 타임스탬프를 찾고, “방금”이 가리키는 장면 후보를 선택해 실제 MP4 클립으로 추출합니다.

## MVP v1

```text
Video → Audio → STT → Timestamp → Edit Memo → Candidate Interval → Evaluation → FFmpeg → MP4
```

초기에는 복잡한 LLM/VLM 판단 대신 메모 이전 5·10·15·30초를 선택하는 규칙 기반 Baseline을 비교합니다. Ground Truth와의 IoU를 측정하고 실패 사례가 다음 기술의 필요성을 결정합니다.

## Roadmap

1. **MVP Baseline** — 음성 메모 탐지와 실제 장면 추출
2. **Scene Retrieval Improvement** — 장면 경계와 의미 검색 개선
3. **Conversational Editing** — 자연어 수정 요청을 편집 작업으로 변환
4. **Personalization** — 사용자 편집 선호 반영
5. **Narrative Editing** — 여러 장면을 하나의 이야기로 구성
6. **Multi-platform Short-form** — Shorts/Reels용 편집안과 실제 영상 생성
7. **Agent Workflow Review** — 동적 재계획 필요성이 확인된 뒤 검토

## Technology Strategy

### MVP v1

- Python
- FastAPI
- FFmpeg
- STT — faster-whisper `small` Baseline

### 필요성이 검증된 이후

- Embedding / Semantic Search
- LLM / VLM
- 데이터베이스와 Object Storage
- Tool Calling / Agent Workflow

기술을 먼저 선택하지 않고 `Baseline → Evaluation → Failure Analysis → Improvement` 순서로 도입합니다.

## Documentation

- [Cutory Full Product Design Source of Truth](docs/product/full-development-plan.md)
- [Version Roadmap](docs/roadmap/version-roadmap.md)
- [Completed v1 Detailed Plan](docs/roadmap/v1-plan.md)
- [Cutory v1 Completion](docs/roadmap/v1-completion.md)
- [Cutory v1 Foundation Evaluation](evaluation/results/cutory-v1-foundation-eval-v0.1.md)
- [Full Product Architecture](docs/architecture/full-architecture.md)
- [Full Product User Journey](docs/product/user-journey.md)
- [Product Specification](docs/product-spec.md)
- [MVP v1 Specification](docs/mvp-v1-spec.md)
- [Architecture](docs/architecture.md)
- [eval_01 End-to-End Integration Verification](docs/integration-eval01-v0.1.md)
- [Browser End-to-End Integration Verification](docs/browser-e2e-v0.1.md)
- [Project Plan](docs/project-plan.md)
- [UI / UX Design](docs/ui-design.md)
- [Evaluation Dataset v0.1](evaluation/README.md)
- [Codex Project Instructions](AGENTS.md)

## Current Repository Status

2026-09-29 현재 저장소에서 확인된 상태입니다.

> Previous: **v1 — Project & Large Video Foundation: Completed**
>
> Current: **v2 Step 7-B — Deterministic Pair Reduction + Conservative Event Grouping**
>
> 아래 목록은 Historical Baseline과 완료된 v1 구현 상태를 함께 구분해 기록한다. [Full Product Design](docs/product/full-development-plan.md) 전체가 구현됐다는 의미는 아니다.

- [x] 프로젝트 문제와 제품 원칙 정의
- [x] MVP v1 범위 및 평가 전략 정의
- [x] Evaluation Dataset v0.1 시나리오 설계
- [x] Test 01 촬영 및 Ground Truth 기록
- [x] FastAPI 기본 환경과 `GET /health`
- [x] `POST /videos/upload` — 업로드 파일명과 Content-Type 확인
- [x] `POST /videos/process` — 필수 fixed Window와 multipart 영상을 받아 공유 STT 모델로 End-to-End Pipeline 실행
- [x] `GET /videos/clips/{run_id}/{clip_id}` — 생성된 MP4를 검증된 UUID 경로와 `video/mp4` 응답으로 제공
- [x] Streamlit MVP — FastAPI만 호출해 영상 업로드, 수동 Window 선택, Transcript·EditMemo·Candidate·MP4 확인
- [x] MOV/MP4 업로드 검증 및 UUID 파일명 기반 로컬 저장
- [x] ffprobe 기반 기본 미디어 정보 조회
- [x] FFmpeg 오디오 추출 — 로컬 영상의 첫 오디오 스트림을 16 kHz mono PCM WAV로 안전하게 생성
- [x] faster-whisper `small` 기반 한국어 STT Baseline — 실제 `eval_01.wav`에서 segment 및 word timestamp 검증
- [x] 규칙 기반 편집 메모 탐지 — trigger 음가 정규화·제한적 유사도와 reference/action 순서 조건 사용
- [x] EditMemo 시점 기반 5·10·15·30초 고정 구간 Scene Candidate 생성
- [x] 2.0초 초과 침묵 기반 Transcript Block 생성 및 최신 block Scene Candidate 선택
- [x] Provider 독립적 의미 기반 Block Selector Schema와 deterministic 검증 계층
- [x] OpenAI `gpt-6-luna` Responses API용 Semantic Block Selector 구현 — 실제 eval_01~05 API 평가는 미실행
- [x] Gemini `gemini-3.5-flash` Structured Outputs용 Semantic Block Selector 구현 — 실제 eval_01~05 API 평가는 미실행
- [x] Ground Truth 대비 IoU·Coverage·구간 경계 오차 계산
- [x] FFmpeg 기반 MP4 클립 생성 — H.264/AAC 재인코딩 및 실제 `eval_01.MOV` 5초 Candidate 검증
- [x] MVP End-to-End application service — probe, 오디오 추출, STT, 메모 탐지, 명시적으로 주입된 Scene Selector와 클립 렌더링을 순차 실행
- [x] Cutory v1 PostgreSQL 개발 기반 — PostgreSQL 17.11 Compose, SQLAlchemy 2.x Engine/Session과 분리된 DB 테스트
- [x] Cutory v1 Product Data Model — Project, SourceVideo, ProcessingStage, Transcript, EditMemo와 최초 Alembic revision
- [x] Cutory v1 Source Ingestion — Project별 로컬 Original Storage, SourceVideo persistence, SHA-256 fingerprint와 PENDING stage 초기화
- [x] Cutory v1 Source Processing — 기존 Probe·Audio·STT·Memo 서비스를 SourceVideo/ProcessingStage와 연결하고 결과를 PostgreSQL에 단계별 영속화
- [x] Cutory v1 Source Resume — 결과 유효성 기반 Resume, 명시적 Retry/Reprocess, stale RUNNING 복구와 downstream invalidation
- [x] Cutory v1 Project Processing — 다중 Source 선택·순차/제한 동시 처리, 완료 결과 재사용과 부분 실패 집계
- [x] Cutory v1 Project API — Project/Source 등록, 202 processing 시작과 PostgreSQL 기반 진행 상태 조회
- [x] Cutory v1 Foundation Evaluation — 120 synthetic Source와 480 Stage의 scale/state/failure 검증
- [x] Cutory v1 Completion — Completion Gate, 한계와 v2 handoff 문서화
- [x] Cutory v2 Scene Data Foundation — SceneCandidate/Evidence/Relation, EventGroup membership와 Scene 전용 WorkItem/Attempt schema
- [x] Cutory v2 Internal Tool Layer — resource ID 기반 Probe·Audio·STT·Memo adapter, safe `ToolResult`와 opaque temporary audio reference
- [x] Cutory v2 Video Editing MCP Server — stdio transport와 `probe_video` 단일 공개 capability
- [x] Cutory v2 Memo-guided Scene Discovery deterministic baseline — persisted EditMemo에서 bounded proposal, 선택/abstain, 검증, Candidate/Evidence 영속화
- [x] Cutory v2 Autonomous Scene Discovery deterministic baseline — transcript/audio/visual/quality cheap signal, cross-modal promotion, partial failure와 Evidence 영속화
- [x] Cutory v2 Selective Text LLM — deterministic selector가 해결하지 못한 bounded Memo Proposal만 OpenAI Structured Outputs로 선택하거나 abstain하고 Python manifest validator와 별도 semantic WorkItem/Attempt로 검증·영속화
- [x] Cutory v2 deterministic Event Grouping baseline — explicit cheap blocking으로 Candidate pair를 축소하고 exact duplicate Relation, conservative accepted-relation grouping, unassigned와 incremental processing을 영속화
- [x] Cutory v2 Scene Resume / Reprocess — Work result contract, Candidate result-link, modality별 fingerprint, targeted invalidation, explicit retry/stale recovery와 incremental Event update

Scene Data Foundation은 discovery 결과를 저장하기 위한 persistence 기반을 제공한다. 일반 `SceneUnit`, 별도 `QualityFlag`, `SceneRole`, CandidatePriority와 Final Scene table은 만들지 않았다. Scene 전용 실행 상태는 완료 결과의 input/config/producer와 Work별 result contract를 검사하고, result-link가 가리키는 최신 유효 Candidate만 Event snapshot에 포함한다.

Internal Tool Layer는 기존 `probe_media`, `extract_audio`, `transcribe_audio`, `detect_edit_memos`를 다시 구현하지 않고 안전한 resource resolution과 구조화 결과 경계로 감싼다. Source Tool 입력은 UUID이며 raw path나 storage reference를 받지 않는다. 추출 WAV는 실제 workspace registry가 opaque artifact ID로 관리하고 Tool 결과에 경로를 노출하지 않는다. `ToolResult`는 한 번의 in-process 호출 결과이며 durable `SceneAnalysisWorkItem`/`SceneAnalysisAttempt`와 별개다. Tool 내부 business retry는 구현하지 않았다.

Video Editing MCP Server는 `python -m backend.app.mcp.server`로 실행하는 local-first stdio process다. 현재 공개 Tool은 `probe_video` 하나뿐이며 MCP adapter가 Internal Tool을 정확히 한 번 호출한다. MCP 응답은 allowlist media metadata, safe error와 실행 metadata만 포함하고 raw path·storage reference·stderr·credential을 제외한다. Resources/Prompts, extract_audio/STT/Memo 공개, Streamable HTTP와 Scene/Agent 기능은 아직 구현하지 않았다.

Memo-guided Scene Discovery는 persisted `EditMemo` 하나를 `MemoIntent → TemporalSearchRegion → SceneProposal[] → deterministic selection/abstain → validator`로 처리한다. production 지원은 `KEEP`과 `JUST_NOW`/`EARLIER`, same-source search로 제한한다. 선택 성공 시 기존 `SceneCandidate(MEMO_GUIDED)`와 `USER_MEMO`, `TEMPORAL_REFERENCE`, `TRANSCRIPT_MATCH`, `SEMANTIC_SELECTION` Evidence를 저장하며, 의미가 불명확하면 WorkItem/Attempt를 정상 완료하고 Candidate를 만들지 않는다. 이 경로 자체에는 LLM/VLM이나 audio/visual refinement가 없고 새 MCP Tool도 추가하지 않았다. 로컬 eval 5개가 없어 실제 historical 평가는 실행하지 않았고 synthetic focused 결과는 `evaluation/results/memo-guided-baseline-v0.1.md`에 기록한다.

Autonomous Scene Discovery는 EditMemo와 독립적으로 persisted Transcript 구조, PCM RMS activity/silence, FFmpeg grayscale frame difference/static interval을 분석한다. 단일 speech·audio·motion·quality signal은 Candidate로 승격하지 않고 reaction+audio, transcript structure+audio 또는 audio+visual이 같은 구간에서 겹치는 명시적 rule만 사용한다. Candidate confidence는 null이며 exact interval만 재사용한다. Memo Candidate와 정확히 겹치면 기존 Candidate의 provenance를 유지한 채 Autonomous Evidence를 추가하고, high-overlap 구간은 병합하지 않는다. modality partial failure는 별도 WorkItem/Attempt에 남기고 가능한 signal로 정상 completion할 수 있다. LLM/VLM 호출은 0이며 실제 media/GT가 없어 semantic accuracy는 아직 검증되지 않았다. 결과는 `evaluation/results/autonomous-baseline-v0.1.md`에 기록한다.

Selective Text LLM 경로는 기존 Memo-guided deterministic selector가 유일한 Proposal을 선택한 경우 Provider를 호출하지 않는다. Transcript Proposal이 의미적으로 경쟁하거나 `EARLIER` 의미 참조가 해결되지 않은 경우에만 bounded Memo와 Proposal snippet을 `TranscriptProposalSelector`로 전달한다. OpenAI adapter의 기본 모델은 config로 교체 가능한 `gpt-6-luna`이고, Responses API Structured Outputs 결과는 기존 Proposal ID 또는 `AMBIGUOUS`/`NO_MATCH`/`INSUFFICIENT_EVIDENCE`만 허용한다. Python validator가 ID allowlist, schema/capability와 manifest를 다시 검증하며 timestamp는 로컬 Proposal이 계속 소유한다. Provider 실패는 별도 semantic WorkItem/Attempt에만 기록되고 기존 deterministic 결과를 삭제하지 않는다. 현재 개발 환경에는 `OPENAI_API_KEY`가 없어 실제 Provider 평가는 실행하지 않았으며 synthetic contract와 PostgreSQL persistence 결과는 `evaluation/results/selective-text-llm-v0.1.md`에 기록한다. VLM과 새 MCP Tool은 추가하지 않았다.

Deterministic Event Grouping baseline은 Project Candidate snapshot에서 bounded transcript token, Evidence type, source ordering과 exact source identity를 explicit blocking reason으로 사용해 likely pair만 만든다. 이 신호는 relation decision이 아니며 production에서 자동 생성하는 Relation은 같은 source fingerprint와 0.001초 정규화 interval이 모두 일치하는 canonical `DUPLICATE`뿐이다. EventGroup engine은 이미 accepted된 `SAME_EVENT`만 입력으로 받고, singleton·single bridge merge·multiple current membership을 금지한다. 근거가 부족한 Candidate는 정상 unassigned로 유지한다. 600 synthetic Candidate scale은 pair reduction 구조만 검증하며 실제 semantic grouping accuracy를 의미하지 않는다. LLM/VLM 호출과 새 MCP Tool은 없다.

Scene Resume/Reprocess 통합은 `scene_analysis_work_result_candidates`로 WorkItem의 현재 Candidate 결과를 명시한다. Transcript/Audio/Visual Work는 독립 fingerprint를 사용하고 Promotion은 modality result fingerprint에 의존하므로 변경되지 않은 modality와 동일한 downstream 결과를 재사용한다. FAILED retry와 stale RUNNING recovery는 명시적 호출만 허용하고, Source/Project parent row lock과 commit 전 input revalidation을 위한 경계를 제공한다. Event grouping validity에는 accepted Relation set이 포함되며 Candidate 변화가 있을 때만 caller가 incremental Event update를 요청한다. 이는 distributed queue, scheduler 또는 immutable history가 아니다.

End-to-End Pipeline은 선택 Window를 자동 판단하지 않는다. 호출자가 `FixedWindowSceneSelector(window_seconds=...)`처럼 선택 전략과 값을 명시해야 하며, Ground Truth와 Evaluator는 사용자 실행 경로에 포함하지 않는다.

### MVP Backend Integration

실제 `eval_01.MOV`를 `VideoProcessingPipeline.process()` 한 번으로 처리해 STT, EditMemo 탐지, 명시적 5초 Candidate 선택과 H.264/AAC MP4 생성을 완료했다. 상세 결과는 [End-to-End Integration Verification](docs/integration-eval01-v0.1.md)에 기록한다.

FastAPI는 lifespan에서 faster-whisper 모델을 한 번 로드해 재사용하고, `/videos/process`의 blocking Pipeline을 단일 동시 실행 semaphore와 threadpool에서 처리한다. 처리 응답은 로컬 절대 경로 대신 안전한 clip ID·파일명·상대 `download_url`을 제공하며, 다운로드 endpoint는 `outputs/api/<run-id>/clips/` 아래 MP4만 반환한다.

Streamlit MVP는 backend service를 직접 import하지 않는 HTTP client다. 사용자가 5·10·15·30초 Window를 직접 선택하며 AI가 최적 길이를 자동 선택하지 않는다. 실시간 progress/SSE는 아직 구현하지 않았다.

실제 브라우저에서 Streamlit → FastAPI → VideoProcessingPipeline → MP4 재생 흐름을 검증했다. 실행 결과와 검증 범위는 [Browser End-to-End Integration Verification](docs/browser-e2e-v0.1.md)에 기록한다.

원본 테스트 영상은 개인정보와 용량 문제로 Git에 포함하지 않습니다.

## Local PostgreSQL Foundation

Cutory v1은 Product table을 추가하기 전에 PostgreSQL 17.11, SQLAlchemy 2.x와 Alembic을 사용하는 개발 기반을 먼저 구성한다. 현재 DB 연결은 기존 Baseline API startup과 분리되어 있으므로 PostgreSQL을 실행하지 않아도 기존 `/health`와 영상 처리 기능을 사용할 수 있다.

PowerShell에서 로컬 DB를 준비하고 연결을 확인한다.

```powershell
Copy-Item .env.example .env
# .env의 POSTGRES_PASSWORD를 로컬 전용 값으로 변경한다.
docker compose up -d postgres
$env:RUN_DATABASE_INTEGRATION_TESTS = "1"
.\.venv\Scripts\python.exe -m unittest backend.tests.integration.test_postgresql_connection -v
.\.venv\Scripts\python.exe -m alembic current
```

`.env`는 Git에서 제외된다. `compose.yaml`은 Docker named volume을 사용하므로 PostgreSQL data directory가 저장소에 생성되지 않는다. 최초 Product revision은 `projects`, `source_videos`, `processing_stages`, `transcripts`, `edit_memos`를 생성한다. 로컬 PostgreSQL에서 upgrade, schema inspection, downgrade와 re-upgrade를 검증했다. 기존 단일 영상 Baseline은 DB startup을 강제하지 않으며, v1 Product application/API 경로가 별도로 PostgreSQL을 사용한다.

## Product Original Source Storage

Product source ingestion은 원본 MOV/MP4 binary를 저장소 루트의 `storage/originals/projects/<project-id>/sources/` 아래 UUID 파일명으로 저장하고, PostgreSQL `source_videos`에는 원본 파일명, machine-independent 상대 resource reference와 SHA-256 fingerprint만 기록한다. 파일 저장과 동시에 fingerprint를 계산하며, 같은 Project의 동일 fingerprint는 식별 정보로 반환하되 자동 거부하지 않는다. 등록된 SourceVideo는 `READY`, PROBE·AUDIO_EXTRACTION·STT·MEMO_DETECTION stage는 `PENDING`으로 시작한다.

이 경로는 기존 단일 영상 Baseline의 `uploads/`와 분리되어 있고 Git에서 제외된다. ingestion은 Project API와 Product processing 경로에서 사용되며, Resume/Retry/Reprocess까지 연결됐다. Object Storage는 아직 구현하지 않았다.

## Product Source Processing

`process_source()` application service는 등록된 SourceVideo 하나를 Original Storage reference로 해석한 뒤 기존 Media Probe → Audio Extraction → faster-whisper STT(`word_timestamps=True`) → Memo Detection 서비스를 순서대로 호출한다. 각 ProcessingStage는 `PENDING → RUNNING → COMPLETED` 또는 `FAILED`를 별도 commit하고, media metadata는 SourceVideo에, timestamp가 포함된 STT 결과는 Transcript에, 탐지 결과는 EditMemo에 저장한다. 오류 필드에는 stage별 안전한 code/message만 기록한다.

추출 WAV는 `temporary/projects/<project-id>/sources/<source-id>/audio/` 아래에만 생성하고 성공·실패 후 source workspace를 정리한다. Original source는 삭제하지 않는다. 기존 `VideoProcessingPipeline`과 HTTP API는 Baseline regression 경로로 그대로 공존하며, Product 경로는 명시적 Resume/Retry/Reprocess, multi-source Project runner와 Project API를 제공한다.

## Source Resume, Retry and Reprocess

Product Source processing은 Stage의 `COMPLETED`만 신뢰하지 않고 source fingerprint, 필수 Product 결과, 선택적으로 지정된 config/tool/result version을 함께 검사한다. `resume_source()`는 유효한 완료 Stage를 재사용하고 필요한 downstream만 실행한다. WAV는 temporary-by-default이므로 STT를 다시 실행해야 할 때 AUDIO를 dependency recreation attempt로 다시 기록하며 장기 보존하지 않는다. 원본 전체 SHA-256 재검사는 매 resume에 강제하지 않고 명시적인 integrity verification에서만 수행한다.

`retry_source_stage()`는 FAILED Stage를 한 번 명시적으로 재실행하고 선택적 `max_attempts`로 호출자가 retry 한도를 제공할 수 있다. 자동 retry loop와 기본 횟수는 아직 없다. `reprocess_source_from()`은 지정 Stage부터 현재 Transcript/EditMemo를 교체하고 downstream을 다시 실행한다. RUNNING은 일반 resume에서 중복 실행하지 않으며, heartbeat가 없는 현재 구조에서는 `started_at`과 호출자 cutoff를 사용하는 explicit stale recovery 뒤에만 retry할 수 있다. Stage 시작은 DB row lock과 상태 재확인으로 보호하지만 distributed lock을 보장하지 않는다.

## Product Project Processing

`process_project()`는 Project의 SourceVideo를 `created_at + id` 순서로 조회하고 Step 6의 `resume_source()`를 재사용한다. 유효한 완료 Source는 다시 실행하지 않고 `REUSED`, FAILED Source는 자동 retry 없이 보존하며, RUNNING Stage가 있는 Source는 명시적 stale recovery 전까지 `BLOCKED`로 남긴다. 한 Source 실패는 뒤 Source 처리를 중단하지 않으며 최종 Project 상태와 완료·실패·차단·잔여 수를 PostgreSQL 상태에서 집계한다.

동시성은 `max_concurrency`로 제한하고 기본값은 1이다. 병렬 실행을 명시하면 Source마다 독립 SQLAlchemy Session을 사용하지만, faster-whisper 공유 모델의 동시 호출 안전성과 자원 사용량은 아직 평가하지 않았으므로 기본값을 높이지 않았다. Project runner 자체는 동기 application service이며 자동 retry/stale recovery와 queue/worker는 포함하지 않는다.

## Product Project API

Project 기반 제품 흐름은 다음 HTTP API로 노출된다.

- `POST /projects` — Project 생성
- `GET /projects/{project_id}` — Project 정보와 처리 집계 조회
- `POST /projects/{project_id}/sources` — MOV/MP4 Source 하나 등록
- `POST /projects/{project_id}/process` — 처리를 in-process executor에 요청하고 `202 Accepted` 반환
- `GET /projects/{project_id}/processing` — PostgreSQL 기반 Project/Source/Stage 진행 상태 조회

처리 시작 요청은 전체 영상 처리가 끝날 때까지 HTTP 연결을 유지하지 않는다. lifespan이 소유하는 단일-worker executor가 기존 `process_project()`를 실행하며 shared faster-whisper 모델을 재사용한다. 같은 프로세스 안에서 동일 Project의 중복 실행 요청은 `409 Conflict`로 거부한다. 이 registry는 distributed lock이 아니며 executor 작업도 durable queue가 아니다. 프로세스가 종료돼도 PostgreSQL의 Project/Source/Stage 상태는 유지되므로 상태 조회와 사용자 재요청의 기반은 남지만, startup 자동 resume는 아직 없다.

응답은 allowlist DTO만 사용하며 storage reference, fingerprint 원문, 로컬 경로와 Transcript 본문을 포함하지 않는다. Project DB 환경변수가 없는 경우 Product API는 안전한 `503`을 반환하지만 기존 단일 영상 Baseline API startup과 실행은 계속 가능하다.

## Run the Current API

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

실행 후 `/health`에서 현재 API 상태를 확인할 수 있습니다.

별도 터미널에서 Frontend를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Backend 주소를 바꾸려면 `BACKEND_URL` 환경변수를 설정합니다. 기본값은 `http://127.0.0.1:8000`입니다.
