# Cutory v2 — Tool / MCP & Scene Intelligence

## 1. Status

> Status: Structural/Foundation Implementation Complete — Gap Closure in progress; Version Completion not declared
>
> Previous version: [v1 — Project & Large Video Foundation](v1-completion.md) — Completed
> Version sequence: [Cutory Version Roadmap](version-roadmap.md)
> Product direction: [Cutory Full Product Development Plan](../product/full-development-plan.md)

이 문서는 Cutory v2 구현 범위, 설계 경계, 구현 순서와 Completion Gate의 Source of Truth다. 아직 구현 코드, DB migration, API, Tool 또는 MCP Server가 추가됐다는 뜻이 아니다. 세부사항이 평가 근거 없이 확정되지 않은 경우 `TBD`, `Evaluation으로 결정`, `구현 전 확정 필요`로 남긴다.

기존 `docs/mvp-v1-spec.md`의 “MVP v1”은 단일 영상 Baseline의 역사적 명칭이다. 이 문서의 v2는 Version Roadmap의 `Tool / MCP & Scene Intelligence`를 뜻한다.

## 2. Goal

v2의 목표는 100개 이상의 SourceVideo를 대상으로 Memo-guided와 Autonomous 두 경로에서 편집 후보 장면을 발견하고, 발견 근거와 장면 간 관계를 구조화하며, Scene Intelligence에 필요한 실행 capability를 Tool Layer와 MCP 경계로 제공하는 것이다.

```text
Project
→ SourceVideo[]
→ v1 Processing: MediaInfo / Transcript / EditMemo
→ Scene Intelligence
   ├─ Memo-guided Discovery
   └─ Autonomous Discovery
→ SceneCandidate + SceneEvidence + QualityFlags
→ SceneRelation
→ EventGroup
```

v2는 최종 브이로그 편집 Version이 아니다. 결과는 v3의 Scene Agent, Style Agent, Edit Planner와 Orchestrator가 사용할 구조화 기반이다. v2는 “영상에서 무엇이 관측되었는가”를 bounded Evidence와 Candidate/Relation으로 만들고 평가 가능한 상태로 보존하지만, 최종 narrative·timeline·creative decision이나 authoritative SceneRole을 내리지 않는다.

## 3. v1에서 이어받는 기반

v1에서 구현·검증된 다음 자산을 다시 만들지 않고 재사용한다.

- Project, SourceVideo, ProcessingStage, Transcript, EditMemo
- PostgreSQL, SQLAlchemy 2.x, Alembic
- Project별 Local Original Source Storage와 resource reference
- SHA-256 source fingerprint와 result validity metadata
- Media Probe, Audio Extraction, faster-whisper STT, Memo Detection
- Source ingestion과 Project/Source processing application boundary
- Resume, Retry, Reprocess, stale `RUNNING` recovery, downstream invalidation
- Project runner, Partial Failure, bounded concurrency, Session isolation
- FastAPI Project API와 DB-backed processing status
- Original Source와 Temporary Workspace lifecycle 분리

현재 저장소에는 SceneCandidate, SceneEvidence, SceneRelation, EventGroup의 Product persistence가 없다. `scene_boundary_proposals`, transcript block retrieval, semantic selectors, audio/visual refiners와 Gemini/Ollama VLM selector는 historical/experimental service다. 이를 곧바로 production truth로 승격하지 않고 v2 Baseline과 Evidence/Proposal 전략으로 재평가한다.

v1 background execution은 in-process executor이며 durable queue가 아니다. v2는 v1의 durable DB state와 manual resume 철학을 확장하되, distributed queue/worker 도입을 자동 전제로 삼지 않는다.

## 4. Scope

v2 범위는 다음과 같다.

### Scene Intelligence data foundation

- SceneUnit, SceneCandidate, SceneEvidence, QualityFlag의 표현과 lineage
- SceneRelation과 한 단계 EventGroup
- logical work item, attempt, producer/version/config 기반 result validity
- Source/Project 경계를 넘지 않는 안전한 resource reference

### Discovery

- EditMemo 기반 Memo-guided Scene Discovery
- Memo 유무와 독립적으로 실행되는 Autonomous Scene Discovery
- Transcript, Audio, Visual, Shot Structure Evidence
- proposal generation, semantic selection, deterministic validation
- candidate merge/deduplication과 conflict preservation
- authoritative SceneRole assignment가 아닌 관측 가능한 semantic/technical Evidence

### Cost-aware analysis

- Cheap deterministic analysis
- Candidate Reduction과 priority
- 선택된 구간만 LLM/VLM으로 심층 분석
- provider-independent capability와 failure taxonomy

### Execution boundary

- 의미 있는 capability 중심 Tool Layer
- 단일 Video Editing MCP Server
- resource ID, validation, structured result, safe error와 execution reference
- v1 service 재사용과 새 Scene service의 명확한 경계

### Reliability and evaluation

- Scene work-item 수준 persistence, Resume, Retry, Reprocess, stale recovery
- dependency lineage와 targeted invalidation
- Memo/Autonomous/Reduction/AI/Event/Reliability 평가
- focused, project, scale dataset의 목적별 분리

## 5. Non-goals

다음은 v2 범위가 아니며 구현 단계에서도 앞당기지 않는다.

