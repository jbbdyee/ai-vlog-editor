# Database and Memory Design

## 목적

Full Product의 구조화 상태, 관계, plan version, 메모리, resource license, execution lineage를 관리한다. Binary와 vector retrieval은 분리한다.

## 주요 Entity

- User, StyleProfile
- Project, ProjectStyle
- SourceVideo, Transcript, EditMemo
- SceneCandidate, SceneEvidence, SceneQualityFlag, SceneRelation, EventGroup
- EditPlan, EpisodePlan, SceneEditPlan
- CreativePlan
- Review, ReviewIssue
- Render, UserFeedback
- StyleReference
- KnowledgeDocument, KnowledgeChunk
- FontResource, BGMResource, ColorPreset, SFXResource
- AgentExecution, ToolExecution

## Memory 세 종류

1. Explicit Preference Memory: UserStyleProfile
2. Project Memory: ProjectStyle
3. Experience/Reference Memory: 과거 사용자 승인/수정 편집 사례

`UserStyleProfile`은 구조화 선호이고 `StyleReference`는 상황별 사례이다. ProjectStyle은 해당 Project에만 적용된다.

## Memory Update Policy

`자막 조금 작게`와 같은 피드백은 기본적으로 ProjectStyle만 수정한다. `앞으로 모든 영상에 적용`을 선택했을 때만 Profile Update Proposal을 만들고 사용자 확인 후 장기 profile을 바꾸며 audit trail을 남긴다.

## Style Version / Snapshot

UserStyleProfile은 version 또는 이에 준하는 변경 이력을 가져야 한다. EditPlan/CreativePlan은 해당 편집에 실제 사용된 ResolvedStyle 또는 style snapshot/reference를 보존한다.

```text
UserStyleProfile v1
→ EditPlan v1 / Style Snapshot A
→ FinalRender A

UserStyleProfile v3
→ 과거 FinalRender A는 Style Snapshot A로 재현/추적
```

후에 UserStyleProfile이 변경되어도 과거 FinalRender의 스타일 결정 근거를 재현할 수 있어야 한다. 정확한 DB schema와 snapshot 저장 방식은 미결정이다.

## Project-derived Data Lineage

```text
Project
→ SourceVideo → Transcript → EditMemo
→ SceneCandidate → EventGroup
→ EditPlan → CreativePlan → Preview / Render
```

Project에서 파생된 엔티티와 resource는 source project reference를 통해 추적 가능해야 한다. StyleReference가 특정 Project의 승인/수정 사례에서 생성되었다면 `source_project_id` 또는 이에 준하는 lineage를 유지한다. Project 삭제 요청 시 연결된 파생 데이터와 개인화 reference를 식별할 수 있어야 하지만, 실제 삭제/보존 범위와 기간은 향후 retention/privacy policy에서 결정한다. 독립적인 장기 UserStyleProfile 전체를 Project 삭제와 함께 자동 삭제하는 것으로 정의하지 않는다.

## Storage 분리

- Relational DB: entity, state, relation, profile, plan, review, license, execution metadata
- File/Object Storage: source, preview, final render, short-form
- Vector: KnowledgeChunk, StyleReference, BGM embedding
- Temporary Workspace: WAV, frame, contact sheet, proxy, intermediate clip

파일 binary는 DB column에 직접 넣지 않고 resource reference와 integrity metadata만 저장한다.

## Version / Lineage

Plan, Review, Render, Style update는 version으로 보존한다. Final Render는 source scene, EditPlan, CreativePlan, ToolExecution까지 역추적 가능해야 한다. AgentExecution/ToolExecution은 reference, model/tool/config version, status, latency/cost 메타데이터를 남기되 prompt/binary/secret 전체를 저장하지 않는다.

## 실패 처리

상태 전이와 output publish는 중간 상태에서 resume 가능하게 기록한다. 불완전한 execution은 final resource로 표시하지 않고 safe error/retryability를 남긴다.

## 하지 않는 일

한 번의 행동으로 장기 선호를 자동 갱신하지 않고, relational DB에 video/frame binary를 저장하지 않으며, vector search를 exact state lookup에 사용하지 않는다.

## 향후 확장

정확한 PostgreSQL schema, migration, tenancy, encryption, retention/erasure, vector backend은 Roadmap에서 선택한다.
