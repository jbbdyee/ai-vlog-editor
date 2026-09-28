# Cutory v1 — Project & Large Video Foundation

> Status: Phase C-2 — v1 Detailed Plan Documentation
>
> 이 문서는 [Cutory Version Roadmap](version-roadmap.md)의 v1을 구현하기 위한 상세 계획이다. 구현 코드, 확정 DB schema, 특정 ORM·queue·cloud vendor 선택을 포함하지 않는다.

## 1. 문서 목적과 경계

이 문서는 다음 질문에 답한다.

> v1에서 정확히 무엇을 왜 만들고, 어떤 순서로 구현하며, 어떤 조건을 만족해야 v1을 완료했다고 판단하는가?

v1은 새로운 AI 판단 기능을 추가하는 Version이 아니다. 현재 Baseline/v0에서 실제 검증한 Media Probe, Audio Extraction, STT, Memo Detection을 Project와 다수 SourceVideo 단위로 안전하게 보존·재사용할 수 있는 제품 기반으로 옮기는 Version이다.

기존 `docs/mvp-v1-spec.md`의 “MVP v1”은 단일 영상 Baseline의 역사적 명칭이다. 이 문서의 “v1”은 [Version Roadmap](version-roadmap.md)이 정의한 **Project & Large Video Foundation**을 뜻한다. 기존 명세와 Evaluation 기록은 삭제하거나 새 v1 완료 상태로 재해석하지 않는다.

## 2. 작성 시 확인한 실제 Repository 상태

기준 commit은 `621ef23` (`docs: Cutory Version Roadmap 수립`)이다.

### 2.1 현재 구조

```text
ai-vlog-editor/
├─ app/
│  ├─ main.py
│  ├─ config.py
│  ├─ routers/
│  │  └─ videos.py
│  └─ services/
├─ frontend/
│  ├─ app.py
│  └─ api_client.py
├─ tests/
├─ evaluation/
│  ├─ data/
│  ├─ results/
│  └─ experiment runners
├─ docs/
├─ requirements.txt
└─ .env.example
```

- `backend/` 디렉터리는 아직 없다.
- FastAPI backend는 루트 `app/`에 있다.
- 테스트는 루트 `tests/`에 있다.
- Streamlit은 `frontend/`에 있으며 단일 영상 Browser E2E 검증용 Prototype이다.
- PostgreSQL, ORM, migration tool, Docker 구성은 없다.
- 저장은 로컬 `uploads/`, `outputs/`를 사용하며 두 경로는 Git에서 제외된다.
- 현재 dependency에는 FastAPI, faster-whisper, Streamlit, OpenAI/Gemini 실험용 SDK 등이 포함된다.

### 2.2 현재 보존할 Baseline

제품 처리 경로에서 실제 연결·검증된 핵심은 다음과 같다.

- MOV/MP4 검증과 UUID 기반 로컬 저장
- ffprobe 기반 Media Probe
- FFmpeg 기반 16 kHz mono WAV 추출
- faster-whisper `small` 기반 STT와 segment/word timestamp
- 규칙 기반 Edit Memo detection
- 5·10·15·30초 candidate 생성
- selector contract와 fixed-window selector
- FFmpeg clip rendering
- `VideoProcessingPipeline`
- 실제 `eval_01.MOV` Pipeline Integration과 Browser E2E
- temporary WAV cleanup과 안전한 resource ID/path 검증

Transcript/Audio/Visual/VLM selector와 refiner 관련 서비스 및 `evaluation/results/`는 v2의 Scene Intelligence 후보를 평가한 연구 history다. v1에서 삭제하거나 Product 기본 경로로 승격하지 않는다.

### 2.3 현재 API와 Frontend 경계

현재 FastAPI에는 다음 경계가 있다.

- `GET /health`
- `POST /videos/upload`
- `POST /videos/process`
- `GET /videos/clips/{run_id}/{clip_id}`

