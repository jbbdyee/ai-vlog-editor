# Cutory Data Flow and Lineage

## 목적

SourceVideo에서 Final Render와 Short-form 후보까지 데이터가 어떻게 파생되고 추적되는지, 확률적 판단과 deterministic 실행 경계를 정의한다.

## 핵심 흐름

```text
Project + SourceVideo
→ MediaInfo / Transcript / EditMemo / Technical Signals
→ SceneCandidate + SceneEvidence + QualityFlags
→ SceneRelations / EventGroups
→ ResolvedStyle + EpisodePlan + EditPlan
→ CreativePlan
→ PreviewRender
→ Review + ReviewIssues
→ UserFeedback / Revised Plan Versions
→ FinalRender
→ ShortFormCandidates / Optional Renders
```

## Scene Discovery Data

Memo-guided candidate와 Autonomous candidate, Story/B-roll/Transition candidate를 동일 SceneCandidate family로 구조화하되 출처 Evidence를 유지한다. SceneRole은 `HIGHLIGHT`, `STORY`, `REACTION`, `ESTABLISHING`, `B_ROLL`, `TRANSITION`, `BEHIND`, `FILLER`, `BAD_TAKE`를 표현할 수 있다.

Evidence의 예는 `USER_MEMO`, `TRANSCRIPT`, `AUDIO_REACTION`, `VISUAL_EVENT`, `MOTION`, `SHOT_CHANGE`, `USER_PREFERENCE`다. QualityFlag의 예는 `BLUR`, `SHAKE`, `DARK`, `OVEREXPOSED`, `LONG_SILENCE`, `DUPLICATE`, `ACCIDENTAL_RECORDING`, `LOW_AUDIO_QUALITY`다. Technical quality, confidence, preference match를 서로 다른 field로 다룬다.

## Cross-video Event Data

```text
EVENT 01 제주 도착: scene_001, scene_002, scene_004
EVENT 02 동문시장: scene_032, scene_035, scene_038
```

SceneRelation은 `SAME_EVENT`, `CONTINUATION`, `REACTION_TO`, `ALTERNATIVE`를 표현한다. Planner는 EventGroup을 사용해 비슷한 장면을 모두 넣지 않고 narrative에 필요한 장면을 선택한다.

## Plan Versioning

EditPlan, EpisodePlan, CreativePlan은 immutable version으로 보존하고 successor/reference를 만든다. Targeted revision은 변경된 plan 부분과 렌더 구간만 새 version으로 만든다.

## Data Lineage

```text
FinalRender
↑ CreativePlan v3
↑ EditPlan v2
↑ SceneEditPlan / SceneCandidate
↑ EventGroup / SceneEvidence
↑ SourceVideo
```

각 reference에는 ID, version, tool/agent execution ID, 생성 시각, config/model reference, status를 연결할 수 있어야 한다. 전체 prompt, frame/video binary, API key는 execution log에 저장하지 않는다.

## Storage Routing

- Relational DB: project/state/entity/relation/plan/review/license/execution metadata
- File/Object Storage: source, preview, final, short-form
- Vector Store: KnowledgeChunk, StyleReference, BGM embedding
- Temporary Workspace: WAV, frame, contact sheet, proxy, intermediate clip

Binary는 relational DB에 저장하지 않고 resource ID/URI/reference만 저장한다.

## External Provider Flow

Agent 요청에는 최소한의 transcript excerpt, selected low-resolution frame/contact sheet, structured scene context, opaque resource/proposal ID만 포함한다. 외부 응답이 ID를 선택하면 local manifest/DB lookup과 validator가 시간·resource를 확정한다.

## 실패 처리

각 stage output에 terminal/non-terminal status와 safe error metadata를 남긴다. Partial result는 완료 부분을 보존하고 downstream이 제약을 알 수 있게 한다. 손상된 lineage/reference는 Final Render 직전 validation에서 거부한다.

## 하지 않는 일

- Model output의 timestamp/path를 검증 없이 실행
- Ground Truth/Oracle를 product execution data에 포함
- raw secret/header/binary를 AgentExecution/ToolExecution log에 저장

## 향후 확장

정확한 schema, event log/outbox, retention/version GC, cache invalidation은 실제 DB·workflow 구현 단계에서 확정한다.
