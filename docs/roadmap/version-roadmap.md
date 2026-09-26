# Cutory Version Roadmap

> Status: Phase B — Version Roadmap
>
> 이 문서는 현재 Baseline에서 [Cutory Full Product Design](../product/full-development-plan.md)까지 도달하는 구현 순서를 정의한다. Full Product 범위를 축소하거나 각 Version의 상세 구현을 확정하는 문서가 아니다.

## 1. 목적과 문서 경계

Cutory의 최종 목적지는 수 시간, 일반적으로 100개 이상의 원본 영상에서 Main Vlog와 선택적 Short-form을 만드는 Multi-Agent AI Video Editing System이다. 최종 제품 정의와 사용자 경험은 다음 Source of Truth를 따른다.

- [Product Vision](../product/product-vision.md)
- [Full Product Development Plan](../product/full-development-plan.md)
- [Full Product User Journey](../product/user-journey.md)
- [Full Product Architecture](../architecture/full-architecture.md)

이 Roadmap은 다음 질문에만 답한다.

> 현재 Baseline에서 시작해 어떤 capability와 검증 결과를 순서대로 축적해야 Full Product Cutory에 도달하는가?

각 Version에서는 목적, 핵심 범위, 재사용할 결과, 새 capability, 아직 하지 않는 일, 완료 기준, 평가 대상, 다음 Version에 넘길 결과물만 정의한다. API endpoint, DB column, Python class, 파일 단위 작업, 세부 schema, 모델과 vendor 같은 구현 상세는 해당 Version 시작 직전의 Detailed Plan에서 결정한다.

`Not in this version`은 Full Product에서 기능을 삭제한다는 뜻이 아니다. 선행 기반과 평가 근거가 준비될 때까지 후속 Version으로 구현을 넘긴다는 뜻이다. Version은 완전히 고립된 Waterfall 단계가 아니며, 앞 단계의 결과를 뒤 단계가 재사용하고 Evaluation 결과에 따라 다음 Detailed Plan을 조정한다.

## 2. 공통 개발 원칙과 Evaluation Gate

모든 Version은 다음 cycle을 따른다.

```text
Design
→ Implementation
→ Integration
→ Evaluation
→ Failure Analysis
→ Documentation
→ Version Completion
```

기존 프로젝트 원칙인 `Baseline → Evaluation → Failure Analysis → Improvement`를 계속 유지한다. 기능이 존재하거나 단위 테스트가 통과했다는 이유만으로 Version을 완료하지 않는다. 각 Version의 핵심 capability를 실제 데이터와 실행 가능한 integration scenario로 검증하고, 실패 유형과 제약을 문서화해야 한다.

정확한 benchmark, dataset 규모, 품질 threshold와 운영 SLO는 각 Version Detailed Plan과 Evaluation 설계에서 사전에 고정한다. 평가 결과를 본 뒤 같은 실험의 성공 기준을 바꾸지 않는다.

## 3. Baseline / v0 — 현재 구현 상태

현재 저장소는 Full Product v1 완료 상태가 아니라 Baseline/feasibility/integration history를 가진 **v0**다. 현재 사실은 [README](../../README.md), [MVP v1 Specification](../mvp-v1-spec.md), [Pipeline Integration Verification](../integration-eval01-v0.1.md), [Browser E2E Verification](../browser-e2e-v0.1.md), [Evaluation Dataset](../../evaluation/README.md)과 `evaluation/results/` 기록을 기준으로 한다.

### 구현 및 실제 검증된 범위

