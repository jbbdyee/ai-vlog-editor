# 🎬 AI Vlog Editor

> Working product name: **Cutory** (WIP)
>
> 사용자의 편집 의도는 남기고, 반복적인 영상 편집 노동은 AI에게 맡깁니다.

Cutory는 여러 촬영 영상에서 장면과 사건을 찾고, 사용자 의도·취향·현재 요청을 반영해 한 편의 브이로그를 만드는 **멀티 에이전트 AI 편집기**를 목표로 합니다. 사용자는 창작 방향과 결과를 확인하고, AI는 반복적인 탐색·구성·편집 작업을 돕습니다.

## 제품 목표

- 음성 메모가 없어도 영상에서 의미 있는 장면을 찾고, 메모가 있으면 편집 의도의 단서로 활용합니다.
- 장면을 이야기 흐름에 맞게 구성하고 자막·음악·색감 등의 편집안을 계획합니다.
- 미리보기와 사용자 검토를 거쳐 완성 영상을 만드는 흐름을 지향합니다.

이는 [최종 제품 기획](docs/product/full-development-plan.md)의 방향이며, 아래의 현재 구현 범위와 구분됩니다.

## 현재 구현 범위

- **v1 완료:** 여러 원본 영상의 등록·처리 상태 저장, 재개와 부분 실패 처리를 위한 기반을 만들었습니다.
- **v2 진행 중:** 장면 후보 분석과 편집 계획, 선택한 장면을 MP4로 결합하는 백엔드 기능을 단계적으로 구현했습니다. 실제 영상 평가와 사용자 화면 연결 등은 계속 진행 중입니다.
- **아직 개발 중:** AI가 스토리·스타일을 계획하는 멀티 에이전트 편집과 최종 사용자 경험은 완성되지 않았습니다.