- LangGraph 전체 orchestration
- Scene Agent 전체 판단 loop
- Style Agent, Edit Planner, Orchestrator
- Creative Agent, Reviewer Agent
- Caption 생성·적용, BGM 선택·적용, Color Grading
- 최종 Vlog 구성과 Final Render product flow
- Shorts/Reels와 Final Mobile Frontend
- RAG와 장기 Style Memory
- production deployment 최적화
- Agent 간 자유 대화 또는 Multi-Agent workflow
- Project/EditPlan context에 따른 authoritative SceneRole assignment

MCP를 구현한다는 사실은 Agent나 Multi-Agent를 구현한다는 뜻이 아니다. v2 MCP Client는 Scene Intelligence application 경계에서 Tool capability를 호출할 수 있으며, v3 Agent가 같은 capability contract를 재사용할 수 있게 한다.

## 6. Core Principles

1. **사용자 의도 우선**: Explicit User Intent인 EditMemo는 일반 heuristic score와 단순 평균하지 않는다.
2. **Evidence ≠ Decision**: audio spike, motion, transcript hit는 근거이지 좋은 장면이라는 최종 판단이 아니다.
3. **Candidate ≠ Final Scene**: v2는 검토 가치가 있는 후보를 발견한다. 최종 편집 선택은 후속 Version 책임이다.
4. **Observed Evidence ≠ Editorial Role**: reaction cue, location view, shot change와 quality signal은 관측 근거다. 최종 role은 v3 Planner의 EditPlan context에서 결정한다.
5. **Cheap → Expensive**: 전체 원본을 같은 비용으로 AI Provider에 보내지 않는다.
6. **Proposal ID selection**: AI가 authoritative timestamp를 자유 생성하지 않는다.
7. **Deterministic validation**: interval, resource ownership, proposal mapping과 실행은 일반 코드가 검증한다.
8. **Capability over provider**: business logic을 Gemini, Ollama/Qwen 등 특정 Provider에 결합하지 않는다.
9. **Structured intermediate result**: Evidence, status, version, lineage와 failure를 보존한다.
10. **Incremental and resumable**: 유효한 결과를 재사용하고 영향받은 downstream만 재계산한다.
11. **Local-first and minimal disclosure**: 전체 MOV/WAV의 외부 전송을 기본 금지하고 선택된 최소 context만 전송한다.
12. **Baseline → Evaluation → Failure Analysis → Improvement**: threshold와 모델은 평가 전에 성공을 보장하는 방향으로 조정하지 않는다.

## 7. Target Architecture

```text
Frontend / Future Mobile Client
              |
              v
      FastAPI Product API
              |
              v
Scene Intelligence Application Services
  |-- Memo-guided Discovery
  |-- Autonomous Discovery
  |-- Candidate Reduction / Merge
  |-- Relation / Event Grouping
  |-- Persistence / Resume / Reprocess
  |
  +-------- MCP Client ----------------------+
              |                              |
              v                              |
     Video Editing MCP Server                |
              |                              |
              v                              |
          Tool Layer                         |
  |-- Media / Transcript / Audio             |
  |-- Visual / Scene / Validation            |
              |                              |
              v                              |
Existing v1 Services + New v2 Services       |
FFmpeg / STT / OpenCV / selective AI Provider
              |
              +------------------------------+

PostgreSQL: entity, relation, state, lineage, result reference
Original Storage: source lifetime binary
Temporary Workspace: WAV, frame, contact sheet, analysis artifacts
```

FastAPI는 Client ↔ Cutory Product 경계다. MCP는 Cutory AI/Application ↔ Execution Capability 경계다. LangGraph는 v3 이후 workflow orchestration 후보이며 v2 architecture에 구현된 것으로 가정하지 않는다.

## 8. Scene Intelligence Data Model

이 절은 conceptual model이다. exact table, column, index, enum과 migration 단위는 **구현 전 확정 필요**다.

### 8.1 SceneUnit

SceneUnit은 분석을 수행하는 시간 구간 단위다. transcript block, shot interval, fixed interval, audio/visual proposal envelope 등에서 만들어질 수 있다.

- 모든 SceneUnit이 편집 후보는 아니다.
- 같은 source의 여러 분석기가 겹치는 SceneUnit을 만들 수 있다.
- SceneUnit의 boundary는 분석 입력 경계이며 최종 Scene boundary를 의미하지 않는다.
- 저장 여부, 생성 단위와 장기 보존 정책은 **TBD**다. 재생성 비용과 lineage 필요성을 구현 전에 평가한다.

### 8.2 SceneCandidate

SceneCandidate는 편집 후보로 검토할 가치가 있다고 발견된 구간이다.

개념 필드 후보:

- `id`
- `source_video_id`
- `start_seconds`, `end_seconds`
- `discovery_method`
- `confidence`
- `created_at`
- input/result validity와 lineage reference

Discovery method 후보는 `MEMO_GUIDED`, `TRANSCRIPT`, `AUDIO`, `VISUAL`, `MULTIMODAL`이다. exact enum은 Evaluation으로 조정하며 구현 전에 확정한다. Candidate에 판단 근거 전체를 JSON으로 몰아넣지 않고 SceneEvidence와 연결한다.

SceneCandidate와 향후 validated/final Scene entity를 분리할지는 **Evaluation으로 결정**한다. v2에서 필요성이 확인되기 전 final Scene entity를 미리 만들지 않는다.