- MOV/MP4의 안전한 로컬 업로드와 UUID 기반 저장
- ffprobe 기반 Media Probe
- FFmpeg 기반 16 kHz mono WAV audio extraction
- faster-whisper `small` 기반 STT와 segment/word timestamp
- trigger/reference/action 규칙 기반 Edit Memo detection
- Memo 이전 5·10·15·30초 Fixed-window SceneCandidate
- Ground Truth 대비 IoU, Coverage, Boundary Error 평가 도구
- FFmpeg H.264/AAC clip render
- 명시적으로 주입된 `SceneSelector`와 fixed-window selector
- Probe → Audio → STT → Memo → Candidate → Selection → Render를 연결한 `VideoProcessingPipeline`
- FastAPI processing/upload/clip delivery 경계와 lifespan STT model 재사용
- Streamlit HTTP client Prototype과 실제 Browser E2E
- 실제 `eval_01.MOV`의 단일 영상 처리, MP4 생성·다운로드·브라우저 재생, temporary WAV cleanup

### 연구·평가 history

- Fixed-window Baseline과 Evaluation Dataset v0.1
- Transcript Block retrieval 및 semantic block selection 실험
- Audio Boundary refinement와 Visual Motion refinement
- deterministic scene boundary proposal과 Proposal Oracle 분석
- Local Ollama VLM proposal selection, provider/context/latency failure 기록
- Gemini semantic/VLM proposal selection과 provider feasibility 기록
- 3-frame/5-frame Contact Sheet feasibility
- 결과 영속 저장, 사전 성공 기준, 실패 단계 분리 등 Evaluation framework/history

이 실험들은 최종 Scene Intelligence로 확정된 것이 아니다. 성공과 실패 모두 v2의 Scene Evidence, candidate reduction, provider/runtime 판단과 평가 설계에 사용하는 근거다.

### 현재 없는 Full Product capability

- Project와 100+ SourceVideo의 product persistence
- incremental/resumable multi-source processing과 project-level partial failure
- Product DB, object/file resource abstraction, vector retrieval
- Full Autonomous Scene Agent와 Cross-video Event Grouping
- production Tool/MCP capability architecture
- Multi-Agent workflow와 persisted LangGraph orchestration
- Episode/Narrative Edit Planning
- Creative Agent와 full Caption/BGM/Color/Effect/SFX planning
- Preview/Reviewer/targeted retry workflow
- 장기 personalization memory와 Style Reference RAG
- Final production frontend와 full project UX
- Main Vlog 전체 렌더 및 Short-form workflow

### v0가 v1에 넘기는 결과물

- 검증된 media/STT/memo/candidate/render service와 테스트
- 실제 MOV·API·Browser integration 경로
- 안전한 ID/path validation과 temporary artifact cleanup 경험
- Scene selection 실패를 포함한 Evaluation history
- Full Product Design과 현재 구현의 명확한 경계

## 4. Version Dependency

```text
Baseline / v0 — 단일 영상 Baseline과 실험·E2E history
  ↓
v1 — Project/Data foundation으로 100+ Source를 안정적으로 관리
  ↓
v2 — Tool/MCP 경계에서 Scene을 발견하고 Event로 연결
  ↓
v3 — Agent가 Scene/Event를 Episode와 Vlog EditPlan으로 구성
  ↓
v4 — EditPlan을 CreativePlan과 Preview로 표현
  ↓
v5 — Preview를 검증하고 필요한 부분만 재작업하며 명시적 개인화를 축적
  ↓
v6 — 전체 사용자 경험, Final Render, optional Short-form과 배포를 완성
```

의존 관계는 다음과 같다.

- v1의 Project, SourceVideo, processing state와 lineage를 v2의 대량 Scene 분석이 사용한다.
- v2의 SceneCandidate, SceneEvidence, QualityFlag, SceneRelation, EventGroup을 v3의 Agent와 Planner가 사용한다.
- v3의 EpisodePlan, EditPlan, SceneEditPlan, ResolvedStyle을 v4의 Creative Agent가 사용한다.
- v4의 CreativePlan과 Preview를 v5의 Reviewer와 사용자 피드백 흐름이 검증한다.
- v5의 reviewed workflow, targeted retry, personalization memory를 v6의 Full UX가 사용자에게 노출한다.

