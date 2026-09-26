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

촬영량이 많으면 장소·주제·스토리 기준 분할안을 보여준다.

```text
약 20분 영상 2편을 추천합니다.
Part 1: 제주 도착 → 시장 → 숙소
Part 2: 우도 → 해변 → 마지막 날
[​2편으로 만들기] [한 편으로 만들기] [직접 설정]
```

사용자 확인 전에 다음 단계로 자동 진행하지 않는다.

## 5. Edit Proposal / Preview

EditPlan의 장면, 순서, 예상 길이, 제외 이유, CreativePlan의 자막·BGM·색감을 확인한다. Fast Preview를 생성한 후 AI Reviewer가 검증하며, `PASS`는 사용자 승인을 의미하지 않는다.

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
