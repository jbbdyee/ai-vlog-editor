# Cutory Product Vision

## 목적

Cutory의 최종 제품 정의와 해결할 문제, 사용자와 AI의 역할 경계를 고정한다.

## 제품 정의

Cutory는 수 시간의 100+ 촬영 영상을 탐색하고, Memo와 자동 발견한 사건, 사용자 취향, 현재 요청을 함께 이해해 Main Vlog, Preview, Final Render와 선택적 Short-form 후보를 만드는 Multi-Agent AI Video Editing System이다.

## 해결하는 문제

사용자에게 부족한 것은 항상 창작 판단이 아니다. 수백 개 소스를 다시 보고, 시점을 찾고, 중복을 제거하고, 자막·음악·색감을 일관되게 적용하는 반복 노동이 문제다. Cutory는 이 노동을 줄이되 사용자의 의도와 승인을 제거하지 않는다.

## 책임

- Memo가 있는 장면과 없는 장면을 함께 탐색한다.
- 장면을 파일이 아닌 사건·반응·스토리 단위로 이해한다.
- 점수 상위 장면 모음이 아닌 완결된 Narrative를 계획한다.
- 자막, BGM, 색감, transition, SFX를 사용자 스타일과 Scene Context에 맞게 계획한다.
- AI Review와 User Review를 거쳐 검증 가능한 Final Render를 만든다.

## 입력과 출력

Input은 100+개, 수 시간의 이질적인 원본, 선택적 Edit Memo, CurrentInstruction, ProjectStyle, UserStyleProfile이다. Output은 사용자가 길이를 지정할 수 있는 일반적 15~25분 Main Vlog와, 필요시 Episode 분할안, Preview/Final Render, Shorts/Reels 후보다.

## 사용자와 AI의 관계

- User: 목표, 스타일 예외, Episode 분할, AI 해석, Preview, 장기 기억을 승인한다.
- AI: 탐색, 후보 축소, 의미 연결, 계획, 검증, 반복 실행을 담당한다.
- Deterministic Tool: ID·시간·라이선스·파일·렌더링을 검증하고 실행한다.

## 성공의 의미

- 촬영량이 많아도 이전 분석을 재사용하고 중단 후 resume할 수 있다.
- 명시적 Memo와 Memo 없는 유의미한 장면을 모두 취급한다.
- 사용자 수정을 전체 재계산이 아닌 targeted recomputation으로 반영한다.
- 최종 결과와 근거, 사용 소스, plan version을 추적할 수 있다.

## 다른 Component와의 관계

Scene Agent는 재료를 만들고, Style Agent는 적용 정책을 해석하며, Edit Planner는 이야기를 구성하고, Creative Agent는 표현 계획을 만든다. Reviewer는 수정하지 않고 검증하며, Orchestrator는 이 절차의 상태와 routing을 관리한다.

## 실패 처리

핵심 Scene/Plan/Core Render 실패는 중단 또는 사용자 판단으로 올린다. 선택적 Creative resource와 Shorts 실패는 경고를 남기고 가능한 결과를 생성한다.

## 하지 않는 일

창작 판단을 사용자에게서 완전히 제거하지 않고, 한 번의 행동을 장기 취향으로 자동 일반화하지 않으며, 원본 binary를 불필요하게 외부 AI에 전송하지 않는다.

## 향후 확장

정확한 Version 범위, 모델, infra, platform-specific short-form policy는 별도 Roadmap과 평가로 결정한다.