후속 Version 구현 중 앞 단계의 schema/capability를 확장할 수 있지만, 이미 검증된 결과를 이유 없이 다시 만들거나 history를 삭제하지 않는다.

## 5. v1 — Project & Large Video Foundation

### 목적

100개 이상의 원본 영상을 하나의 Project로 관리하고, 중단 후 재개 가능한 분석 기반을 만든다. 중심은 AI 기능 추가가 아니라 뒤의 Agent가 신뢰할 수 있는 Project/Data foundation이다.

### 이전 단계에서 재사용

- Media Probe, audio extraction, STT, Edit Memo detection
- 안전한 upload/storage ID와 file validation
- temporary WAV cleanup과 structured service errors
- `VideoProcessingPipeline`에서 확인한 application/service 경계
- 실제 MOV integration 및 기존 자동화 테스트

### 핵심 범위와 새 capability

- Target Repository Structure로의 단계적 migration 시작
- backend/application boundary 정리
- Product DB 기반과 resource reference
- Project, SourceVideo, Transcript, EditMemo, Processing State
- 100+ Source의 multi-video ingestion
- source/stage 단위 Incremental Processing과 Resumable Processing
- input/config/tool version에 따른 완료 결과 재사용과 무효화 근거
- source-level Partial Failure와 project-level progress aggregation
- Temporary Workspace 소유권과 artifact lifecycle
- 병렬화 가능한 media analysis를 위한 상태·dependency 기반
- Project-derived data lineage의 시작점

정확한 DB schema, migration 단위, worker/queue 방식과 storage vendor는 v1 Detailed Plan에서 결정한다.

### Integration Result / 완료 기준

하나의 Project에서 100+ Source를 등록하고 source별 분석 상태를 저장할 수 있어야 한다. 실제 처리 도중 중단한 뒤 재시작했을 때 완료된 분석은 재사용하고 남은 stage부터 계속해야 한다. 일부 source가 실패해도 영향과 상태를 기록하고 정책상 가능한 나머지 처리를 계속해야 한다. temporary artifact는 소유권과 완료/실패 정책에 따라 정리돼야 한다.

### 평가 대상

- 대량 source 등록, 상태 정확성, 중단/resume와 중복 처리 방지
- 일부 source 및 stage failure 격리
- analysis output 재사용과 invalidation
- temporary artifact cleanup과 source 보존
- 다양한 길이·codec·오디오 유무의 실제 media

정확한 수량, 성능, concurrency와 성공 threshold는 v1 Evaluation 계획에서 고정한다.

### Not in this version

- Full Scene Agent와 Cross-video semantic Event Grouping
- Full Multi-Agent/LangGraph workflow
- Creative Agent, Reviewer, Product RAG
- 완성된 personalization memory와 Shorts
- Final production frontend

### 다음 Version에 넘기는 결과물

Project/resource ID, 100+ Source analysis state, reusable Transcript/EditMemo/media metadata, failure/resume history, storage/lineage boundary, v1 Evaluation 및 Failure Analysis.

## 6. v2 — Tool / MCP & Scene Intelligence

### 목적

기존 영상 처리 capability를 안전한 Tool/MCP 경계로 정리하고, Memo가 없는 영상에서도 의미 있는 Scene을 찾아 여러 Source의 실제 Event로 연결한다.

### 이전 단계에서 재사용

- v1의 Project, SourceVideo, processing state, media/STT/memo output
- v0의 transcript/audio/motion/visual/VLM proposal 실험과 failure evidence
- 기존 deterministic media/scene/render service
- resource ownership, temporary workspace와 lineage

### 핵심 범위와 새 capability