### 8.3 SceneEvidence

SceneEvidence는 Candidate가 왜 생성·유지·축소·관계화됐는지 설명하는 독립 근거다.

개념 필드 후보:

- `id`, `scene_candidate_id`
- `modality`, `evidence_type`
- `start_seconds`, `end_seconds`
- `confidence`, structured `payload`
- `producer`, `producer_version`
- `source_reference`
- analysis configuration/result validity reference

Evidence type 후보:

- `USER_MEMO`, `TEMPORAL_REFERENCE`, `TRANSCRIPT`
- `AUDIO_REACTION`, `AUDIO_EVENT`
- `VISUAL_EVENT`, `SHOT_CHANGE`, `MOTION`
- `VLM_SELECTION`

Evidence는 서로 충돌할 수 있으며 충돌 자체도 정보로 보존한다. payload allowlist, 크기 제한, schema version과 민감정보 정책은 **구현 전 확정 필요**다.

### 8.4 QualityFlag

후보 예시는 `BLUR`, `SHAKE`, `DARK`, `OVEREXPOSED`, `LONG_SILENCE`, `DUPLICATE`, `ACCIDENTAL_RECORDING`, `LOW_AUDIO_QUALITY`다.

Quality는 semantic value와 분리한다. 품질 문제가 있다고 자동 삭제하지 않으며 Explicit Intent나 의미 가치가 있으면 Candidate로 유지할 수 있다. QualityFlag를 SceneEvidence subtype으로 둘지 별도 entity로 둘지는 **TBD**다.

### 8.5 SceneRelation

SceneRelation은 Candidate 간 의미 관계와 근거를 표현한다.

초기 후보:

- `SAME_EVENT`
- `CONTINUATION`
- `REACTION_TO`
- `DUPLICATE`

기존 Full Product/Data Flow 문서에는 `ALTERNATIVE`도 존재한다. `DUPLICATE`와 `ALTERNATIVE`의 의미가 겹치지 않도록 exact relation enum은 구현 전 설계·Evaluation으로 확정한다. `BEFORE`/`AFTER`처럼 timestamp로 계산 가능한 관계는 LLM 판단보다 deterministic derivation을 우선한다.

Relation에는 source/target Candidate, relation type, confidence, Evidence/producer/version과 방향성을 추적할 수 있어야 한다. exact schema는 **TBD**다.

### 8.6 EventGroup

EventGroup은 여러 SourceVideo의 관련 SceneCandidate를 같은 사건·경험 단위로 묶는다.

```text
우도 이동
├─ 선착장 설명
├─ 배 탑승
├─ 바다 B-roll
├─ 멀미 반응
└─ 우도 도착
```

파일 경계와 Event 경계는 같지 않다. v2는 우선 한 단계 EventGroup을 사용한다. Event/SubEvent 재귀 계층, immutable group versioning과 group label schema는 필요성이 확인되기 전 확정하지 않는다. label/summary는 grouping 이후 생성할 수 있지만 primary grouping criterion으로 사용하지 않는다.

## 9. Memo-guided Discovery

```text
EditMemo
→ Memo Intent
→ Temporal Search Region
→ Boundary Proposals
→ Semantic Selection
→ Deterministic Validation
→ SceneCandidate + SceneEvidence
```

### Memo Intent

MemoIntent는 `action`, `temporal_reference`, `semantic_reference`, `strength`를 구조화한다. action 후보는 `KEEP`, `REMOVE`, `SHORTEN`, `START_FROM`, `END_AT`이지만 exact enum과 parser 전략은 구현 전에 확정한다.

기존 EditMemo의 matched action/reference/trigger를 우선 입력으로 사용한다. LLM parser가 필요한 범위는 deterministic parser Baseline의 실패 분석 후 결정한다.

### Temporal Search Region

“방금”, “아까”, “여기부터” 같은 표현은 탐색 범위를 만든다. Memo timestamp를 곧바로 실제 장면 끝점으로 사용하지 않으며 Temporal Search Region도 최종 boundary가 아니다.

Search Region 정책과 최대 범위는 **Evaluation으로 결정**한다. Source duration 밖으로 나가지 않도록 Python validator가 제한한다.

### Boundary Proposals

Proposal source 후보:

- Transcript boundary
- Fixed Padding Baseline
- Shot Boundary
- Audio signal
- Visual signal
- surrounding Context

과거 audio/motion refinement 실패를 보존한다. audio activity는 semantic event boundary가 아니며 motion은 semantic relevance가 아니다. 두 signal은 truth가 아니라 proposal/evidence generator다.

### Semantic Selection and Validation

Semantic Selector에는 opaque proposal ID와 필요한 최소 context만 제공한다. LLM/VLM은 proposal ID를 선택하거나 abstain하며 자유 timestamp를 authoritative result로 반환하지 않는다. Python은 선택 ID가 manifest에 존재하는지 검증한 뒤 저장된 interval로 매핑한다.

Semantic 상태는 최소 `SELECTED`, `AMBIGUOUS`, `NO_MATCH`, `INSUFFICIENT_EVIDENCE`를 구분한다. `PROVIDER_FAILURE`, `PARSE_FAILURE`, `VALIDATION_FAILURE`는 semantic uncertainty와 분리한다.

