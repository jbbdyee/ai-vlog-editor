# Cutory Orchestrator

## 목적

Agent와 Tool의 상태, routing, conditional branch, user wait, targeted retry, partial failure, resume, completion을 관리한다. 편집 판단 자체를 하지 않는다.

## 실행 모델

`Sequential Pipeline + Conditional Branch + Bounded Targeted Retry`를 기본으로 한다. Agent가 서로 자유롭게 무제한 대화하는 구조를 사용하지 않는다.

## 입력

Project/workflow state, node outputs, user decisions, retry counters, stage policies, resource availability, safe failures.

## 출력

Persisted workflow state, next node/branch, wait request, retry command with target/scope, terminal status, warnings, execution references.

## 상태 예시

```text
CREATED → UPLOADING → MEDIA_ANALYZING → SCENE_ANALYZING
→ STYLE_RESOLVING → PLANNING
→ WAITING_FOR_SPLIT_DECISION? → CREATIVE_PLANNING
→ PREVIEW_RENDERING → REVIEWING → RETRYING?
→ WAITING_FOR_USER_REVIEW → REVISING?
→ FINAL_RENDERING → SHORT_FORM_PLANNING? → COMPLETED
```

## LangGraph 사용 근거

LangGraph는 persisted state, conditional routing, node retry, user wait, 이전 node로의 targeted return, resume가 필요하기 때문에 사용 후보다. 단 Full Design은 특정 라이브러리 구현 완료를 뜻하지 않으며, 정확한 도입 시점은 Roadmap에서 결정한다.

## Retry / User Wait

Reviewer issue의 target/scope만 재실행한다. 기본 targeted retry 2회, review cycle 3회 상한을 가지며 초과 시 user decision/terminal warning으로 전환한다. Episode split, 중요 AI 해석, User Review에서 wait state를 persist한다.

## Partial Failure / Resume

Source/stage 별 terminal result를 저장해 중단 후 완료 node를 반복하지 않는다. Optional BGM/Color/SFX/Short-form 실패는 warning으로 진행할 수 있고, critical planning/core render 실패는 중단한다.

## 다른 Component와의 관계

FastAPI는 workflow 시작/상태/사용자 결정 API를 제공하고, Agent는 node 판단을, MCP/Tool은 capability 실행을 담당한다. Orchestrator는 각 domain 판단을 복제하지 않는다.

## 하지 않는 일

Scene/BGM/Caption을 직접 선택하거나 raw tool payload를 임의 생성하지 않고, retry 상한 없이 자율실행하지 않는다.

## 향후 확장

정확한 graph schema, checkpoint store, cancellation, priority, multi-project scheduling은 implementation roadmap에서 확정한다.