- `Agent = 판단`, `Tool = deterministic execution`인 Tool Layer
- 의미 있는 capability만 노출하는 Video Editing MCP Server
- resource ID 중심 input/output, validation, safe failure와 execution reference
- Memo-guided Scene Discovery와 전체 footage 대상 Autonomous Scene Discovery 병행
- Memo가 있어도 Autonomous Discovery를 비활성화하지 않는 정책
- Scene segmentation, SceneCandidate, SceneEvidence, SceneQualityFlag
- technical quality, confidence, preference match 분리
- `Cheap → Expensive Analysis`와 deep-analysis 전 Candidate Reduction
- 필요한 후보 구간에 한정한 LLM/VLM 심층 분석
- Source를 넘는 SceneRelation과 EventGroup
- `SAME_EVENT`, `CONTINUATION`, `REACTION_TO`, `ALTERNATIVE` 관계
- experimental selector/refiner를 정답이 아닌 evidence/evaluation history로 재사용

### Integration Result / 완료 기준

100+ Source Project를 cheap deterministic analysis로 처리해 Scene unit과 evidence를 만들고, 후보 축소 후 선택된 구간만 심층 분석해야 한다. Memo Candidate와 Autonomous Candidate가 함께 생성되어야 하며, 여러 Source의 관련 Scene을 EventGroup으로 연결한 구조화 결과를 만들어야 한다. 일부 evidence/provider 실패는 숨기지 않고 영향과 fallback 가능 여부를 기록해야 한다.

### 평가 대상

- Memo-guided/Autonomous discovery의 독립적·결합 성능
- Scene boundary, role, evidence, quality flag의 정확성과 calibration
- candidate reduction이 유의미한 Scene을 보존하는지
- cross-video relation/EventGroup 품질
- cheap/expensive 분석 비용과 외부 전송 최소화
- Tool/MCP validation, determinism, idempotency와 failure isolation

### Not in this version

- 완결된 Vlog Narrative와 Episode/EditPlan 생성
- Caption/BGM/Color 중심 CreativePlan
- Reviewer와 personalization memory
- Final UX와 Short-form rendering

### 다음 Version에 넘기는 결과물

검증된 Tool/MCP capability, SceneCandidate/Evidence/QualityFlag, SceneRelation/EventGroup, deep-analysis policy, Scene Intelligence Evaluation과 Failure Analysis.

## 7. v3 — Multi-Agent Planning & Orchestration

### 목적

Scene을 후보 목록으로 끝내지 않고 사용자 의도, 프로젝트 요구, 스타일과 Event 흐름에 맞는 Main Vlog의 EpisodePlan과 EditPlan으로 구성한다.

### 이전 단계에서 재사용

- v1의 Project state, persistence, resume와 lineage
- v2의 Tool/MCP capability와 SceneCandidate/EventGroup
- Full Product의 user/project style 우선순위와 planning policy

### 핵심 범위와 새 capability

- Scene Agent, Style Agent, Edit Planner의 책임 분리
- workflow state/routing만 담당하는 Orchestrator
- LangGraph 도입 검토 및 필요한 경우 persisted workflow 구현
- sequential flow, conditional routing, user wait state와 resume
- CurrentInstruction, ProjectStyle, UserStyleProfile, retrieved reference 우선순위를 반영한 ResolvedStyle
- Event 기반 Narrative, target duration, 중복 제거, Opening/Ending
- EpisodePlan, EditPlan, SceneEditPlan과 Creative Intent
- Episode split policy: `SINGLE`, `AUTO_SPLIT`, `USER_CONFIRM_SPLIT`
- EventGroup, 장소, 주제, Narrative boundary, target duration 기반 Episode 구성
- 사용자 결정이 필요한 split/plan의 persisted wait state
- 선택되지 않은 좋은 Scene의 Short-form/Behind/Unused Highlight 후보 보존

이 Version에서 필요한 사용자/프로젝트 스타일 입력과 ResolvedStyle은 planning을 가능하게 하는 범위다. 장기 profile 학습, StyleReference RAG와 consent workflow의 완성은 v5가 담당한다.

### Integration Result / 완료 기준