Explicit User Intent는 Autonomous signal보다 우선한다. 단 Memo가 있다는 이유로 Autonomous Discovery를 비활성화하지 않는다.

## 10. Autonomous Discovery

```text
Memo-guided Discovery ─┐
                       ├→ Candidate Pool → Merge / Deduplication
Autonomous Discovery ──┘
```

Autonomous Discovery는 Memo가 없는 영상에서도 실행하며 Memo가 있는 영상에서도 독립적으로 수행한다. 목적은 최종 편집 여부 결정이 아니라 “검토할 가치가 있는 구간을 근거와 함께 발견”하는 것이다.

### SceneRole Scope Amendment

G4 Architecture Review 결과 authoritative SceneRole assignment는 v2에서 v3 Edit Planner로 이동한다. 이는 누락 기능을 삭제하거나 SceneRole capability 자체를 제거한 것이 아니다. `HIGHLIGHT`, `ESTABLISHING`, `B_ROLL`, `TRANSITION`처럼 최종 사용 역할은 Project theme, target duration, surrounding scenes, Episode와 placement에 따라 같은 Candidate에도 달라질 수 있기 때문이다.

v2는 `REACTION` cue, dialogue, location view, action/event cue 같은 observed semantic fact와 Memo/preference match, technical quality를 분리된 Evidence로 제공한다. v3 Scene Agent는 필요할 때 evidence-backed, optional, potentially multi-label semantic/role hint를 제공할 수 있고, v3 Edit Planner가 전체 Project/EditPlan context에서 final editorial/narrative role을 결정한다. role enum, multi-label 정책과 Planner output contract는 v3 Detailed Plan에서 결정한다.

Evidence channel:

1. Transcript / Story
2. Audio
3. Visual
4. Shot Structure
5. User Preference interface

User Preference는 v2에서 input interface만 고려할 수 있다. persistent personalization 학습과 Style Memory는 v5 범위이며 v2에서 만들지 않는다.

겹치거나 유사한 Candidate를 merge/deduplicate하되 Evidence를 잃지 않는다. temporal overlap, semantic similarity와 duplicate 관계의 결합 방식은 Baseline 비교 후 결정한다.

## 11. Cheap → Expensive Analysis

```text
100+ SourceVideo
→ Cheap Deterministic Analysis
→ SceneUnit / Proposal
→ Cheap Evidence
→ Candidate Reduction / Priority
→ Selective Expensive Analysis
→ SceneCandidate
```

Cheap analysis 후보:

- Media Probe, STT, Memo Detection
- Shot Change, Audio Activity, Silence
- Basic Quality, Keyframe, Basic Visual Change

Candidate Reduction은 삭제가 아니라 expensive analysis 우선순위 결정이다. 개념적 priority는 `HIGH_PRIORITY`, `UNCERTAIN`, `LOW_PRIORITY`이나 exact enum은 구현 전에 확정한다.

Reduction threshold, 비율과 budget은 사전에 고정하지 않고 Baseline Evaluation으로 결정한다. `USER_MEMO`가 있는 영역은 cheap heuristic만으로 제거하지 않는다. 어떤 Candidate가 deep analysis를 받지 못했는지도 추적 가능해야 한다.

Cheap Analysis는 어디를 깊게 볼지 정하고, Expensive Analysis는 선택 구간의 의미를 분석한다. 100+ Source 전체를 동일하게 LLM/VLM에 보내지 않는다.

## 12. Evidence Model

### Transcript Evidence

언어 의미, 주제, 설명, 대화, temporal expression과 narrative cue를 다룬다. Transcript segment/word timestamp와 source lineage를 유지한다.

### Audio Evidence

웃음, 비명, 박수, silence, loudness change와 speech/non-speech 같은 음향 사건을 표현한다. Audio event는 important scene과 동의어가 아니다.

### Visual Evidence

- deterministic visual signal: motion, shot change, brightness change
- semantic visual evidence: 행동, 표정, 장소, 객체, 시각적 사건

motion은 semantic relevance와 동의어가 아니다. deterministic signal과 VLM semantic result의 producer/type을 구분한다.

### Quality Evidence

Technical quality는 semantic value와 분리한다. 낮은 품질은 경고·ranking input이 될 수 있지만 자동 삭제 결정은 아니다.

`BAD_TAKE`는 editorial role이 아니라 quality judgment 또는 exclusion/preservation reason에 가깝다. 이름만으로 자동 drop하지 않으며 Explicit User Intent가 technical issue보다 우선할 수 있다.

### Memo Evidence

Memo는 Explicit User Intent다. 일반 Evidence confidence와 단순 평균하지 않으며 source EditMemo와 lineage를 보존한다. 다른 Evidence가 충돌해도 Memo를 삭제하지 않고 conflict를 기록한다.

## 13. LLM / VLM Boundary

```text
Python: proposal ID + validated interval 생성
   ↓
LLM/VLM: proposal ID 선택 또는 abstain
   ↓
Python: schema / ID / ownership / range validation
   ↓
Python: stored timestamp mapping과 persistence
```

- Deterministic code: 측정, proposal 생성, resource/interval 검증, 실행
- LLM: 언어 의미, MemoIntent 또는 transcript semantic selection이 필요한 경우
- VLM: 축소된 구간의 시각 의미

Capability 후보:

- `MemoIntentParser`
- `TranscriptSemanticSelector`
- `VisualEventAnalyzer`
- `VisualProposalSelector`
- `EventSimilarityAnalyzer`

Provider는 Gemini, Ollama/Qwen 또는 future provider로 교체 가능해야 한다. v2에서 특정 Provider를 고정하지 않는다.

결과 상태는 semantic result와 infrastructure failure를 분리한다.

- semantic: `SELECTED`, `ABSTAIN`, `AMBIGUOUS`, `INSUFFICIENT_EVIDENCE`
- infrastructure/contract: `PROVIDER_FAILURE`, `PARSE_FAILURE`, `VALIDATION_FAILURE`

VLM은 Candidate Reduction 이후 선택적으로 사용한다. frame strategy는 3-frame, 5-frame, adaptive keyframe을 비교할 수 있으며 **Evaluation으로 결정**한다. Provider별 payload, timeout, model과 token/frame budget도 **TBD**다.

External Provider에는 전체 MOV/WAV를 기본 전송하지 않는다. transcript excerpt, selected low-resolution frame/contact sheet, structured context와 opaque resource/proposal ID만 최소 전송하며 provider/model/purpose를 추적한다.

## 14. Cross-video Event Grouping

```text
SceneCandidate[]
→ Cheap Relation Filter
→ Likely Related Pairs
→ Selective Semantic Analysis
→ SceneRelation
→ EventGroup
```

Grouping evidence 후보는 Temporal, Semantic, Location, People/Object, Visual, Audio와 Narrative다. 같은 장소라는 이유만으로 같은 Event로 확정하지 않는다.

모든 Candidate pair를 LLM/VLM으로 비교하면 비용이 제곱으로 증가하므로 cheap blocking/filtering으로 likely pair를 먼저 만든다. filter key, neighbor window와 embedding 사용 여부는 **Evaluation으로 결정**한다.

`DUPLICATE`는 삭제 명령이 아니라 관계 정보다. EventGroup 생성 후에도 원 Candidate와 Evidence lineage를 유지한다. Event Grouping은 현재 Project 내부 장면 관계 분석이며 외부 knowledge/reference retrieval인 RAG와 다르다.

## 15. Tool Layer

> Agent judges. Tool executes. Python function ≠ Tool.

모든 helper를 Tool로 노출하지 않고 독립 호출 가치가 있는 bounded capability만 제공한다. v1 service를 폐기하거나 같은 기능을 중복 구현하지 않는다.

### Domain 후보

- **Media Tools**: probe, extract audio, frame/keyframe extraction
- **Transcript Tools**: transcribe, detect memo, transcript window
- **Audio Analysis Tools**: activity, silence, audio event evidence
- **Visual Analysis Tools**: shot detection, basic quality, keyframes
- **Scene Tools**: temporal region, proposal generation, deterministic merge
- **Validation Tools**: interval, proposal, ownership, resource reference

`is_good_scene()`처럼 final scene value를 판단하는 Tool은 만들지 않는다.

### Tool contract

공통 ToolResult의 개념 후보:

- `success` 또는 status
- `tool_name`, `tool_version`
- structured `data`
- warnings
- safe error code/message와 retryability hint
- timing/execution metadata

exact schema와 version negotiation은 **구현 전 확정 필요**다. raw FFmpeg stderr, secret, absolute path, 전체 prompt와 media binary를 Agent/frontend에 노출하지 않는다.

Tool은 가능한 범위에서 deterministic/idempotent하게 설계하고 request/idempotency reference를 검토한다. Business retry 횟수와 backoff는 Orchestrator/application 정책이며 Tool 내부에 숨기지 않는다.

## 16. MCP Architecture

v2 초기 구조는 하나의 **Video Editing MCP Server**다. 구현 복잡도나 독립 배포 요구가 검증되기 전에 domain별 server로 나누지 않는다.

```text
Scene Intelligence
→ MCP Client
→ Video Editing MCP Server
→ Tool Layer
→ Existing / New Services
→ FFmpeg / STT / OpenCV / selective AI Provider
```

MCP Server는 Tool을 재구현하지 않고 Tool Layer capability를 표준 contract로 노출하는 adapter/interface다.

- FastAPI: Frontend/Client ↔ Cutory Product
- MCP: Cutory AI/Application ↔ Execution Capability
- LangGraph: v3 이후 workflow orchestration 후보

금지 capability:

- `run_shell(command)`
- `run_ffmpeg(command)`
- `read_any_file(path)`

선호 capability:

- `extract_keyframes(source_video_id, bounded_config)`
- `detect_shot_changes(source_video_id, bounded_config)`
- `generate_scene_proposals(source_video_id, search_region_id)`

Input은 absolute path 대신 resource ID와 bounded interval/config를 사용한다. ownership, project scope와 duration을 adapter 또는 validator에서 확인한다.

MCP Tools는 v2 핵심이다. MCP Resources와 MCP Prompts 사용 여부, transport, auth/deployment boundary, streaming/progress는 stable MCP SDK와 실제 요구를 구현 시 확인한 뒤 결정한다. 현재 문서에서는 특정 transport를 고정하지 않는다.

## 17. Persistence / Resume / Reprocess

v1의 상태·결과 유효성 철학을 Scene work item까지 확장한다.

필요한 개념:

- Source-level persistence와 Work-item-level persistence
- logical work item과 Attempt 분리
- result persistence/reference
- input fingerprint
- producer와 producer version
- analysis configuration
- dependency lineage
- stale recovery와 safe failure

SceneUnit, SceneCandidate, SceneEvidence, SceneRelation, EventGroup은 persistent data 후보다. exact table/schema와 어떤 중간 결과까지 영속화할지는 **구현 전 확정 필요**다.

WAV, extracted frame, contact sheet와 analysis temporary file은 재생성 가능한 temporary artifact다. Project/Source/Work-item ownership과 privacy/storage 정책에 따라 cleanup하며 original source를 삭제하지 않는다.

`COMPLETED`만으로 결과를 재사용하지 않는다.

```text
Reusable Result
= COMPLETED
+ matching input fingerprint
+ compatible producer / producer version
+ compatible analysis configuration
+ required result and dependency lineage 존재
```

Invalidation 예:

- STT 변경 → 영향받는 Transcript/Memo/Transcript Evidence/Scene downstream 재계산
- Visual Analyzer 변경 → Visual Evidence와 의존 downstream만 재계산
- grouping config 변경 → Source-level Candidate를 유지하고 Relation/EventGroup부터 재계산 가능

전체 Project를 무조건 처음부터 실행하지 않는다. 외부 AI 호출 성공 직후 DB 저장 전에 process가 종료되는 경우를 고려해 idempotency reference, reconciliation 또는 safe re-execution 전략을 구현 단계에서 결정한다.

Retry 횟수, stale timeout과 자동 recovery 정책은 **TBD**이며 Evaluation과 운영 요구로 결정한다.

## 18. Evaluation Strategy

v2 평가는 discovery 단계, failure 단계와 비용을 분리해 기록한다. Ground Truth/Oracle은 product execution flow에 넣지 않는다.

### Memo-guided Discovery

- Temporal IoU, GT Coverage
- Start/End Boundary Error
- Proposal Recall
- Semantic Selection Accuracy

Proposal Generation 실패와 Semantic Selection 실패를 분리한다.

### Autonomous Discovery

- Candidate Recall, Candidate Precision
- Candidate Count, Candidate Duration

중요 장면을 놓치지 않는 Recall을 중시하되 전체 영상을 Candidate로 만드는 방식은 Precision/Count/Duration으로 드러낸다.

### Candidate Reduction

- Reduction Rate
- GT Recall After Reduction

목표 threshold는 Baseline 결과 후 결정한다.

### LLM / VLM

- Correct Selection, Wrong Selection
- Abstain, Ambiguous, Insufficient Evidence
- Provider Failure, Parse Failure, Validation Failure

Provider 장애와 semantic 판단 실패를 합치지 않는다.

### Efficiency

- LLM/VLM calls, frames sent, input tokens
- execution time, provider failures
- 측정 가능한 경우 cost

### Frame Strategy

필요성이 확인되면 3-frame, 5-frame, adaptive keyframe을 동일한 사전 기준으로 비교한다.

### Event Grouping

- Pairwise Relation Precision / Recall / F1
- Event Group Purity
- `OVER_MERGE`, `OVER_SPLIT`, `MISASSIGNMENT`

### Reliability

- Resume, Retry, Reprocess, stale recovery
- dependency invalidation, Partial Failure, duplicate processing
- temporary cleanup, MCP error propagation, provider failure isolation

정확한 목표 수치와 acceptance threshold는 각 evaluation 시작 전에 별도 설계로 고정하며 현재는 **TBD**다.

## 19. Dataset Strategy

기존 eval_01~05, fixed-window, transcript block, semantic block, audio boundary, visual motion, Gemini/Ollama VLM과 contact sheet 실험은 historical baseline/evidence로 보존한다. 다섯 sample만으로 일반화 성능을 주장하지 않는다.

### Focused Evaluation Set

- 짧고 통제된 영상
- Memo, boundary, proposal
- LLM/VLM과 frame strategy
- failure 원인을 사람이 확인 가능한 규모

### Project Evaluation Set

- 여러 SourceVideo
- Autonomous Discovery, Candidate Reduction
- Cross-video Event Grouping
- Resume와 Scale

### 규모별 목적

- Small, 10~20 Source: semantic accuracy와 failure analysis
- Medium, 30~50 Source: relation/event/reduction
- Scale, 100+ Source: state scale, resume, reliability와 비용 구조

100+ 실제 영상 전체에 초 단위 Ground Truth annotation을 요구하지 않는다. Semantic Accuracy Evaluation과 Scale/Reliability Evaluation을 분리한다. 개인정보, 촬영 동의, 외부 Provider 전송 범위와 Git 제외 정책을 dataset별로 기록한다.

## 20. Implementation Steps

각 Step은 `Design confirmation → Implementation → Test → Integration → Evaluation where applicable → Documentation → Commit` 순서를 따른다. 한 번에 v2 전체를 구현하지 않는다.

### Step 1 — Scene Intelligence Data Foundation

- conceptual model을 실제 v2 최소 schema로 확정
- SceneCandidate/Evidence/Relation/EventGroup persistence
- enum, constraint, index, lineage와 migration 설계
- model/unit/PostgreSQL migration test
- SceneUnit/QualityFlag/final Scene entity의 저장 경계 결정

