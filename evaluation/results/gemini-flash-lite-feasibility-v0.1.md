# Gemini Flash-Lite Vision Feasibility v0.1

## 목적

동일한 synthetic Contact Sheet payload를 사용해 `gemini-3.1-flash-lite`가 이미지 입력, JSON Structured Output, proposal abstain 및 deterministic validator 경로를 실제로 처리할 수 있는지 확인했다. 이 실험은 모델 선택 정확도 평가가 아니라 Provider/model 실행 가능성 확인이다.

## 고정 조건

- Run ID: `gemini-vlm-contact-sheet-flash-lite-smoke-v0.1-run1`
- Provider: Gemini API
- Model: `gemini-3.1-flash-lite`
- Proposal: 3개
- Logical source frames: 9개
- 실제 image input: synthetic horizontal contact sheet 3장
- Structured Output: `response_mime_type="application/json"` + `response_json_schema`
- Validator: 기존 deterministic proposal validator
- 명시적 재시도: 없음
- Ground Truth 및 실제 eval frame: 사용하거나 전송하지 않음

외부로 전송한 데이터는 synthetic Contact Sheet, synthetic EditMemo, synthetic selected block text, proposal ID 및 proposal start/end뿐이다. API key, 로컬 경로, 원본 MOV/WAV, Ground Truth, 평가 지표는 전송 payload나 결과 기록에 포함하지 않았다.

## 결과

| 항목 | 결과 |
| --- | --- |
| Application-level API 호출 | 1회 |
| Provider error | 없음 |
| Structured Output | 성공 |
| Deterministic validator | 성공 |
| Selected proposal | 없음 — 정상 abstain |
| Reasoning code | `INSUFFICIENT_VISUAL_EVIDENCE` |
| Latency | 6.5525초 |
| Input tokens | 3,795 |
| Output tokens | 73 |
| Total tokens | 3,868 |

Reasoning summary는 synthetic placeholder 이미지가 물체 낙하 transcript와 관련된 시각 정보를 포함하지 않아 proposal을 선택할 근거가 부족하다는 내용이었다. 입력과 무관한 proposal을 강제로 고르지 않은 정상 abstain으로 해석한다.

결과는 ignored runtime JSONL에 즉시 저장하고 다시 읽어 복구 가능함을 확인했다. JSONL 원본은 Git에 포함하지 않는다.

## Gemini 3.5 Flash와의 실행 가능성 비교

- `gemini-3.5-flash`: 독립 synthetic Smoke 2회 모두 HTTP 503 `UNAVAILABLE`, Structured Output 이전 실패
- `gemini-3.1-flash-lite`: 동일 표현의 synthetic Smoke 1회 성공, Structured Output과 validator 완료

이 결과는 `gemini-3.1-flash-lite`의 synthetic payload 처리 가능성만 확인한다. 1회 결과로 Provider 안정성이나 선택 정확도 우위를 일반화하지 않는다.