실제 SceneCandidate와 EventGroup, 사용자/Project Style, 목표 길이를 입력받아 하나 이상의 EpisodePlan과 일관된 EditPlan을 생성해야 한다. split policy에 맞게 한 편 유지, 자동 분할 또는 사용자 결정 대기가 작동해야 하고, 단순 importance Top-K나 시간 slicing이 아니라 Event/Narrative 근거가 결과에 남아야 한다. workflow 중단 후 wait/resume 상태도 보존해야 한다.

### 평가 대상

- Scene Agent, Style Agent, Planner 책임과 output contract
- Narrative coherence, event coverage, duplicate suppression와 target duration
- User Memo/CurrentInstruction/ResolvedStyle 준수
- Episode policy별 결과와 user wait/resume
- plan lineage, deterministic validation과 workflow recovery

### Not in this version

- Caption/BGM/Color/Effect/SFX의 전체 Creative execution
- Preview Reviewer와 bounded targeted retry의 완성
- 장기 personalization update와 Style Reference RAG
- Final product frontend, Final Render와 Shorts workflow

### 다음 Version에 넘기는 결과물

Scene/Style/Planner agent contract, persisted orchestration state, ResolvedStyle, EpisodePlan/EditPlan/SceneEditPlan, Creative Intent, preserved unused Scene references, Planning Evaluation과 Failure Analysis.

## 8. v4 — Creative Editing & Retrieval

### 목적

EditPlan을 사용자 취향과 Scene Context가 반영된 Caption/BGM/Color/Transition/Effect/SFX 중심 CreativePlan과 검토 가능한 Preview로 만든다.

### 이전 단계에서 재사용

- v2의 Tool/MCP execution boundary와 Scene context
- v3의 EditPlan, SceneEditPlan, Creative Intent와 ResolvedStyle
- v1의 resource storage, version/lineage와 processing state

### 핵심 범위와 새 capability

- Creative Agent와 Caption/BGM/Color/Transition/Effect/optional SFX planning
- Caption type/source와 실행 가능한 Caption plan
- 구간별 BGM mood, genre, energy, volume, ducking, fade planning
- 검증된 ColorPreset과 제한적 adjustment
- Approved Font/BGM/ColorPreset/SFX Resource Catalog
- `SYSTEM_CATALOG`과 `USER_PROVIDED`를 구분할 수 있는 resource provenance/responsibility 경계. 사용자 제공 resource의 실제 제품 지원 시점은 별도로 결정한다.
- creative suitability와 license eligibility의 분리
- 구조화 license metadata와 deterministic Resource/License Validator
- Editing Knowledge RAG
- Approved BGM Catalog 내부 Metadata Filter + Semantic Retrieval
- Profile/Plan/License/Workflow state는 RAG가 아닌 structured DB lookup 유지
- CreativePlan version과 빠른 Preview Render
- optional creative resource 실패 시 warning을 남기는 degradation

### Integration Result / 완료 기준

실제 EditPlan과 ResolvedStyle에서 구조화 CreativePlan을 만들고, 모든 resource를 Approved Catalog와 License Validator로 검증한 뒤 Preview를 렌더링해야 한다. BGM 등 optional resource가 실패해도 core Preview는 가능한 범위에서 생성되고 경고가 남아야 한다. Preview는 Final quality render와 명확히 구분돼야 한다.

### 평가 대상

- Caption/BGM/Color/Effect/SFX plan의 style·scene 적합성과 일관성
- resource/license validation과 attribution metadata
- Editing Knowledge RAG와 BGM retrieval의 relevance 및 failure behavior
- Preview의 media integrity, 생성 시간과 사용자 검토 가능성
- optional failure가 Main Vlog planning을 불필요하게 중단하지 않는지

### Not in this version

- Reviewer Agent와 production-grade targeted retry loop
- 장기 StyleReference memory update와 consent workflow 완성
- Final UX, User Approval 기반 Final Render, Short-form rendering

### 다음 Version에 넘기는 결과물