`/videos/process`는 업로드부터 Pipeline 완료까지 하나의 HTTP request에서 기다리는 단일 영상 Baseline이다. v1의 장시간 Project 처리 방식으로 확장하지 않으며, 새 Project flow 검증이 끝날 때까지 Regression 자산으로 보존한다.

현재 Streamlit은 위 API의 단일 영상 upload/process/download 흐름을 검증한다. Final Frontend도 Mobile App도 아니다.

## 3. v1 Goal

v1의 목표는 Cutory가 하나의 Project 안에서 100개 이상의 SourceVideo를 관리하고, 영상별 분석 상태와 결과를 지속적으로 저장하며, 중단 또는 일부 실패가 발생해도 이미 완료된 **유효한** 작업을 재사용하여 남은 처리부터 이어갈 수 있는 기반을 구축하는 것이다.

v1의 중심은 새로운 AI 기능이 아니라 다음 Version이 신뢰할 수 있는 Project/Data/Processing Foundation이다.

- v2: Scene Intelligence와 Tool/MCP
- v3: Multi-Agent와 Planning/Orchestration
- v4: Creative Editing과 Retrieval
- v5: Reviewer, Targeted Retry, Personalization
- v6: Final UX, Final Render, Short-form

## 4. v1 Scope

### 4.1 Repository Migration

Full Product target structure 방향으로 단계적으로 이동한다.

핵심 원칙은 다음과 같다.

> Move first, refactor later.

- 이동 단계와 동작 변경 단계를 분리한다.
- 한 번의 대규모 migration을 하지 않는다.
- 각 이동 후 기존 테스트를 실행해 import와 동작을 확인한다.
- Git history를 이해할 수 있는 작은 migration 단위를 선호한다.
- media probe, audio extraction, STT, memo detection, `VideoProcessingPipeline`, FastAPI Baseline, tests, evaluation assets를 보존한다.
- 기존 `/videos/process`를 즉시 삭제하거나 Project API로 위장하지 않는다.
- 실제 기능이 생기기 전 `agents/`, `orchestrator/`, `mcp/`, `retrieval/` 빈 구조를 만들지 않는다.

초기 migration 대상은 현재 `app/`과 `tests/`를 target `backend/` 경계로 옮기는 것이다. `frontend/`, `evaluation/`, `docs/`는 현재 역할을 유지한다. 정확한 이동 commit 수와 import 경로는 구현 시작 시 현재 branch 상태를 다시 확인해 정한다.

### 4.2 Database Foundation

v1 Product Database는 PostgreSQL을 사용한다. 개발 환경의 기본 방향은 Local Docker PostgreSQL이다.

```text
PostgreSQL
→ structured state / metadata / relationships / result references

File or Object Storage
→ original video / binary artifacts
```

영상, WAV, frame, clip 등의 binary를 PostgreSQL column에 저장하지 않는다. DB에는 resource/storage reference와 무결성·lineage metadata를 저장한다.

Managed PostgreSQL, Supabase, production topology는 v1에서 확정하지 않는다. ORM과 migration library도 구현 단계의 별도 검토 대상으로 남긴다.

### 4.3 Core Data Model

#### Project

하나의 브이로그 편집 작업 전체를 나타내는 최상위 단위다.

v1 최소 개념:

- identity
- name
- project status
- target duration
- split policy
- project instruction
- created/updated timestamps

Full Product의 Style, Creative, Review, Personalization field를 v1 Project에 미리 넣지 않는다.

#### SourceVideo

Project에 속하는 각각의 원본 영상이다.

v1 최소 개념:

- identity
- project relation
- original filename
- storage/resource reference
- media metadata
- processing status 또는 집계 가능한 상태
- stable source identity/fingerprint reference
- created/updated timestamps

#### ProcessingStage

SourceVideo의 처리 단계별 실행 상태와 시도를 나타낸다.

