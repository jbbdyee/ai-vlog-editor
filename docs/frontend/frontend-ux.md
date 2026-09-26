# Cutory Full Product Frontend / UX

## 목적

100+ 영상을 집계 중심으로 다루고 AI가 먼저 반복 작업을 한 뒤, 사용자가 중요한 창작 판단과 장기 메모리를 확인하는 경험을 정의한다.

## 현재 Prototype과의 구분

현재 Streamlit은 FastAPI/VideoProcessingPipeline Browser E2E를 검증한 Prototype이며 Full Product Frontend 기술스택으로 확정된 것이 아니다.

## 주요 화면

1. Home
2. New Project
3. Upload
4. Project Setup
5. AI Analysis
6. Edit Proposal
7. Preview
8. Edit Request
9. Final Render
10. Shorts
11. Style Profile
12. Project Settings

## UX 원칙

- AI가 먼저 탐색/계획하고 사용자는 창작 판단을 유지한다.
- 자연어를 중심으로 하되 중요한 AI 해석은 적용 전 확인한다.
- 수정은 필요한 부분만 재처리한다.
- 장기 취향 저장은 사용자 선택이다.
- Agent 이름보다 user-facing progress state를 보여준다.

## Initial Style Onboarding

새 사용자에게 처음부터 거대한 Style 설정 폼을 요구하지 않는다. 첫 Project 또는 초기 설정에서 영상 템포, 자막 밀도, 색감, BGM, 중요하게 보는 Content(대화, Reaction, 풍경, B-roll, Behind) 같은 소수의 축을 가볍게 질문할 수 있다. `빠르게/보통/여유롭게`, `적게/보통/많이` 등은 UX 예시이며 현재 enum/schema로 확정하지 않는다.

핵심은 초기에 최소한의 명시적 선호만 받고, 실제 Project 수정 과정에서 사용자의 명시적 동의를 통해 UserStyleProfile을 점진적으로 정교화하는 것이다.

## 대량 업로드

100개의 큰 카드 대신 총 개수/길이, uploaded/analyzed/processing/pending/failed 집계를 우선 표시한다. 개별 source는 필요할 때 펼친다. 업로드된 source부터 incremental analysis를 시작할 수 있고 중단/resume 상태를 보여준다.

## Episode Split

분할 이유, 편별 스토리 범위, 예상 길이를 보여주고 `여러 편`, `한 편`, `직접 설정`을 선택하게 한다. 확인 전 자동 진행하지 않는다.

## Proposal / Preview / Review

Scene 선택·순서·길이, 제외 근거, Caption/BGM/Color 계획을 사용자가 이해할 수 있는 단위로 보여준다. AI Reviewer 결과와 User Approval을 별도로 표시한다. Preview와 Final quality/render cost의 차이를 안내한다.

Memo Evidence는 내부 Agent/Evidence code를 그대로 노출하지 않고 `촬영 중 '여기 꼭 살려줘'라고 표시한 장면`과 같이 사용자가 자신의 의도가 반영됐음을 이해할 수 있게 표시한다. Memo가 없는 Autonomous Scene을 열등한 후보로 취급하지 않는다.

Timeline을 제공하더라도 Premiere처럼 모든 컷을 사용자가 수동 조작하는 full manual NLE로 만들지 않는다. Timeline은 AI 결과와 스토리 흐름을 이해하고, Scene을 탐색하며, 수정 대상을 선택하는 lightweight review interface여야 한다.

## Edit Request

사용자 요청, AI가 해석한 대상/현재/변경을 보여주고 `적용`/`다시 말하기`를 제공한다. 수정 후에는 재처리된 범위를 보여준다.

## Style Memory UX

Project-only 적용이 기본이며 `앞으로 모든 영상에 적용`을 선택할 때 Profile update 내용을 한 번 더 확인한다. 기존 profile을 보고 취소/수정할 수 있어야 한다.

## Short-form UX

Final Vlog의 단순 자르기가 아닌 Main Scene, Unused Highlight, Behind, Reaction 출처와 추천 근거를 표시한다. 사용자가 후보를 선택/제외한 후 플랫폼 출력을 생성한다.

## Attribution UX

Final Render/Export에 사용된 BGM, Font, SFX 중 attribution이 필요한 항목은 resource 이름, source, license, attribution 필요 여부와 text를 사용자가 확인할 수 있어야 한다. 필요하면 attribution text를 복사할 수 있게 한다. 정확한 화면 디자인은 확정하지 않으며 Privacy/License 계층의 구조화 metadata를 UI까지 연결하는 원칙만 고정한다.

## 실패 처리

Partial source failure는 집계, 영향, 재시도/제외 action을 보여준다. Optional creative failure는 warning으로 표시하고 사용 가능한 Preview를 유지한다. Critical failure는 단계, safe explanation, resume 가능 여부를 보여준다.

## 하지 않는 일

- 100+ source를 항상 동일 크기 카드로 전개
- AI 해석/에피소드 분할/장기 메모리를 무확인 적용
- Agent 내부 용어와 raw technical failure를 사용자에게 그대로 노출

## 향후 확장

정확한 Frontend framework, timeline interaction, mobile/accessibility, collaboration, publishing UX는 별도 사용성 평가로 확정한다.