Creative Agent contract, CreativePlan, validated resource/attribution references, Editing Knowledge RAG, BGM Semantic Retrieval, Preview Render, Creative Evaluation과 Failure Analysis.

## 9. v5 — Reviewer, Targeted Retry & Personalization Memory

### 목적

AI가 Preview를 검증하고 문제가 있는 부분만 다시 처리하며, 사용자의 명시적 피드백을 Project와 장기 개인화 memory에 안전하게 연결한다.

### 이전 단계에서 재사용

- v3의 persisted orchestration, plans와 ResolvedStyle
- v4의 CreativePlan, Preview, retrieval과 resource validation
- v1의 DB/lineage와 v2의 scoped Tool/MCP capability

### 핵심 범위와 새 capability

- Reviewer Agent와 CONTENT/INTENT/NARRATIVE/STYLE/TECHNICAL/SAFETY·RESOURCE review
- ReviewResult, ReviewIssue, severity, evidence, affected resource와 Retry Target
- Reviewer가 직접 수정하지 않고 Scene Agent/Edit Planner/Creative Agent/Render Tool로 보내는 targeted retry
- bounded retry와 변경 범위만 처리하는 partial recomputation
- AI Reviewer PASS와 User Approval의 분리
- UserStyleProfile, ProjectStyle, StyleReference의 명확한 분리
- Content, Editing, Caption, BGM, Color preference 범위
- Style Reference RAG
- Project-only 수정이 기본인 feedback policy
- `앞으로 모든 영상에 적용` 선택과 확인을 통한 explicit long-term memory consent
- UserStyleProfile version/history
- EditPlan/CreativePlan의 ResolvedStyle snapshot/reference와 FinalRender lineage
- Project-derived StyleReference provenance

정확한 retry 횟수, 장기 memory retention과 review threshold는 v5 Detailed Plan/Evaluation에서 결정한다.

### Integration Result / 완료 기준

Preview를 Reviewer가 검사해 근거 있는 issue와 target을 만들고, 문제가 있는 Agent/Tool과 구간만 재실행하여 Revised Preview를 생성해야 한다. 사용자는 Reviewer 결과와 별개로 Preview를 검토하고 수정할 수 있어야 한다. 프로젝트 수정은 기본적으로 ProjectStyle에 남고, 명시적 동의가 있을 때만 versioned UserStyleProfile 또는 StyleReference update로 연결돼야 한다.

### 평가 대상

- review issue 정확성, severity와 target routing
- bounded retry 종료, partial recomputation 범위와 회귀 방지
- revised Preview 개선과 불필요한 전체 재실행 방지
- profile/project/reference memory 격리와 explicit consent
- style retrieval relevance, profile version/snapshot 재현성과 lineage
- AI PASS와 User Approval 경계

### Not in this version

- Final production frontend 전체 화면과 대량 업로드 UX 완성
- Short-form 추천/렌더링의 제품화
- 최종 deployment/demo/portfolio packaging

### 다음 Version에 넘기는 결과물

Reviewer contract, Review/Issue history, targeted retry workflow, User Review 경계, versioned personalization memory와 style lineage, reviewed Preview, Review/Personalization Evaluation과 Failure Analysis.

## 10. v6 — Full UX, Short-form & Portfolio Completion

### 목적

Full Product Design의 사용자 경험을 완성하고, Project 생성부터 승인된 Main Vlog Final Render와 선택적 Short-form까지 End-to-End로 사용할 수 있고 시연 가능한 제품으로 만든다.

### 이전 단계에서 재사용

- v1의 100+ Source Project/Data foundation
- v2의 Scene/Event Intelligence와 Tool/MCP
- v3의 planning/orchestration
- v4의 CreativePlan/Preview/retrieval/resource validation
- v5의 Review/targeted retry/personalization memory

### 핵심 범위와 새 capability