```text
PROBE
  ↓
AUDIO_EXTRACTION
  ↓
STT
  ↓
MEMO_DETECTION
```

상태의 기본 방향은 다음과 같다.

- `PENDING`
- `RUNNING`
- `COMPLETED`
- `FAILED`
- `SKIPPED`

정확한 DB enum과 schema는 구현 단계에서 확정한다. Full Design의 `ANALYZING`/`ANALYZED` 표현과 충돌하지 않도록 Project/Source 집계 상태와 Stage 실행 상태를 구분한다.

#### Transcript와 EditMemo

- `Transcript`: STT의 구조화된 결과
- `EditMemo`: Transcript에서 탐지된 촬영 중 편집 메모

`ProcessingStage`는 실행 상태이고 `Transcript`/`EditMemo`는 실행 결과다. 완료 상태와 결과 entity를 하나의 row나 개념으로 합치지 않는다.

## 5. Source Identity와 Result Validity

SourceVideo에는 stable identity/fingerprint 개념이 필요하다.

목적:

- 동일 Source 식별
- input 변경 감지
- 중복 등록 판단의 근거
- resume 시 기존 결과가 현재 input의 것인지 확인

SHA-256 전체 파일 hash, 부분 hash, 크기·metadata 조합 등 정확한 알고리즘은 구현 전에 비용과 충돌 가능성을 평가해 결정한다.

`Stage.status == COMPLETED`만으로 결과를 재사용하지 않는다. 재사용에는 최소 다음 조건이 필요하다.

- input identity/fingerprint가 유효하게 동일함
- 필요한 output/result가 실제로 존재함
- config/model/tool version이 호환됨
- result 또는 artifact가 손상되지 않았음
- upstream dependency 결과가 여전히 유효함

필요한 traceability metadata 후보:

- input fingerprint/reference
- stage config version
- model/tool version
- output/result version
- artifact integrity metadata
- execution attempt와 timestamps

어떤 metadata를 필수 column으로 둘지는 schema 설계에서 확정한다.

## 6. Processing State, Resume, Retry, Reprocess

세 동작을 명확히 구분한다.

- **Resume**: 중단된 Project 실행을 이어서 수행한다.
- **Retry**: 실패한 Stage를 다시 실행한다.
- **Reprocess**: 성공했던 Stage도 input/config/version 변화나 사용자 요청 때문에 다시 실행한다.

### 6.1 Resume 기본 규칙

```text
COMPLETED + valid result
→ reuse

PENDING
→ execute

FAILED + retry allowed
→ retry

stale RUNNING
→ recover
→ retry 가능한 상태로 전환

SKIPPED
→ 명시된 정책에 따라 계속 skip하거나 재평가
```

DB에 `RUNNING`이라고 기록됐다는 이유만으로 실제 작업이 살아 있다고 가정하지 않는다. process crash, host restart, timeout 이후 stale RUNNING을 식별하고 복구할 수 있어야 한다.

Retry는 bounded retry를 사용한다. 정확한 횟수와 backoff는 v1 Evaluation 근거로 결정하며 Full Product Reviewer의 retry 기본값을 그대로 가져오지 않는다. 각 attempt의 시작·종료·실패 분류와 안전한 오류 정보를 추적할 수 있어야 한다.

### 6.2 상태 전이 안전성

- 허용되지 않은 상태 전이를 거부한다.
- 결과 publish와 `COMPLETED` 기록 사이의 불일치가 생겨도 복구할 수 있게 한다.
- 동일 Stage의 중복 실행 또는 중복 publish를 식별할 수 있어야 한다.
- 실패가 기존의 유효한 성공 결과를 무조건 덮어쓰지 않게 한다.
- 재시작 후 어떤 실행을 재사용·재시도했는지 설명할 수 있어야 한다.

## 7. Stage Dependency와 Invalidation

v1 dependency는 다음과 같다.

```text
PROBE
  ↓
AUDIO_EXTRACTION
  ↓
STT
  ↓
MEMO_DETECTION
```

