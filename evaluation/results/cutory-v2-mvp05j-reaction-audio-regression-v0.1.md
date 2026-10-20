# MVP-05J Reaction Cue + Audio Activity 회귀 검증

이 문서는 Autonomous Discovery의 결정적 Evidence 결합 규칙에 대한 media-free 회귀 검증 기록이다. 실제 촬영 영상의 추천 정확도나 P1~P3 focused evaluation 결과가 아니다.

## 변경 근거와 범위

이전 규칙은 `TRANSCRIPT_REACTION_CUE`와 Audio modality가 겹치면 `REACTION_CUE_PLUS_AUDIO`를 생성했다. 짧은 `SILENCE`도 Audio modality이므로 발화 전 무음이 반응 단서의 보강 근거가 될 수 있었다. MVP-05I의 격리 합성 입력에서 이 경로를 관찰했다.

변경 후에는 이 조합에 `AUDIO_ACTIVITY`가 필요하다. `SILENCE` Evidence 자체와 저장 방식, `TRANSCRIPT_STRUCTURE_PLUS_AUDIO`, `AUDIO_PLUS_VISUAL_ACTIVITY`, STT 및 Visual 설정은 바꾸지 않았다. Promotion config version만 `autonomous-promotion-v0.2`로 구별하여 동일 입력의 종전 완료 결과를 새 규칙의 결과로 오인 재사용하지 않는다.

## 검증 범위

- Reaction Cue + SILENCE만 겹침: 해당 조합 후보 없음.
- Reaction Cue + AUDIO_ACTIVITY 겹침: 기존 조합 후보 유지.
- Reaction Cue + AUDIO_ACTIVITY 시간 불일치: 후보 없음.
- 두 다른 허용 Evidence 조합: 후보 유지.
- SILENCE와 AUDIO_ACTIVITY가 모두 있을 때: 활동 구간의 후보만 생성.
- SILENCE Evidence는 분석 결과에 저장되고, SILENCE만 있는 Source의 active 후보 조회는 비어 있음.

검증은 합성 Evidence와 인메모리 DB 기반 `unittest`로 수행했다. `TMPDIR=/private/tmp` 환경에서 전체 559개 테스트가 통과했고 29개는 건너뛰었다. Scene API·편집 계획·렌더링 관련 47개도 별도 실행해 통과했다. 실제 촬영 미디어나 Semantic Provider는 실행하지 않았다. 비음성 STT 오인식은 이 변경으로 해결되지 않으며 별도 평가가 필요하다.