- final frontend와 100+ Upload 집계 중심 UX
- Home, New Project, Upload, Project Setup, AI Analysis와 progress
- lightweight Initial Style Onboarding
- Episode Decision, Edit Proposal와 Memo Evidence UX
- Preview, AI Review, User Review와 lightweight review timeline
- 자연어 Edit Request와 적용 전 AI interpretation confirmation
- targeted revision과 Style Memory consent UX
- 사용자 승인 후 Final Render
- Attribution UX와 Privacy/License final validation
- Main Vlog scene뿐 아니라 Unused Highlight, Behind, Reaction을 활용하는 Shorts/Reels 추천
- 사용자 취향 기반 Short-form planning/rendering
- Main Vlog completion과 optional Short-form failure 분리
- 운영 가능한 deployment, demo, architecture/evaluation documentation와 Portfolio README

최종 frontend framework와 deployment topology는 v6 Detailed Plan 전까지 확정하지 않는다.

### Integration Result / 완료 기준

사용자가 실제 UI에서 Project를 만들고 100+ Source를 업로드하여 분석 진행을 확인하고, Episode/Edit Proposal과 Preview를 검토·수정·승인한 뒤 Main Vlog Final Render를 받을 수 있어야 한다. 사용자는 attribution과 적용된 memory를 확인할 수 있어야 하며, 선택적으로 Main/Unused/Behind/Reaction Scene에서 Short-form 후보와 결과를 만들 수 있어야 한다. Short-form 실패는 성공한 Main Vlog를 실패로 바꾸지 않는다.

### 평가 대상

- Project 생성부터 Final Render까지 실제 End-to-End completion
- 100+ Upload/progress/resume UX와 partial failure 이해 가능성
- proposal, Memo evidence, Episode decision와 edit request 해석의 사용성
- Preview/Reviewer/User Approval/Final 경계
- Main Vlog 및 optional Short-form output integrity
- privacy, license, attribution, path/secret 비노출
- deployment reliability와 portfolio demo 재현성

### Not in this version

Full Product Design 바깥의 새로운 제품 기능은 이 Roadmap에서 추가하지 않는다. 플랫폼별 publishing, collaboration, mobile-specific UX 등 Full Design에서 미결정인 확장은 별도 근거와 후속 설계를 요구한다.

### 다음 단계에 남기는 결과물

End-to-End Full Product, Final Render와 optional Short-form workflow, production UX/deployment, Full Product Evaluation/Failure Analysis, 운영·아키텍처 문서와 재현 가능한 portfolio demonstration.

## 11. Full Product Capability Coverage

| Full Product capability | 주 도입 Version | 후속 재사용/완성 |
| --- | --- | --- |
| 100+ Source Video | v1 | v2~v6 전체 |
| Incremental / Resumable Processing | v1 | Orchestrator와 UX에서 확장 |
| Partial Failure / Temporary Cleanup | v1 | v2 Tool, v3 workflow, v6 UX |
| Memo-guided Discovery | v2 | v3 planning, v6 evidence UX |
| Autonomous Discovery | v2 | Memo와 병행해 v3 planning 입력 |
| Scene Evidence / Quality / Candidate Reduction | v2 | v3 Planner, v5 Reviewer |
| Cross-video Event Grouping | v2 | v3 Narrative/Episode planning |
| Tool Layer / MCP | v2 | v3~v6 Agent execution |
| Scene Agent | v3 | v5 targeted retry |
| Style Agent / ResolvedStyle | v3 | v4 Creative, v5 memory |
| Edit Planner / Main Vlog / Episode split | v3 | v4~v6 rendering·UX |
| Orchestrator / LangGraph candidate | v3 | v5 retry, v6 product flow |
| Content / Editing / Caption / BGM / Color preference | v3 policy 입력 | v5 장기 personalization 완성 |
| Creative Agent | v4 | v5 review, v6 Final UX |
| Caption / BGM / Color / Effect / SFX | v4 | v5 review, v6 final output |
| Editing Knowledge RAG | v4 | Planner/Creative/Reviewer에서 재사용 |
| BGM Semantic Retrieval | v4 | v6 resource UX |
| Approved Resource / License Validation | v4 | v6 attribution/final validation |
| Preview | v4 | v5 review, v6 user review |
| Reviewer / bounded targeted retry | v5 | v6 Full UX |
| User Review / Revision | v5 workflow | v6 완성 UX |
| UserStyleProfile / ProjectStyle / StyleReference | v5 | v6 onboarding/consent UX |
| Style Reference RAG / explicit consent | v5 | v6 product UX |
| Database / Memory / Lineage | v1 기반 | v2~v5 entity와 memory 확장 |
| Privacy / local-first / minimal external transmission | v1부터 공통 | 모든 Version gate |
| Final Render | v6 | Main Vlog 기본 출력 |
| Short-form | v6 | Main Vlog 이후 optional flow |
| Final UX / Deployment / Portfolio | v6 | Full Product completion |
| Evaluation / Failure Analysis | 모든 Version | 다음 Detailed Plan의 입력 |