upstream 결과가 invalidated되면 그 결과에 의존하는 downstream 결과를 그대로 재사용하지 않는다.

예:

```text
STT invalidated
→ MEMO_DETECTION invalidated

AUDIO_EXTRACTION config changed
→ AUDIO_EXTRACTION, STT, MEMO_DETECTION 재평가

Source fingerprint changed
→ 해당 Source의 모든 Stage 재평가
```

정확한 dependency engine이나 invalidation 저장 방식은 아직 확정하지 않는다. v1 요구사항은 dependency가 명시되고 downstream invalidation이 누락되지 않는 것이다.

## 8. Partial Failure와 Project 상태

한 SourceVideo의 실패가 Project 전체를 즉시 `FAILED`로 만들지 않는다.

```text
127 Source
├─ 126 Source 성공
└─ 1 Source 실패

→ 성공 결과 보존
→ 실패 Source와 실패 Stage 식별
→ 실패 Stage부터 재처리 가능
→ Project는 warning/degraded completion 표현 가능
```

정확한 Project status enum은 schema 구현 전에 확정한다. 다만 다음 원칙을 지킨다.

- Project status와 Source/Stage status가 모순되지 않아야 한다.
- 가능하면 Project 상태는 Source/Stage 상태에서 일관되게 파생하거나 검증 가능해야 한다.
- 실패한 Source의 수, 영향, retry 가능 여부를 집계할 수 있어야 한다.
- 성공한 Source 결과는 다른 Source 실패 때문에 폐기하지 않는다.

## 9. 100+ Source Ingestion과 Processing

Upload/Ingestion과 Analysis를 개념적으로 분리한다.

```text
Project 생성
  ↓
다수 Source 등록
  ↓
Source별 original 저장과 identity 기록
  ↓
READY
  ↓
처리 가능한 Source부터 분석
```

모든 Source upload가 끝날 때까지 분석 시작을 무조건 기다리지 않는다. 등록과 저장이 끝난 Source는 정책과 resource budget이 허용하면 분석 대상으로 전환할 수 있다.

v1 Source Analysis 결과:

```text
SourceVideo
├─ Media Metadata
├─ Transcript
├─ EditMemo
└─ ProcessingStage state/history
```

v1에서는 Autonomous Scene Discovery, VLM Scene Analysis, Cross-video Event Grouping, Narrative Planning을 수행하지 않는다.

## 10. Processing Concurrency

100+ Source를 무제한 동시 처리하지 않는다. v1은 bounded processing과 bounded concurrency를 지원할 수 있는 상태·application 경계를 만든다.

- CPU, memory, disk I/O와 faster-whisper model 사용량을 제한할 수 있어야 한다.
- dependency가 충족된 Stage만 실행 후보가 된다.
- 동시 처리 수를 설정 가능하게 둘 수 있지만 정확히 `N`개로 문서에서 고정하지 않는다.
- 실제 Evaluation에서 latency, resource usage, failure를 관찰한 뒤 기본값을 결정한다.
- Redis/Celery 등 distributed queue를 선제적으로 도입하지 않는다.
- PostgreSQL 기반 Processing State와 단일 개발 환경의 resume correctness를 먼저 검증한다.

후속 Evaluation에서 별도 worker/queue 필요성이 확인되면 구현 선택을 다시 검토한다.

## 11. Storage와 Artifact Lifecycle

### 11.1 Original Source

사용자가 제공한 원본 영상이다. Project가 존재하는 동안 후속 Scene Analysis, Revision, Final Render를 위해 필요할 수 있다. temporary artifact와 같은 cleanup 정책을 적용하지 않는다.

### 11.2 Temporary Artifact

예:

- extracted WAV
- temporary frame
- contact sheet
- proxy
- intermediate clip
- temporary analysis file