### Step 2 — Tool Layer Foundation

- 기존 v1 service를 capability 기준으로 매핑
- 공통 Tool input/result/error/version contract
- resource ID validation, ownership, bounded interval
- deterministic/idempotent behavior와 execution metadata
- arbitrary shell/path capability 부재 검증

### Step 3 — Video Editing MCP Server

- 단일 MCP Server와 Tool adapter
- stable SDK/transport를 구현 시점에 검증해 선택
- capability discovery/call, schema validation, safe error propagation
- FastAPI/MCP 책임 분리와 resource scope test
- Resources/Prompts는 필요성 평가 후 포함 여부 결정

### Step 4 — Memo-guided Scene Discovery

- MemoIntent와 Temporal Search Region Baseline
- 여러 source의 boundary proposal 생성
- proposal ID semantic selector와 deterministic validator
- SceneCandidate/Evidence persistence
- proposal failure와 selection failure 분리 평가

### Step 5 — Autonomous Scene Discovery

- Transcript/Audio/Visual/Shot/Quality cheap Evidence
- Memo와 독립적인 Candidate 생성
- candidate merge/deduplication과 conflict 보존
- observed semantic fact, technical quality, candidate utility Evidence의 분리 평가
- final SceneRole assignment는 수행하지 않고 v3 Planner responsibility로 handoff

### Step 6 — Selective LLM / VLM Analysis

- Candidate Reduction과 priority
- provider-independent semantic capability
- 선택 구간의 최소 context 전송
- abstain/failure/parse/validation 상태 분리
- frame strategy와 비용/성능 비교

### Step 7 — Cross-video Event Grouping

- cheap relation filter와 likely pair generation
- selective semantic relation analysis
- SceneRelation과 한 단계 EventGroup persistence
- pairwise/group failure taxonomy와 평가

### Step 8 — Persistence / Resume Integration

- Scene work item/attempt 상태
- validity/reuse, Retry/Reprocess, stale recovery
- dependency-based targeted invalidation
- external side-effect 후 durable write 실패 대응
- 100+ synthetic/state scale와 Partial Failure 검증

### Step 9 — v2 Evaluation / Failure Analysis / Completion

- Focused/Project/Scale 평가 실행
- Memo/Autonomous/Reduction/AI/Event/Reliability 결과 분리
- regression, privacy, cost와 operational limitation 기록
- Completion Gate 판정과 v3 handoff 문서화

Step별 정확한 commit 수와 파일 배치는 해당 Step 시작 시 현재 repository 상태를 다시 확인해 결정한다.

## 21. Completion Gate

v2 완료 선언 전 최소 다음을 실제로 검증하고 근거를 남긴다.

### Data

- [ ] SceneCandidate / Evidence / Relation / EventGroup 영속화 가능
- [ ] Candidate, Evidence, Quality와 Decision 의미가 혼합되지 않음
- [ ] Observed Evidence와 Project-context editorial role이 혼합되지 않음
- [ ] source/result/producer/config lineage가 추적 가능

### Tool

- [ ] Scene Intelligence 핵심 capability가 Tool Layer로 분리됨
- [ ] 기존 v1 service를 중복 구현하지 않음
- [ ] structured ToolResult와 safe failure가 검증됨

### MCP

- [ ] Video Editing MCP Server를 통해 핵심 Tool 호출 가능
- [ ] FastAPI와 MCP 책임이 분리됨
- [ ] arbitrary shell/path 접근이 없음

### Discovery

- [ ] EditMemo에서 관련 SceneCandidate 생성 가능
- [ ] Memo 없이도 SceneCandidate 발견 가능
- [ ] Memo가 있는 Source에서도 Autonomous Discovery가 독립 실행됨
- [ ] Candidate merge/deduplication이 Evidence를 보존함

### Multimodal / AI

- [ ] Transcript / Audio / Visual Evidence가 분리되어 보존됨
- [ ] Shot Structure Evidence가 Visual Activity와 구분되어 생성·재사용됨
- [ ] Quality와 semantic value가 분리됨
- [ ] LLM/VLM이 Candidate Reduction 이후 selective하게 사용됨
- [ ] capability와 provider가 분리됨
- [ ] AI free timestamp를 authoritative interval로 사용하지 않음
- [ ] semantic/provider/parse/validation failure가 구분됨

### Scale / Event

- [ ] 100+ Source 구조에서 모든 영상을 동일하게 full VLM 분석하지 않음
- [ ] Candidate Reduction Rate와 GT Recall을 함께 평가함
- [ ] 여러 Source의 관련 Candidate를 EventGroup으로 묶을 수 있음
- [ ] pairwise relation과 grouping failure를 평가함

### Reliability

- [ ] 중단 후 valid result를 재사용하고 이어서 처리 가능
- [ ] dependency 기반 targeted invalidation 가능
- [ ] Partial Failure와 provider failure가 격리됨
- [ ] duplicate processing과 temporary cleanup이 검증됨
- [ ] v1 동작에 의도하지 않은 regression이 없음

### Evaluation / Analysis

- [ ] Memo / Autonomous / Reduction / LLM-VLM / Event 평가 결과 존재
- [ ] efficiency와 external transmission 범위가 기록됨
- [ ] 주요 failure case와 후속 개선 근거가 문서화됨
- [ ] v3 handoff contract와 남은 위험이 기록됨

