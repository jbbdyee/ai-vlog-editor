# Reviewer Agent

## 목적

Preview와 plan을 검증하고 문제 근거, severity, retry target을 반환한다. 결과를 직접 수정하지 않는다.

## 검사 영역

- CONTENT: 잘못된/누락된 Scene, Memo 의도
- INTENT: CurrentInstruction/User explicit intent 준수
- NARRATIVE: 중복, 단절, Opening/Ending, Episode 흐름
- STYLE: ResolvedStyle, caption/BGM/color 일관성
- TECHNICAL: codec, sync, black frame, clipping, render integrity
- SAFETY / RESOURCE: license, missing resource, privacy/resource policy

## 입력

Project instruction, SceneCandidates/Evidence, EditPlan, CreativePlan, PreviewRender metadata/selected review media, validation tool results, previous ReviewIssues.

## 출력

ReviewResult는 `PASS`, `PASS_WITH_WARNINGS`, `RETRY_REQUIRED`, `USER_DECISION_REQUIRED`다. ReviewIssue는 domain, `INFO/LOW/MEDIUM/HIGH/CRITICAL` severity, evidence/reference, safe summary, retry target, affected IDs를 갖는다.

Retry target은 `SCENE_AGENT`, `EDIT_PLANNER`, `CREATIVE_AGENT`, `RENDER_TOOL`를 포함한다.

## Target 선택

- 잘못된 Scene 선택: Scene Agent
- Scene은 맞지만 본편에서 누락/중복: Edit Planner
- Caption/BGM/Color/Effect: Creative Agent
- Plan은 정상이지만 render 실패: Render Tool

## Retry 정책

기본 targeted retry 최대 2회, review cycle 최대 3회를 상한으로 둔다. 정확한 수치는 Evaluation으로 조정할 수 있다. Caption 문제라면 Creative Agent→해당 Preview→Reviewer만 반복하고 전체 workflow를 처음부터 실행하지 않는다.

## AI Review와 User Review

AI Reviewer `PASS`는 User Approval이 아니다. `PASS`라도 User Preview와 승인을 거쳐야 Final Render로 진행한다.

## 실패 처리

근거가 부족하면 추측된 PASS/FAIL 대신 `USER_DECISION_REQUIRED`를 반환할 수 있다. Retry 상한을 초과하면 Orchestrator가 안전한 종료 또는 사용자 판단으로 전환한다.

## 하지 않는 일

Plan/Preview를 직접 수정하거나 무제한 retry를 요청하지 않고, 사용자 승인을 대체하지 않는다.

## 향후 확장

Review benchmark, issue calibration, sampled/full review policy, human escalation threshold는 평가로 확정한다.