Project/Source/Stage 단위로 소유권을 식별할 수 있는 workspace를 사용한다. 성공, 실패, 취소, crash 후 recovery 각각에서 cleanup 대상과 보존 대상을 구분한다.

정확한 retention 시간은 현재 확정하지 않는다. 최소한 다음을 검증한다.

- 다른 Project/Source의 artifact를 삭제하지 않음
- 성공한 output/reference를 cleanup하지 않음
- 실패 중 생성된 partial artifact를 식별 가능
- retry가 이전 partial artifact를 유효 결과로 오인하지 않음
- source와 temporary artifact lifecycle이 분리됨

DB에는 binary 대신 resource/storage reference를 저장한다.

## 12. API와 Application Boundary

제품 중심 단위를 Single Video에서 Project로 전환한다.

```text
Frontend or Mobile Client
  ↓
FastAPI
  ↓
Application Layer
  ↓
Service / Repository
  ↓
PostgreSQL / Storage
```

책임:

- **FastAPI**: HTTP, request validation, response DTO
- **Application**: use case, Project processing flow, coordination, transaction boundary
- **Service**: Media Probe, Audio Extraction, STT, Memo Detection
- **Repository**: structured persistence contract
- **Storage**: original과 binary artifact 관리

Router에서 STT, FFmpeg, DB orchestration을 직접 수행하지 않는다. application use case가 service/repository/storage를 조정한다.

v1 Project API는 다음 capability를 지원해야 하지만 정확한 endpoint와 DTO는 API 설계 단계에서 확정한다.

- Project 생성·조회
- 다수 Source 등록 결과 조회
- processing 시작 또는 요청
- Project/Source/Stage 상태 조회
- 실패와 retry 가능 상태 조회
- 허용된 retry/reprocess 요청

## 13. Long-running Processing

100+ Source 처리를 하나의 HTTP request가 끝날 때까지 기다리게 하지 않는다.

```text
Project 생성 → 빠른 응답
Source 등록 → 등록 결과 응답
Processing 시작 → processing state 응답
Client → Project processing state 확인
```

Polling, SSE, WebSocket, worker, queue 중 무엇을 사용할지는 필요성과 Evaluation 없이 확정하지 않는다.

기존 `/videos/process`는 즉시 삭제하지 않는다. 단일 영상 Baseline과 Regression 자산으로 보존하고 새 Project 기반 flow와 공존시킨다. 새 flow가 기존 실제 media scenario를 대체 검증한 뒤에만 deprecation 여부를 별도로 결정한다.

## 14. Mobile-first Product Direction

Cutory의 최종 사용자 경험은 Desktop 중심보다 Mobile-first 방향을 우선한다.

미래 요구:

- iOS/Android media picker
- 대량 영상 선택
- background/resumable upload
- app background 또는 lock 상태
- processing progress
- notification
- final video save/share

v1은 Mobile App을 구현하지 않는다. v1의 책임은 미래 Mobile Client가 붙어도 backend/application 구조를 다시 설계하지 않도록 다음 경계를 만드는 것이다.

- client-independent Project/Source identity
- long-running processing state 조회
- request lifecycle과 분리된 처리 상태
- local path를 노출하지 않는 resource reference
- 재시도 가능한 ingestion/processing 의미
- aggregate progress와 partial failure 표현

현재 Streamlit은 Prototype/E2E Validation UI로 유지한다. Final Frontend로 확장하거나 Mobile-first 요구를 Streamlit 기술 선택으로 고정하지 않는다.

## 15. Test와 Evaluation 전략

v1 Evaluation은 세 계층을 구분한다.

### 15.1 Unit Test

- Project persistence
- Source registration
- Stage state transition
- invalid transition 거부
- valid completed result reuse
- failed Stage retry
- stale RUNNING recovery
- reprocess와 invalidation
- downstream invalidation
- Project/Source 상태 집계
- artifact ownership과 cleanup decision

### 15.2 Integration Test

소규모 실제 media를 사용한다.

