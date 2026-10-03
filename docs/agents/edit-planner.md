# Edit Planner

## 목적

SceneCandidate와 EventGroup을 점수 상위 목록이 아닌 하나 이상의 완결된 브이로그 이야기로 구성한다.

## 책임

- 한 편/여러 Episode 제안
- 장소·주제·스토리 흐름 기준 Episode 구성
- Scene 선택/제외, 순서, 중복 제거, 사용 길이
- 각 SceneEditPlan의 authoritative editorial/narrative role
- target duration 준수
- Opening, Ending, 전개, 반응, 전환의 narrative
- Creative Agent에 전달할 Creative Intent
- 제외된 좋은 Scene을 Shorts/Behind/Unused Highlight로 보존

## 입력

Project, SceneCandidates, SceneEvidence, SceneQualityFlags, EventGroups/Relations, ResolvedStyle, target duration, current user/project instruction, UserStyleProfile에서 해결된 preference, Editing Knowledge RAG result.

## 출력

EpisodePlan, EditPlan, SceneEditPlan, selected/excluded scene IDs and reasons, planned in/out/use duration, order, authoritative narrative/editorial role, CreativeIntent, split proposal, preserved unused assets.

`SceneEditPlan.narrative_role` 또는 v3 Detailed Plan에서 정할 equivalent field는 Planner output lineage에 속하는 최종 role이다. SceneCandidate의 고정 property가 아니며 Scene Agent의 optional RoleHint를 그대로 복사해야 하는 값도 아니다.

## 주요 흐름

EventGroup으로 중복과 alternative를 파악하고 사용자 의도·선호·스토리·목표 길이·technical quality·ResolvedStyle을 함께 고려한다. 품질 flag는 근거 중 하나이며 명시적 User Intent를 자동으로 덮지 않는다. 촬영량이 많으면 Episode 분할안을 만들고 Orchestrator를 통해 사용자 확인을 기다린다.

같은 공항 외관 Candidate도 opening placement에서는 `ESTABLISHING`, 대화 위 overlay에서는 `B_ROLL`, Event 사이에서는 `TRANSITION`이 될 수 있다. `HIGHLIGHT` 역시 사용자 의도, Project theme, target duration, 주변 Candidate와 duplicate alternative에 따라 달라진다. observed reaction이 있다는 사실과 그 장면을 final reaction shot으로 배치하는 결정도 구분한다.

Episode 정책은 `SINGLE`, `AUTO_SPLIT`, `USER_CONFIRM_SPLIT`을 지원할 수 있다. Planner는 EventGroup, 장소, 주제, Story/Narrative boundary, target duration을 근거로 사용하고 시간만으로 기계적 분할하지 않는다. 기본 정책과 Version별 지원 범위는 이 문서에서 확정하지 않는다.

## 다른 Component와의 관계

Scene Agent의 후보·Evidence와 optional non-authoritative semantic/role hint를 소비하고, Style Agent의 pace/content 정책을 반영하며, Creative Agent에 scene order·intent·duration·final role을 전달한다. Reviewer의 NARRATIVE/CONTENT issue는 해당 Episode/EditPlan 범위만 재계획한다.

## 실패 처리

후보 부족, 목표 길이 불가능, 서사 모호성을 issue로 반환한다. 분할안과 핵심 선택이 복수로 타당하면 User Decision을 요청한다.

## 하지 않는 일

원본 장면을 직접 렌더하거나 Caption/BGM/Color 세부 값을 정하지 않고, Episode를 시간만으로 기계적으로 자르지 않는다.

## 향후 확장

Alternative plan comparison, user-adjustable narrative constraints, collaborative timeline plan는 후속 범위다.