이 표의 `주 도입 Version`은 capability의 첫 제품화 지점이다. Privacy, lineage, evaluation처럼 횡단적인 원칙은 처음 도입한 뒤 모든 후속 Version에서 유지·확장한다.

## 12. Per-Version Detailed Plan 정책

전체 Version의 구현 상세를 지금 한 번에 확정하지 않는다. Roadmap 검수 후 다음 작업은 v1 Detailed Plan 작성이다. 각 Version 시작 직전에 필요하면 다음 문서를 만든다.

```text
docs/roadmap/v1-plan.md
docs/roadmap/v2-plan.md
...
```

각 Detailed Plan은 당시 코드와 이전 Version의 Integration/Evaluation/Failure Analysis를 다시 확인해 구현 범위, schema, API, migration, 테스트와 사전 성공 기준을 정한다. Version 종료 후에는 다음을 검토한 뒤 다음 Version Detailed Plan을 작성한다.

- Evaluation 결과
- Failure Analysis
- 설계 변경 필요성
- 재사용 가능한 산출물과 남은 위험
- 다음 Version의 dependency와 범위에 미치는 영향

현재 Phase B에서는 이 `version-roadmap.md`만 생성하며 v1~v6 상세 계획은 작성하지 않는다.

## 13. 의도적으로 미결정인 사항

다음은 Roadmap에서 확정하지 않고 해당 Version Detailed Plan과 Evaluation 근거에 맡긴다.

- 정확한 모델과 외부 Provider
- PostgreSQL 세부 schema와 migration 단위
- Object Storage vendor와 Vector DB 제품
- Embedding model과 chunking strategy
- exact concurrency와 queue/worker technology
- deployment topology
- final frontend framework
- retention 기간과 삭제/보존 정책의 세부값
- Reviewer retry의 정확한 횟수와 threshold
- pricing과 운영 비용 정책
- 각 Version의 일정과 날짜
- 세부 API endpoint
- Python class/file implementation
- Version tag naming convention
- Episode split 기본 policy
- 사용자 제공 BGM/Font/SFX의 실제 지원 Version과 UX

이 미결정 항목은 Full Product 목표에서 제외된 것이 아니라, 선행 결과 없이 성급하게 확정하지 않은 것이다.

## 14. 하지 않는 일

- 현재 Baseline을 Full Product v1 완료 상태로 과장하지 않는다.
- Roadmap을 이유로 Full Product Design capability를 삭제하거나 축소하지 않는다.
- 이 문서에서 repository migration, DB, Agent, MCP, LangGraph, RAG 또는 frontend를 구현하지 않는다.
- 기존 Baseline/Evaluation 실패 기록을 삭제하거나 성공으로 재해석하지 않는다.
- Ground Truth와 Oracle을 product execution flow에 연결하지 않는다.
- 각 Version의 상세 구현과 benchmark를 사전에 고정하지 않는다.