```text
Project
→ 실제 Source 등록
→ Probe
→ Audio Extraction
→ STT
→ Memo Detection
→ persistence
→ process restart
→ resume
```

기존 `eval_01.MOV`와 검증된 Baseline scenario를 가능한 범위에서 재사용한다. Ground Truth와 Oracle은 product execution flow에 넣지 않는다.

### 15.3 Large Project / Scale Evaluation

100~500개의 synthetic Source metadata/state로 다음을 검증한다.

- Project orchestration
- persistence와 상태 집계
- resume/retry/reprocess
- partial failure
- invalidation
- duplicate processing
- bounded processing 구조

실제 영상 100개에 STT를 전부 수행하는 것을 v1 완료 조건으로 두지 않는다.

- **Scale Test**: synthetic metadata/state로 100+ 구조 검증
- **Real Media Integration**: 소규모 실제 영상으로 FFmpeg/STT/Memo/Persistence 검증

두 결과를 분리해 기록하며 실제 영상 100개를 처리했다고 과장하지 않는다.

## 16. Failure Scenarios

### 16.1 Crash / Resume

일부 Source가 `COMPLETED`, 일부가 stale `RUNNING`, 일부가 `PENDING`인 시점에 실행을 중단한다. 재시작 후:

- 유효한 완료 Stage는 중복 처리하지 않음
- stale RUNNING을 복구함
- 남은 Stage부터 계속함
- invalid result는 완료 상태여도 재사용하지 않음

### 16.2 Partial Failure

정상 Source와 corrupt/unreadable Source를 함께 등록한다.

- 정상 Source 결과 보존
- 실패 Source와 Stage 격리
- Project 집계에 warning/degraded 상태 반영
- 실패 Stage부터 retry 가능

### 16.3 Duplicate Processing

완료된 Project/Source를 다시 resume한다.

- 유효한 `COMPLETED` Stage를 불필요하게 재실행하지 않음
- 동시 또는 반복 요청이 중복 결과 publish를 만들지 않음

### 16.4 Cleanup

- 성공 시 temporary artifact 정책 준수
- 실패 시 partial artifact 정리 또는 복구 가능 상태 기록
- original source와 유효한 결과 보존
- 다른 Source workspace에 영향 없음

## 17. v1 Evaluation Metrics

v1은 AI 품질 Version이 아니므로 Scene IoU를 핵심 완료 지표로 사용하지 않는다.

최소 관찰 대상:

- Project creation success
- Source registration success
- Stage completion
- Resume correctness
- Retry correctness
- stale RUNNING recovery
- Duplicate processing count
- Failed Source isolation
- DB consistency
- Temporary artifact cleanup
- processing latency

특히 `Duplicate processing count`를 중요하게 관찰한다. 정확한 threshold와 workload는 Evaluation 설계에서 실행 전에 확정한다.

## 18. Implementation Order

### 1. Repository Migration

- 현재 구조와 import/test baseline 고정
- `Move first, refactor later`
- backend target 경계로 작은 단위 이동
- 이동마다 기존 테스트와 Baseline regression 확인

### 2. PostgreSQL Foundation

- Local Docker PostgreSQL 개발 경계
- connection/configuration와 migration 실행 기반
- binary와 structured state 분리 확인

### 3. Project Data Model

- Project, SourceVideo, ProcessingStage
- Transcript, EditMemo persistence
- 상태 전이와 lineage 최소 계약

### 4. Storage / Ingestion

- Project/Source resource identity
- original storage reference
- source fingerprint 결정 및 검증
- multi-source 등록과 ownership

### 5. Existing Media Pipeline Integration

- 기존 Probe/Audio/STT/Memo service 보존
- Project/Source application flow에서 호출
- 기존 `/videos/process` Regression 유지

### 6. Processing State / Resume

- result validity
- completed reuse
- failed retry
- stale RUNNING recovery
- reprocess와 downstream invalidation