“AI가 100% 정확하다”는 Completion Gate가 아니다. Scene Intelligence 구조가 실제 동작하고, 객관적으로 평가 가능하며, 실패 원인을 분리하고, 다음 Version에서 개선 가능한 상태인지가 기준이다.

## 22. Risks / Open Decisions

| 항목 | 현재 상태 | 결정 시점/근거 |
|---|---|---|
| exact DB schema/index/migration 단위 | TBD | Step 1 설계 및 query pattern |
| exact enum 전체 | TBD | Step 1 + Evaluation |
| SceneUnit 영속 범위 | TBD | 재생성 비용/lineage 검토 |
| QualityFlag 별도 entity 여부 | TBD | Step 1 |
| final Scene entity 도입 | TBD | v2 validation 결과 |
| authoritative SceneRole | v3 Edit Planner로 이동 | Project/EditPlan context-dependent editorial decision |
| optional semantic/role hint | v3 Scene Agent에서 설계 | evidence-backed, non-authoritative Planner input |
| `DUPLICATE`와 기존 `ALTERNATIVE` relation | 구현 전 확정 필요 | relation semantics/Evaluation |
| Candidate Reduction threshold/비율 | Evaluation으로 결정 | Step 6 Baseline |
| target accuracy 숫자 | TBD | evaluation protocol 사전 등록 |
| VLM frame strategy | Evaluation으로 결정 | 3/5/adaptive 비교 |
| AI Provider/model | TBD | privacy, quality, cost, latency |
| embedding/cheap relation filter 사용 | TBD | Event pair scale Evaluation |
| MCP transport/SDK version | 구현 전 확정 필요 | 당시 stable SDK/운영 요구 |
| MCP Resources 사용 | TBD | 실제 resource discovery 필요성 |
| MCP Prompts 사용 | TBD | 실제 반복 prompt contract 필요성 |
| retry 횟수/backoff | Evaluation으로 결정 | failure/reliability 결과 |
| stale timeout | Evaluation으로 결정 | workload timing |
| Event/SubEvent hierarchy | v2에서 미도입 | 한 단계 EventGroup 결과 |
| ToolResult exact fields/versioning | 구현 전 확정 필요 | Step 2 contract |
| queue/worker 도입 | TBD, v2 자동 범위 아님 | real workload/operational evidence |

주요 위험:

- Candidate Reduction이 중요한 Scene을 제거할 위험
- Explicit Intent가 generic score aggregation에 묻힐 위험
- AI selection의 provider/parse 실패를 semantic failure로 잘못 집계할 위험
- Candidate pair 증가로 Event Grouping 비용이 제곱 증가할 위험
- stale/invalid result가 downstream에서 재사용될 위험
- frame/transcript 외부 전송으로 privacy 범위가 커질 위험
- 실제 faster-whisper/VLM 병렬 workload가 v1 기본 동시성 가정과 충돌할 위험

각 위험은 숨겨진 fallback이 아니라 metric, status, warning과 Failure Analysis로 드러나야 한다.

## 23. v3 Handoff

v2는 v3에 다음 결과를 넘긴다.

- validated SceneCandidate와 modality별 SceneEvidence/QualityFlags
- SceneRelation과 EventGroup
- discovery method, confidence, conflict와 abstain/failure metadata
- Tool Layer와 Video Editing MCP capability contract
- resource ID, execution reference와 producer/version lineage
- Scene work-item Resume/Retry/Reprocess 기반
- Memo/Autonomous/Reduction/LLM-VLM/Event Evaluation 결과
- 비용·privacy·provider·scale Failure Analysis
- authoritative role로 고정되지 않은 observed semantic/technical Evidence

v3는 이 기반 위에서 Scene Agent, Style Agent, Edit Planner와 필요한 Orchestrator를 설계한다. Scene Agent는 필요하면 Evidence 기반 semantic/usage/role hint를 제공하지만 final authority를 갖지 않는다. Edit Planner는 Project instruction, Candidate/EventGroup, target duration, ResolvedStyle, surrounding scenes와 Episode placement를 반영해 SceneEditPlan의 authoritative editorial/narrative role을 결정한다. v2 문서에서 exact role enum, v3 Agent prompt, LangGraph state graph, planning schema와 Multi-Agent interaction을 미리 확정하지 않는다.

## References

- [Cutory Full Product Development Plan](../product/full-development-plan.md)
- [Cutory Version Roadmap](version-roadmap.md)
- [v1 Detailed Plan](v1-plan.md)
- [v1 Completion](v1-completion.md)
- [Full Product Architecture](../architecture/full-architecture.md)
- [Large Video Processing Architecture](../architecture/large-video-processing.md)
- [Data Flow and Lineage](../architecture/data-flow.md)
- [Tool Layer](../tools/tool-layer.md)
- [MCP Architecture](../mcp/mcp-architecture.md)
- [Privacy and License Design](../privacy/privacy-license.md)
- [Historical MVP v1 Specification](../mvp-v1-spec.md)
- [Historical Real-media Integration](../integration-eval01-v0.1.md)
- [Historical Browser E2E](../browser-e2e-v0.1.md)
- [v1 Foundation Evaluation](../../evaluation/results/cutory-v1-foundation-eval-v0.1.md)
