# Creative Agent

## 목적

EditPlan의 Creative Intent와 ResolvedStyle을 Caption, BGM, Color, Transition/Effect, SFX의 구체적이고 검증 가능한 CreativePlan으로 변환한다.

## 책임

- Caption Planning
- BGM Planning
- Color Planning
- Transition/Effect/SFX Planning
- 장면·에피소드 간 스타일 일관성
- Approved Catalog resource ID 선택

## 입력

EditPlan/SceneEditPlan, CreativeIntent, ResolvedStyle, Transcript, SceneContext, Approved Font/BGM/SFX/ColorPreset catalogs, BGM retrieval result.

## 출력

CreativePlan version, CaptionPlan, BGMPlan, ColorPlan, Transition/SFX plan, resource IDs, timing/ducking/fade parameters, warnings.

Caption type은 `DIALOGUE`, `REACTION`, `EMPHASIS`, `CONTEXT`, `LOCATION`, `TIME`, `EDITORIAL`, `SOUND_EFFECT`를, source는 `TRANSCRIPT`, `USER`, `AI_GENERATED`를 구분한다.

## BGM / Color / Font 정책

BGM은 구간별 mood, genre, energy, volume, ducking, fade in/out을 계획하되 Approved BGM Catalog에서만 선택한다. Font는 Approved Font Catalog의 ID를 사용한다. Color는 `WARM_NATURAL`, `COOL_CLEAN`, `BRIGHT_VLOG`, `SOFT_FILM`, `NIGHT_WARM` 같은 검증된 preset과 제한적 adjustment만 사용한다.

## 주요 흐름

초기 Full Design에서 Caption/BGM/Color Planning은 상위 Creative Agent가 조율한다. 개별 domain이 복잡해지면 하위 Agent로 분리할 수 있지만, 현재 설계에서 고정하지 않는다.

## 실패 처리

BGM 검색/선택 실패는 BGM 없이 계속하고 warning을 남긴다. Color enhancement/SFX 실패도 core edit를 실패시키지 않는다. 라이선스 부적합 resource는 deterministic validator가 거부한다.

## 다른 Component와의 관계

Style Agent의 정책과 Edit Planner의 의도를 소비하고 Tool Layer에 실행 계획을 제공한다. Reviewer의 STYLE issue와 사용자의 표현 수정은 해당 CreativePlan/Preview만 재계산한다.

## 하지 않는 일

Scene 선택/순서를 바꾸거나 arbitrary font path, BGM file, FFmpeg filter numeric value를 생성하지 않는다. 라이선스 적격성을 추측하지 않는다.

## 향후 확장

Caption/BGM/Color 하위 Agent 분리와 고급 effect grammar는 실제 복잡도가 필요성을 보일 때 검토한다.