### 7. Multi-Source Processing

- source-level partial failure
- bounded processing 구조
- project progress aggregation
- artifact lifecycle

### 8. Project API

- Project/Source/Processing capability를 HTTP DTO로 노출
- long-running request와 상태 조회 분리
- router와 application orchestration 분리

### 9. Scale / Failure Evaluation

- 100+ synthetic Source
- 소규모 real media integration
- crash/resume, duplicate, corrupt source, cleanup

### 10. Failure Analysis / Documentation

- 사전 기준 대비 결과 기록
- 실패 유형과 운영 제약 기록
- v2가 재사용할 contract와 남은 위험 명시

각 단계는 별도 검증 가능한 작은 변경으로 진행한다. migration과 기능 추가, schema와 대량 orchestration을 한 commit에 섞지 않는다.

## 19. v1 Completion Gate

다음 항목을 모두 충족하고 Integration/Evaluation/Failure Analysis가 문서화되어야 v1을 완료로 판단한다.

- [ ] Target backend structure migration
- [ ] Existing Baseline regression preserved
- [ ] PostgreSQL persistence
- [ ] Project create/read
- [ ] Multiple SourceVideo registration
- [ ] ProcessingStage persistence
- [ ] Real Media Probe
- [ ] Real Audio Extraction
- [ ] Real STT
- [ ] Real Memo Detection
- [ ] Transcript persistence
- [ ] EditMemo persistence
- [ ] Valid Completed Stage reuse
- [ ] Failed Stage retry
- [ ] Stale RUNNING recovery
- [ ] Reprocess path
- [ ] Downstream invalidation
- [ ] Source-level Partial Failure
- [ ] Project/Source/Stage state consistency
- [ ] Original/Temporary lifecycle separation
- [ ] Temporary cleanup on success/failure
- [ ] 100+ synthetic Source scale scenario
- [ ] Small real-media integration scenario
- [ ] Crash/resume scenario
- [ ] Duplicate processing verification
- [ ] Bounded processing structure
- [ ] Project-based FastAPI flow
- [ ] Existing `/videos/process` regression decision documented
- [ ] Evaluation documentation
- [ ] v1 Failure Analysis
- [ ] Privacy/local-first review
- [ ] v2 handoff contract documented

단위 테스트 통과만으로 이 Gate를 충족한 것으로 보지 않는다. 실제 PostgreSQL persistence, process restart, real media와 100+ synthetic state scenario를 분리해 검증해야 한다.

## 20. Explicit Non-goals

다음은 v1에서 구현하지 않는다.

- Scene Agent
- Autonomous Scene Discovery
- Full VLM Scene Selection
- Cross-video Event Grouping
- MCP Server
- LangGraph Orchestrator
- Multi-Agent workflow
- RAG
- Creative Agent
- Caption/BGM/Color full editing
- Reviewer Agent
- long-term personalization memory
- Final Mobile App
- Short-form
- Production Deployment

이는 Full Product에서 삭제한 기능이 아니다. [Version Roadmap](version-roadmap.md)에 따라 후속 Version에서 구현한다.

## 21. Intentionally Unresolved

다음은 이 계획에서 임의로 확정하지 않는다.

- exact DB schema
- exact SQL column types
- ORM
- migration library
- exact source fingerprint algorithm
- exact duplicate policy
- exact concurrency number
- exact retry count와 backoff
- exact Project status enum
- exact retention duration
- Polling vs SSE vs WebSocket
- queue/worker technology
- Managed DB vendor
- Object Storage vendor
- Production deployment topology
- Final Mobile framework
- iOS vs Android implementation priority

다음 세 방향은 v1 설계 결정으로 유지한다.

- PostgreSQL Product Database
- Local Docker PostgreSQL 개발 방향
- Mobile-first 최종 제품 방향

## 22. Privacy와 Data Handling Gate

