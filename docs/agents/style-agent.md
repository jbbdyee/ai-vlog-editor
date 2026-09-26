# Style Agent

## 목적

`UserStyleProfile + ProjectStyle + CurrentInstruction + SceneContext`를 이번 편집에 적용할 `ResolvedStyle`로 해석한다.

## 책임

- Content: dialogue, scenery, reaction, B-roll, behind 선호
- Editing: pace, average cut length, silence, transition, zoom 선호
- Caption: font, size, density, position, color, animation 정책
- BGM: mood, genre, energy, vocal, volume 정책
- Color: temperature, saturation, contrast, brightness, skin tone, preset 정책
- 서로 충돌하는 스타일 소스의 우선순위 해결

## 우선순위

```text
Current User Instruction
> ProjectStyle
> UserStyleProfile
> Retrieved Style Reference
> System Default
```

`평소 따뜻한 색감`인 사용자가 `이번 겨울 여행은 차갑고 푸른 느낌`을 지시하면 해당 Project만 차갑게 해석하고 장기 Profile은 유지한다.

## 입력

UserStyleProfile, ProjectStyle, CurrentInstruction, Scene/Event context, retrieved StyleReferences, approved catalog capability metadata.

## 출력

ResolvedStyle version, 소스별 적용/오버라이드 근거, 장면/에피소드별 제약, unresolved conflicts, warnings.

## 주요 흐름

구조화 profile을 우선하고 StyleReference RAG는 비슷한 상황의 승인/수정 사례를 보조한다. 결과는 Edit Planner의 pace/content 제약과 Creative Agent의 표현 정책으로 전달한다.

## Memory 정책

수정은 기본적으로 ProjectStyle에만 반영한다. `앞으로 모든 영상에 적용`을 사용자가 선택하면 Profile Update Proposal을 만들고 확인 후 UserStyleProfile을 변경한다.

## 실패 처리

프로필이 없으면 ProjectStyle/SystemDefault로 구조화된 ResolvedStyle을 만든다. 충돌이 해소되지 않거나 중요 지시가 모호하면 User Decision을 요청한다.

## 하지 않는 일

실제 Caption/BGM/Color 실행, font path/filter numeric value 생성, 사용자 승인 없는 장기 Profile 수정을 하지 않는다.

## 향후 확장

Profile confidence, explicit negative preference, multi-context profiles, preference drift review는 후속 설계 대상이다.
