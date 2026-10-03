# Scene Agent

## 목적

Memo-guided Editing과 Autonomous Scene Discovery를 함께 사용해 어떤 장면이 존재하고 왜 사용할 가치가 있는지를 구조화한다. 최종 편집을 결정하지 않는다.

## 책임

- `USER_MEMO`를 강한 의도 Evidence로 반영
- Memo가 없는 전체 footage에서 Autonomous Discovery
- Transcript, audio reaction, visual event, motion, shot change, preference evidence 통합
- observed semantic fact, QualityFlag, candidate utility/preference와 optional role/usage hint 분리
- 파일 간 EventGroup/Relation 후보 제공

## 입력

SourceVideo metadata, Transcript, EditMemo, shot/audio/quality signal, deterministic scene segments, Project instruction, 제한된 UserPreference context, optional deep-analysis result.

## 출력

- SceneCandidate: source/time/resource reference, summary, confidence, preference match
- SceneEvidence: type, source, strength, supporting resource IDs
- SceneQualityFlag
- SceneRelation/EventGroup proposal
- optional CandidateSemanticHint/RoleHint: evidence-backed, potentially multi-label, non-authoritative Planner input
- unresolved ambiguity/warnings

Scene Agent가 제공하는 hint는 “이 장면은 reaction shot으로 활용 가능” 같은 해석이며 “최종 role은 REACTION”이라는 확정이 아니다. 같은 Candidate도 Project/EditPlan context에 따라 `ESTABLISHING`, `B_ROLL`, `TRANSITION` 또는 `HIGHLIGHT`로 사용될 수 있다. exact hint schema와 taxonomy는 v3 Detailed Plan에서 결정한다.

## 주요 흐름

Cheap deterministic evidence로 후보를 만들고, 중복/저가치 후보를 축소한 뒤 필요한 구간만 심층 LLM/VLM 분석을 요청한다. Memo/Autonomous Candidate와 관측 Evidence, 필요한 경우 optional semantic/usage hint를 함께 Edit Planner에 제공한다.

## Semantic fact와 editorial role 경계

- `reaction observed`, dialogue present, location view와 action/event cue는 관측 또는 semantic interpretation이다.
- explicit user memo, preference match와 likely-highlight signal은 candidate utility/preference 근거다.
- `STORY`, `ESTABLISHING`, `B_ROLL`, `TRANSITION`은 배치 맥락에 따른 editorial role이며 Edit Planner가 최종 결정한다.
- `HIGHLIGHT`는 사용자 의도, Project theme, target duration, alternatives와 Episode context에 따라 달라지는 선택 판단이다.
- `BAD_TAKE`는 role이 아니라 quality/exclusion/preservation 판단에 가깝고 이름만으로 자동 삭제하지 않는다.
- observed reaction과 장면을 reaction shot으로 사용하는 결정은 별개다.

## Quality 정책

`BLUR`, `SHAKE`, `DARK`, `OVEREXPOSED`, `LONG_SILENCE`, `DUPLICATE`, `ACCIDENTAL_RECORDING`, `LOW_AUDIO_QUALITY`는 자동 삭제 명령이 아니다. Technical quality가 낮아도 명시적 User Memo가 우선할 수 있다.

## 다른 Component와의 관계

Media/Scene Tools에서 evidence를 받고 Edit Planner에 후보와 optional non-authoritative hint를 제공한다. Edit Planner가 SceneEditPlan의 최종 editorial/narrative role을 소유한다. Reviewer가 scene 오선택을 발견하면 해당 source/event 범위만 targeted retry한다.

## 실패 처리

일부 source/evidence 실패는 warning으로 보존하고 남은 후보를 반환한다. 핵심 event의 근거가 없거나 후보가 전혀 없으면 Orchestrator에 decision/retry를 요청한다.

## 하지 않는 일

Scene 순서, Episode, 최종 길이, authoritative SceneRole, Caption/BGM/Color, FFmpeg command를 결정하지 않는다. Quality heuristic이나 `BAD_TAKE` hint만으로 source를 삭제하지 않는다.

## 향후 확장

Cross-video multimodal retrieval, better event identity, active user clarification, calibrated confidence는 Evaluation 근거에 따라 확장한다.