[Privacy and License Design](../privacy/privacy-license.md)의 다음 원칙을 v1부터 적용한다.

- 원본 영상·음성 local-first
- 외부 Provider로 전체 MOV/WAV를 기본 전송하지 않음
- temporary artifact는 temporary-by-default
- DB log에 binary, API key, auth header, 전체 prompt를 저장하지 않음
- Project-derived Transcript/EditMemo와 resource lineage 식별 가능
- local absolute path를 client 응답에 직접 노출하지 않음
- Project 삭제와 resource cleanup을 구현할 때 파생 데이터 식별이 가능하도록 설계

정확한 retention/deletion/export 법적 정책은 미결정이지만, 나중에 삭제 범위를 식별할 수 없는 구조를 만들지 않는다.

## 23. v2 Handoff

v1은 다음 결과를 v2에 넘긴다.

- Project와 SourceVideo identity
- 100+ Source의 저장된 analysis state
- 유효성 검증 가능한 MediaInfo, Transcript, EditMemo
- ProcessingStage history와 retry/resume/invalidation 근거
- source/storage/resource reference와 temporary workspace ownership
- source-level partial failure와 Project progress aggregation
- v1 Scale/Integration Evaluation
- v1 Failure Analysis

v2는 이 기반 위에서 SceneCandidate/Evidence, candidate reduction, VLM deep analysis, Cross-video Event Grouping, Tool/MCP 경계를 구현한다.

## 24. Full Design / Roadmap Consistency Review

### 24.1 일치하는 부분

- Full Product의 100+ Source와 incremental/resumable processing을 v1 기반으로 배치한다.
- Project/Data foundation을 먼저 만들어 v2 Scene Intelligence와 v3 Multi-Agent가 신뢰할 상태를 제공한다.
- 기존 Baseline과 Evaluation history를 보존한다.
- Binary/DB/temporary workspace 책임을 분리한다.
- partial failure, bounded retry, source-level isolation 원칙을 유지한다.
- local-first와 external-provider 최소 전송 원칙을 유지한다.
- Streamlit을 Prototype으로 유지하고 Final Frontend로 간주하지 않는다.
- v2 Scene Intelligence, v3 Multi-Agent, v4 RAG/Creative, v5 Reviewer/Memory, v6 Short-form을 침범하지 않는다.

### 24.2 구현 전에 다시 확인할 경계

- `docs/mvp-v1-spec.md`의 역사적 “MVP v1”과 Version Roadmap의 새 “v1” 명칭을 개발/issue/commit에서 구분해야 한다.
- Full Architecture의 상태 예시 `ANALYZING`/`ANALYZED`와 v1 Stage 상태 `RUNNING`/`COMPLETED`의 계층을 schema 설계에서 명확히 해야 한다.
- Full Product 문서의 Agent/Reviewer retry 기본값을 v1 Stage retry 횟수로 자동 적용하지 않는다.
- 현재 `AGENTS.md`는 `docs/mvp-v1-spec.md`를 현재 범위로 지정하므로 v1 구현 시작 전에 Version Roadmap 기준으로 작업 지침을 갱신할지 별도 검수해야 한다.

## 25. 참고 문서

- [Full Product Development Plan](../product/full-development-plan.md)
- [Full Product Architecture](../architecture/full-architecture.md)
- [Large Video Processing Architecture](../architecture/large-video-processing.md)
- [Data Flow and Lineage](../architecture/data-flow.md)
- [Database and Memory Design](../database/database-memory.md)
- [Privacy and License Design](../privacy/privacy-license.md)
- [Frontend UX](../frontend/frontend-ux.md)
- [Version Roadmap](version-roadmap.md)
- [MVP v1 Specification — Baseline/v0 history](../mvp-v1-spec.md)
- [Pipeline Integration Verification](../integration-eval01-v0.1.md)
- [Browser E2E Verification](../browser-e2e-v0.1.md)
- [Evaluation Dataset](../../evaluation/README.md)
