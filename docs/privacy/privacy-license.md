# Privacy and License Design

## 목적

개인 영상·음성·취향을 최소한으로 수집·전송·보존하고, Creative resource의 라이선스 적격성을 AI 추측이 아닌 구조화 데이터로 검증한다.

## Privacy 원칙

1. Data Minimization
2. Local-first Processing
3. Temporary-by-default
4. Explicit Long-term Memory
5. Least-Privilege Agent Context
6. External Provider 최소 전송
7. Traceability

## External Provider 정책

전체 MOV/WAV 전송은 기본 금지한다. 필요할 때 transcript excerpt, selected low-resolution frame, contact sheet, structured scene context만 전송한다. Agent별 필요한 user/project data만 제공하고 provider/model, 전송 유형, 시각, purpose, retention policy reference를 추적한다.

## Temporary / Long-term Data

WAV/frame/contact sheet/intermediate clip은 temporary workspace에서 처리 완료/취소/TTL 정책으로 삭제한다. UserStyleProfile과 StyleReference의 장기 저장은 사용자의 명시적 선택을 필요로 한다.

## Approved Creative Catalog

FontCatalog, BGMCatalog, SFXCatalog, ColorPresetCatalog만 Creative Agent/Tool이 사용한다. Font/BGM/SFX resource는 다음 메타데이터를 갖는다.

- `license_type`
- `license_url`
- `commercial_use`
- `redistribution_allowed`
- `attribution_required`
- `attribution_text`
- `license_verified_at`
- `status`

Creative suitability는 AI가 판단할 수 있지만 license eligibility는 DB Validator가 판단한다.

## 주요 흐름

1. Creative Agent가 catalog resource ID를 제안한다.
2. Validator가 project purpose, commercial use, redistribution, attribution, status를 검증한다.
3. 부적합/unknown이면 실행을 거부하고 다른 approved resource 또는 resource 없는 계획을 요청한다.
4. Final output에 필요한 attribution을 연결한다.

## Logging / Lineage

resource ID, policy decision, provider, execution reference는 기록하되 API key, auth header, full prompt, frame/video/audio binary는 log에 저장하지 않는다.

## 실패 처리

라이선스가 불확실하면 사용 가능으로 추측하지 않고 거부/decision으로 전환한다. Optional BGM/SFX 실패는 해당 resource 없이 계속하고 warning을 남긴다. Privacy scope violation은 critical failure로 다룬다.

## 하지 않는 일

- Vector similarity/LLM으로 license eligibility 판단
- arbitrary font/music/SFX path 사용
- 동의 없는 장기 행동 메모리 생성
- 불필요한 전체 원본 외부 전송

## 향후 확장

정확한 retention, deletion/export UX, encryption, regional storage, provider DPA, child/bystander data policy는 법적·운영 검토로 확정한다.
