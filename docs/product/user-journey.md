# Cutory Full Product User Journey

## 목적

100+ 영상의 새 프로젝트 생성부터 Main Vlog, 수정, Final Render, Short-form 제안까지 사용자가 승인하는 지점을 명확히 한다.

## 전체 Journey

```text
Home → New Project → Upload → Project Setup
→ AI Analysis → Optional Episode Decision
→ Edit Proposal → Preview → AI Review
→ User Review → Edit Request / Confirmation
→ Final Render → Optional Shorts
→ Style Profile / Project Settings
```

## 1. New Project / Project Setup

사용자는 프로젝트 이름, 목표 길이, 이번 영상의 요구, 기본 스타일을 입력한다. 현재 지시는 ProjectStyle과 장기 UserStyleProfile보다 우선한다.

첫 프로젝트에서는 거대한 스타일 설정 폼 대신 영상 템포, 자막 밀도, 색감, BGM, 중요하게 보는 Content 같은 소수의 축에 대해 가벼운 Style Onboarding을 제공할 수 있다. 초기에는 최소한의 명시적 선호만 받고, 실제 프로젝트 수정 과정에서 사용자의 명시적 동의를 통해 UserStyleProfile을 점진적으로 정교화한다. 정확한 선택지와 schema는 아직 확정하지 않는다.

## 2. 100+ Upload / Incremental Analysis

집계 중심으로 표시한다.

```text
촬영 영상 127개 / 4시간 38분
Uploaded 103 / 127
Analyzed 72
Processing 18
Pending 13
Failed 0
```

개별 파일은 필요할 때만 펼쳐 보고, 업로드 완료 파일부터 점진적으로 분석한다. 중단 후에는 완료된 결과를 재사용한다.

## 3. AI Analysis

사용자에게 Agent 이름보다 `미디어 분석`, `장면 탐색`, `스토리 구성` 같은 진행 상태를 보여준다. Memo 유무와 관계없이 Autonomous Discovery를 실행한다. Partial source failure는 전체 중단 대신 경고와 제외 선택을 제공한다.

## 4. Episode Split Decision

프로젝트는 `SINGLE`, `AUTO_SPLIT`, `USER_CONFIRM_SPLIT` 정책을 지원할 수 있다. `SINGLE`은 한 편을 유지하고, `AUTO_SPLIT`은 촬영량·목표 길이·Narrative/Event 구조를 고려해 자동 분할하며, `USER_CONFIRM_SPLIT`은 장소·주제·Story boundary에 따른 분할안을 사용자에게 보여준다. 정확한 기본 정책은 미결정이다.

```text
약 20분 영상 2편을 추천합니다.
Part 1: 제주 도착 → 시장 → 숙소
Part 2: 우도 → 해변 → 마지막 날
[​2편으로 만들기] [한 편으로 만들기] [직접 설정]
```

`USER_CONFIRM_SPLIT`에서는 사용자 확인 전에 다음 단계로 자동 진행하지 않는다.

## 5. Edit Proposal / Preview

EditPlan의 장면, 순서, 예상 길이, 제외 이유, CreativePlan의 자막·BGM·색감을 확인한다. Fast Preview를 생성한 후 AI Reviewer가 검증하며, `PASS`는 사용자 승인을 의미하지 않는다.

사용자가 촬영 중 남긴 Edit Memo가 반영된 Scene은 `촬영 중 '여기 꼭 살려줘'라고 표시한 장면`과 같은 사용자 친화적 근거로 표시할 수 있다. 내부 Evidence code를 그대로 노출하지 않으며, Memo가 없는 Autonomous Scene도 정상 후보로 함께 표시한다.

## 6. User Review / Edit Request

자연어 수정 요청의 AI 해석을 적용 전에 확인한다.

```text
사용자: "친구가 넘어지는 장면을 조금 더 길게 해줘"

요청을 이렇게 이해했습니다.
대상: 친구가 넘어지는 장면
현재: 4.2초
변경: 앞뒤를 포함해 약 7초
[적용] [다시 말하기]
```

자막 크기 변경은 Scene Agent/Edit Planner를 재실행하지 않고 Style/Creative 및 해당 Preview만 재계산한다.

## 7. Memory Consent

`자막 조금 작게`와 같은 수정에 `앞으로 모든 영상에 적용` 선택을 제공한다. 미선택이면 ProjectStyle만 바꾸고, 선택하면 UserStyleProfile Update Proposal을 보여준 뒤 명시적 확인으로 장기 프로필을 변경한다.

## 8. Final Render

사용자 승인 후 원본 품질 기준으로 Final Render를 실행한다. Preview는 빠른 확인용이며 Final을 대체하지 않는다.

Final Render/Export에 포함된 BGM, Font, SFX 중 attribution이 필요한 resource가 있다면 resource 이름, source, license, attribution 필요 여부와 text를 확인할 수 있어야 한다. 이 정보는 structured license metadata에서 연결되며 정확한 화면 배치는 미결정이다.

## 9. Shorts / Reels

Final Vlog Scene뿐 아니라 Unused Highlight, Behind, Reaction에서 사용자 취향에 맞는 후보를 제안한다. Short-form 추천 실패는 Main Vlog 완료를 막지 않는다.

## 실패 처리

- 업로드/분석 중단: 완료 항목 보존 후 resume
- 일부 source 실패: warning, 재시도/제외 선택
- optional BGM/Color/SFX 실패: 경고 후 가능한 결과 유지
- critical planning/render 실패: 안전한 중단과 사용자 안내

## 하지 않는 일

- Agent 내부 용어를 사용자 진행 상태로 강제하지 않는다.
- AI Reviewer PASS를 User Approval로 간주하지 않는다.
- 중요한 AI 해석을 확인 없이 적용하지 않는다.

## 향후 확장

정확한 collaborative timeline UI, mobile UX, platform-specific publishing은 후속 설계와 사용성 평가로 결정한다.