자세한 완료 범위와 한계는 아래 [Current Repository Status](#current-repository-status) 및 [Version Roadmap](docs/roadmap/version-roadmap.md)을 참고해 주세요.

## 초기 실험: 음성 편집 메모

초기 Baseline에서는 촬영 중 남긴 “AI야 방금 장면 꼭 살려줘” 같은 말을 찾고, 해당 시점 주변의 장면을 후보로 골라 MP4 클립으로 추출했습니다. 음성 메모는 최종 제품의 **선택 기능**이며, 이 실험이 제품 전체를 뜻하지는 않습니다.

```text
Video → Audio → STT → Timestamp → Edit Memo → Candidate Interval → Evaluation → FFmpeg → MP4
```

기능은 `Baseline → Evaluation → Failure Analysis → Improvement` 순서로 검증하며 확장합니다.

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
- [Current Work Index](TODO.md)

## Current Repository Status

MVP-06C-2B의 Windows 합성 미디어 하드 자막 렌더 경로는 [검증 기록](docs/handoff/mvp-06c-2b-windows-validation.md)에 정리했다. 로컬 `CUTORY_SUBTITLE_FONT_PATH`에 검증된 NotoSansCJKkr-Regular.otf 경로를 설정하면 기존 `final.mp4`와 `final.srt` 옆에 별도의 `final-subtitled.mp4`를 만든다. MVP-06D에서는 기존 기본 MP4 다운로드를 유지하고, 하드 자막 MP4의 상태 조회·다운로드 및 Streamlit 선택 UI를 추가했다. [검증 범위](docs/handoff/mvp-06d-subtitle-download-validation.md)를 참고한다. MVP-07A에서는 [P1-S01 실제 영상 한 건의 API 수준 통합 검증](docs/handoff/mvp-07a-real-video-validation.md)으로 MP4·SRT·한국어 하드 자막 MP4 생성과 두 MP4의 다운로드를 확인했다. 선택 후보는 자동 추천이 아니라 촬영자 확인 구간과의 겹침을 기준으로 검증 스크립트가 고른 것이다. Streamlit 실제 클릭 조작과 추천 품질의 정량 평가는 미완료이며 GT도 동결되지 않았다. [MVP-07B 원인 분석](docs/handoff/mvp-07b-root-cause-analysis.md) 이후 [MVP-07C 검증](docs/handoff/mvp-07c-stt-dependency-validation.md)에서 `av==18.1.0`을 명시하고 깨끗한 Windows 환경의 실제 WAV·P1-S01 소스 처리로 STT를 확인했다. 제품 STT 코드는 변경하지 않았다.

아래는 구현 단계별 기록입니다. 각 기능의 검증 범위와 남은 한계는 해당 설명을 기준으로 확인해 주세요.

> Previous: **v1 — Project & Large Video Foundation: Completed**
>
> Current: **v2 Structural/Foundation Implementation Complete — Gap Closure in progress; G5-B5 media-free Validator implemented**
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
- [x] Cutory v2 Shot Structure deterministic baseline — FFmpeg `scdet` 기반 hard-cut 구조, bounded Shot manifest, 독립 `SHOT_EVIDENCE` Work와 Candidate 보조 Evidence 구현. actual synthetic 4-fixture와 PostgreSQL 17.11/Alembic 검증 완료
- [x] Cutory v2 G4-C SceneRole scope amendment — v2는 observed Evidence를 소유하고, v3 Scene Agent hint는 optional/non-authoritative이며, v3 Edit Planner가 SceneEditPlan의 final editorial/narrative role을 결정하도록 Source of Truth 정리
- [x] Cutory v2 G5-A focused evaluation GT design review 및 G5-B1 [dataset schema/annotation guide](evaluation/datasets/cutory-v2-focused-eval-v0.1/README.md) — Memo, Autonomous, VLM, Event의 평가 규칙과 privacy/freeze 정책을 고정. 이후 P1-S01 실제 영상 API 통합 검증은 수행했으나 동결 GT와 semantic 품질 평가 결과는 아직 없음
- [x] Cutory v2 G5-B2 [controlled recording scenarios](evaluation/datasets/cutory-v2-focused-eval-v0.1/manifests/README.md) — 3 Project/18 Source 등록(촬영 계획 17개, 1개 byte copy), 촬영 지시·Event intent·coverage·privacy를 모델 실행 전에 사전 등록. 이 단계에서는 촬영·GT 주석·평가를 실행하지 않음
- [x] Cutory v2 G5-B5 [GT Validator](evaluation/validate_focused_gt.py) — Draft 2020-12 Schema와 구간·ID·관계·그룹 참조를 영상 없이 검증. 현재 P1 미동결 초안 8개는 draft PASS, 전체 freeze-ready는 GT·Proposal 참조 미완료로 PENDING

Scene Data Foundation은 discovery 결과를 저장하기 위한 persistence 기반을 제공한다. 일반 `SceneUnit`, 별도 `QualityFlag`, `SceneRole`, CandidatePriority와 Final Scene table은 만들지 않았다. 이는 SceneRole capability 삭제가 아니다. v2는 observed Evidence를 제공하고, v3 Scene Agent는 필요할 때 optional role/usage hint를 제공하며, v3 Edit Planner가 Project/EditPlan context에서 final role을 결정한다. Scene 전용 실행 상태는 완료 결과의 input/config/producer와 Work별 result contract를 검사하고, result-link가 가리키는 최신 유효 Candidate만 Event snapshot에 포함한다.

현재 v2 전체는 아직 Completed가 아니다. Gap Closure 상태는 G1 actual Text LLM evaluation 미실행(기존 `BLOCKED_NO_API_KEY` 기록의 현재 실행 조건은 재확인 필요), G2/G3 pending, G4-A/B/C 완료, G5-A review와 G5-B1 schema/guide·G5-B2 recording manifest·G5-B5 Validator 완료다. G5-B3 촬영·G5-B4 GT 주석은 일부 P1 초안이 있으나 GT는 freeze되지 않았다. 이 Windows checkout에는 실제 촬영 영상이 있으며 P1-S01 한 건의 제한된 API 통합 검증을 수행했다.

Internal Tool Layer는 기존 `probe_media`, `extract_audio`, `transcribe_audio`, `detect_edit_memos`를 다시 구현하지 않고 안전한 resource resolution과 구조화 결과 경계로 감싼다. Source Tool 입력은 UUID이며 raw path나 storage reference를 받지 않는다. 추출 WAV는 실제 workspace registry가 opaque artifact ID로 관리하고 Tool 결과에 경로를 노출하지 않는다. `ToolResult`는 한 번의 in-process 호출 결과이며 durable `SceneAnalysisWorkItem`/`SceneAnalysisAttempt`와 별개다. Tool 내부 business retry는 구현하지 않았다.

Video Editing MCP Server는 `python -m backend.app.mcp.server`로 실행하는 local-first stdio process다. 현재 공개 Tool은 `probe_video` 하나뿐이며 MCP adapter가 Internal Tool을 정확히 한 번 호출한다. MCP 응답은 allowlist media metadata, safe error와 실행 metadata만 포함하고 raw path·storage reference·stderr·credential을 제외한다. Resources/Prompts, extract_audio/STT/Memo 공개, Streamable HTTP와 Scene/Agent 기능은 아직 구현하지 않았다.

Memo-guided Scene Discovery는 persisted `EditMemo` 하나를 `MemoIntent → TemporalSearchRegion → SceneProposal[] → deterministic selection/abstain → validator`로 처리한다. production 지원은 `KEEP`과 `JUST_NOW`/`EARLIER`, same-source search로 제한한다. 선택 성공 시 기존 `SceneCandidate(MEMO_GUIDED)`와 `USER_MEMO`, `TEMPORAL_REFERENCE`, `TRANSCRIPT_MATCH`, `SEMANTIC_SELECTION` Evidence를 저장하며, 의미가 불명확하면 WorkItem/Attempt를 정상 완료하고 Candidate를 만들지 않는다. 이 경로 자체에는 LLM/VLM이나 audio/visual refinement가 없고 새 MCP Tool도 추가하지 않았다. 로컬 eval 5개가 없어 실제 historical 평가는 실행하지 않았고 synthetic focused 결과는 `evaluation/results/memo-guided-baseline-v0.1.md`에 기록한다.

Autonomous Scene Discovery는 EditMemo와 독립적으로 persisted Transcript 구조, PCM RMS activity/silence, FFmpeg grayscale frame difference/static interval을 분석한다. 단일 speech·audio·motion·quality signal은 Candidate로 승격하지 않고 reaction+audio, transcript structure+audio 또는 audio+visual이 같은 구간에서 겹치는 명시적 rule만 사용한다. Candidate confidence는 null이며 exact interval만 재사용한다. Memo Candidate와 정확히 겹치면 기존 Candidate의 provenance를 유지한 채 Autonomous Evidence를 추가하고, high-overlap 구간은 병합하지 않는다. modality partial failure는 별도 WorkItem/Attempt에 남기고 가능한 signal로 정상 completion할 수 있다. LLM/VLM 호출은 0이다. 과거 합성 Baseline 결과는 `evaluation/results/autonomous-baseline-v0.1.md`, 이후 P1-S01 실제 영상 한 건의 후보 생성 결과는 [MVP-07A 검증](docs/handoff/mvp-07a-real-video-validation.md)에 기록했다. GT가 동결되지 않아 semantic accuracy의 정량 평가는 미완료다.

Shot Structure baseline은 위 grayscale frame-difference activity와 별도다. FFmpeg `scdet`가 보고한 hard/jump-cut timestamp를 0.001초 단위로 정규화하여 `ShotBoundary`와 source 전체를 덮는 `ShotInterval` manifest를 만든다. 결과는 독립 `SHOT_EVIDENCE` WorkItem의 bounded result reference/fingerprint로 보존하고, 실제 경계가 active Candidate interval과 겹칠 때만 `SHOT_CHANGE` 보조 Evidence를 저장한다. Shot만으로 Candidate를 생성하거나 Candidate interval을 snap하지 않으며 Promotion, SceneRole, Event 판단에도 사용하지 않는다. 같은 source/config는 재사용하고 detector 설정 변경은 Shot work만 재처리한다. 4개 actual synthetic fixture에서 GT boundary 4개를 모두 검출하고 false positive 0을 기록했지만 production vlog accuracy로 일반화하지 않는다. 상세 결과는 `evaluation/results/shot-structure-baseline-v0.1.md`에 기록한다.

Selective Text LLM 경로는 기존 Memo-guided deterministic selector가 유일한 Proposal을 선택한 경우 Provider를 호출하지 않는다. Transcript Proposal이 의미적으로 경쟁하거나 `EARLIER` 의미 참조가 해결되지 않은 경우에만 bounded Memo와 Proposal snippet을 `TranscriptProposalSelector`로 전달한다. OpenAI adapter의 기본 모델은 config로 교체 가능한 `gpt-6-luna`이고, Responses API Structured Outputs 결과는 기존 Proposal ID 또는 `AMBIGUOUS`/`NO_MATCH`/`INSUFFICIENT_EVIDENCE`만 허용한다. Python validator가 ID allowlist, schema/capability와 manifest를 다시 검증하며 timestamp는 로컬 Proposal이 계속 소유한다. Provider 실패는 별도 semantic WorkItem/Attempt에만 기록되고 기존 deterministic 결과를 삭제하지 않는다. 실제 Provider 평가는 미실행이며, 과거 키 미설정 상태에서 수행한 synthetic contract와 PostgreSQL persistence 결과는 `evaluation/results/selective-text-llm-v0.1.md`에 기록한다. 현재 키의 유효성이나 평가 실행 가능 여부는 확인하지 않았다. VLM과 새 MCP Tool은 추가하지 않았다.

Deterministic Event Grouping baseline은 Project Candidate snapshot에서 bounded transcript token, Evidence type, source ordering과 exact source identity를 explicit blocking reason으로 사용해 likely pair만 만든다. 이 신호는 relation decision이 아니며 production에서 자동 생성하는 Relation은 같은 source fingerprint와 0.001초 정규화 interval이 모두 일치하는 canonical `DUPLICATE`뿐이다. EventGroup engine은 이미 accepted된 `SAME_EVENT`만 입력으로 받고, singleton·single bridge merge·multiple current membership을 금지한다. 근거가 부족한 Candidate는 정상 unassigned로 유지한다. 600 synthetic Candidate scale은 pair reduction 구조만 검증하며 실제 semantic grouping accuracy를 의미하지 않는다. LLM/VLM 호출과 새 MCP Tool은 없다.

Scene Resume/Reprocess 통합은 `scene_analysis_work_result_candidates`로 WorkItem의 현재 Candidate 결과를 명시한다. Transcript/Audio/Visual Work는 독립 fingerprint를 사용하고 Promotion은 modality result fingerprint에 의존하므로 변경되지 않은 modality와 동일한 downstream 결과를 재사용한다. FAILED retry와 stale RUNNING recovery는 명시적 호출만 허용하고, Source/Project parent row lock과 commit 전 input revalidation을 위한 경계를 제공한다. Event grouping validity에는 accepted Relation set이 포함되며 Candidate 변화가 있을 때만 caller가 incremental Event update를 요청한다. 이는 distributed queue, scheduler 또는 immutable history가 아니다.

MVP-01의 `GET /projects/{project_id}/scene-candidates`는 기존 active-result 계약으로 현재 유효한 후보만 조회한다. 후보 ID·Source ID·구간과 Evidence 유형별 개수만 반환하며 payload·원본 경로·fingerprint는 공개하지 않는다. 후보가 없으면 빈 목록이다. 이 API는 후보를 생성하거나 사용자 선택·순서 조정·최종 MP4를 제공하지 않는다. 현재 Project API 전체에는 인증과 사용자별 소유권 검증이 없으므로, 프로젝트 ID를 아는 다른 사용자로부터의 접근을 막는 제품 수준 권한 경계는 별도 구현이 필요하다.

MVP-02 Streamlit 화면은 프로젝트 ID를 입력받아 이 읽기 전용 API의 후보 순서·구간 길이·Evidence 유형/개수를 표시한다. 후보 0개는 정상 빈 상태이며 원본 미리보기, 후보 선택/정렬, 중요도 점수 또는 최종 MP4는 제공하지 않는다. 인증이 없으므로 로컬 개발용 화면이다.

MVP-03A는 v1 분석을 완료한 SourceVideo 한 건에 대해 Autonomous Discovery를 실행하는 별도 application adapter를 추가했다. 저장된 Transcript/길이를 재사용하고 원본은 SourceStorage 경유로만 열며, Scene 전용 임시 WAV를 정리한다. 결과는 기존 Scene Work/Candidate/Evidence에 저장되어 MVP-01 조회 계약을 따른다. Scene 성공·기권·실패는 v1 완료 상태와 별개다. 실제 촬영 영상에 대한 동작·정확도 검증은 아직 하지 않았다.

MVP-05M은 반응 단서 Evidence를 확인된 STT 단어 구간에만 배치해 긴 segment의 다른 Audio Activity와 잘못 결합하는 경우를 차단한다. 단어 시점이 없으면 반응 단서는 보류하며, 기존 STT/VAD 설정과 다른 후보 규칙은 유지한다. 기존 Scene 결과는 자동 삭제하지 않으며 새 분석은 별도 버전·fingerprint로 구분된다.

MVP-03B는 v1 전용 `POST /projects/{project_id}/process`를 변경하지 않고, `POST /projects/{project_id}/scene-process`로 별도 Scene 분석을 접수한다. 반환된 `status_url` (`GET /projects/{project_id}/scene-processing`)에서 접수·진행·Source별 성공/기권/실패/차단/건너뜀을 확인한 뒤, 기존 `GET /projects/{project_id}/scene-candidates`에서 유효 후보를 조회할 수 있다. v1 미완료 Source는 Scene 분석을 건너뛰며, 한 Source의 실패가 다른 Source의 결과나 v1 완료 상태를 변경하지 않는다. Scene Work/Candidate/Evidence는 DB에 남지만 프로젝트 Scene 실행 진행률·마지막 실행 결과는 **단일 프로세스 메모리에만** 있으므로 서버 재시작 뒤 `NOT_STARTED`는 이 프로세스에서 추적 중인 실행이 없다는 뜻이다. v1과 Scene 실행은 같은 단일-worker executor를 사용하며 영속 큐·분산 잠금·자동 재시도는 없다. 인증/사용자별 권한 검증과 실제 촬영 영상 정확도 검증은 아직 없다.

MVP-05F는 읽기 전용 `GET /projects/{project_id}/scene-diagnostics`와 Streamlit의 진단 보기를 추가한다. 저장된 Scene modality Work 결과에서 Source별 Evidence 개수·유형·구간, 후보 수, 안전한 경고 코드와 관측 가능한 기권 이유를 보여준다. 근거 기록이 없거나 실행 간 대응이 불명확하면 `UNKNOWN`으로 표시한다. 이 진단은 DB에 남은 분석 사실이며, 메모리 전용 실시간 실행 상태(`scene-processing`)를 대체하지 않는다. 추천 규칙·후보 조회 계약·인증 한계는 그대로다.

MVP-03C Streamlit 프로젝트 화면은 Scene 분석 접수 버튼과 수동 상태 새로고침을 제공한다. 실행 중 중복 클릭을 막고 Source별 완료·정상 기권·실패·차단·건너뜀을 구분하며, terminal 상태 조회 후 기존 유효 후보 목록을 다시 읽는다. 서버 재시작 뒤 `NOT_STARTED`를 성공/실패로 해석하지 않는다. 이 UI는 로컬 개발용이며 Scene 선택·편집·MP4 결합이나 인증은 제공하지 않는다.

MVP-04는 현재 유효한 후보 중 사용자가 사용할 장면을 선택·제외하고 순서를 정해 프로젝트별 편집 계획으로 DB에 저장한다. `GET/PUT /projects/{project_id}/scene-edit-plan`이 순서가 있는 후보 ID 목록을 조회·교체하며, 저장 시 기존 active-result 계약으로 프로젝트 소속과 유효성을 검증한다. 재분석으로 무효화된 ID는 조회 응답의 `invalid_candidate_ids`와 Streamlit 경고에 남고, 사용자가 명시적으로 해결할 때까지 다른 후보로 대체하지 않는다. 이는 사용자 선택 목록이지 v3 Edit Planner의 완성된 EditPlan이 아니다. SceneCandidate/Evidence, v1 `/process`, Scene 분석 API는 그대로이며 실제 자르기·결합·자막·최종 MP4는 아직 없다. 기존 DB에는 새 Alembic migration 적용이 필요하다. 인증/사용자별 권한 검증과 실제 영상 End-to-End 검증도 아직 없다.

MVP-05A는 저장된 장면 순서를 다시 검증한 뒤 `SourceStorage.resolve()`로 원본을 읽어 기존 개별 `render_clip()`을 재사용하고, 해상도·프레임레이트·오디오 유무를 정규화해 하나의 H.264/AAC MP4로 결합하는 백엔드 엔진이다. 임시 구간 파일은 정리하고 성공한 최종 MP4만 별도 출력 경로에 남긴다. 재분석으로 무효화된 후보, 비어 있는 계획, 원본 누락 또는 FFmpeg 실패는 명시적 오류이며 다른 후보로 대체하지 않는다. 합성 미디어로 결합을 검증했지만 실제 촬영 영상의 장시간 렌더링·품질은 아직 검증하지 않았다. 사용자용 렌더 API·Streamlit 연결·자막·인증은 MVP-05A에 없다.

MVP-05B는 `POST /projects/{project_id}/render` (202 접수), `GET /projects/{project_id}/rendering` (상태), `GET /projects/{project_id}/renders/{render_id}/download` (완료 MP4)를 추가했다. 기존 단일 worker에서 비동기로 실행하고 프로젝트별 중복 렌더를 막는다. 빈/무효 편집 계획은 접수 전에 오류로 응답하며 실행 시에도 재검증한다. 결과는 `outputs/projects/` 아래에 보존되고 임시 구간은 MVP-05A가 정리한다. 다운로드는 같은 프로세스에서 완료를 확인한 렌더 ID와 안전한 출력 경로에만 허용한다. 실행 상태·완료 ID 목록은 **프로세스 메모리 전용**이므로 서버 재시작 뒤 파일이 남아도 성공으로 간주하거나 다운로드하지 않는다. 실제 진행률 퍼센트는 없고, 사용자 권한·Streamlit 연결·장시간 실제 촬영 영상 검증도 아직 없다.

MVP-05C는 Streamlit 프로젝트 화면에서 **저장된** 편집 계획으로 렌더링을 접수하고, 수동으로 상태를 새로고침해 완료 MP4를 다운로드할 수 있게 한다. 미저장 선택·순서, 빈 계획, 무효 후보는 화면에서 실행을 막으며 백엔드도 다시 검증한다. 진행률 퍼센트나 재시작 후 상태 복구는 없고, 자동 자막·BGM·인증과 실제 촬영 영상 E2E 검증은 아직 구현·확인하지 않았다.

MVP-06B는 저장된 Transcript의 segment/word 시각과 순서가 있는 SceneCandidate 구간에서 한국어 SRT 문자열을 생성하는 **순수 로직**을 추가했다. 선택 구간만 포함하고 클립 길이를 누적한 계획상 시간축을 사용한다. 렌더링된 MP4의 실제 PTS/길이와 동기화하거나 자막을 영상에 삽입하는 기능은 아직 없다. 현재 저장형 편집 계획은 동일 Candidate의 중복 선택을 허용하지 않지만 자막 매핑 함수는 반복 입력을 처리할 수 있다.

MVP-06C-1은 자막이 있는 렌더에서 병합 영상 필터와 동일한 30fps 정규화 조건으로 클립별 영상 시간축을 측정하고, 그 실제 길이를 반영한 `final.srt`를 MP4 옆에 보관한다. 요청 구간과 출력 길이의 차이는 클립 안에서 비례 매핑하며, 최종 영상 길이와 측정값이 맞지 않거나 SRT 생성이 실패하면 **MP4는 유지하고 SRT는 생략**한다. 기존 MP4 다운로드 API는 변경하지 않았으며 SRT 다운로드·영상 내 자막 삽입은 아직 없다.

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
