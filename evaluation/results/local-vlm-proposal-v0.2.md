# Local VLM Proposal Selector Evaluation v0.2

## 1. 실험 목적과 고정 조건

Local VLM Proposal v0.1.1은 모든 Test에서 유효한 proposal 집합을 만들었지만 12장 입력은 timeout, 18장 입력은 `num_ctx=16,384`를 초과해 선택 품질을 측정하지 못했다. v0.2는 proposal별 10%·50%·90% frame을 한 장의 수평 contact sheet로 결합해 시각적 시점은 유지하면서 실제 VLM 이미지 수를 줄였을 때 eval_01~05가 실행 가능한지 평가한다.

- Run ID: `local-vlm-eval-v0.2-run1`
- Runtime: Mac native Ollama
- Endpoint: `http://localhost:11434`
- Model: `qwen3-vl:4b`
- `num_ctx`: 16,384
- Temperature: 0.0
- Prompt와 Structured Output: v0.2 Smoke Test와 동일
- Proposal generator, selected block, evaluator: v0.1.1과 동일
- 재시도 및 fallback: 없음
- 완료 레코드: 5/5
- 실제 Ollama 요청: Test별 1회, 총 5회

Ground Truth, 평가 지표, Proposal Oracle, proposal kind, 기존 winner, 원본 MOV/WAV는 VLM에 전달하지 않았다. Ground Truth는 VLM selection과 deterministic validator 이후 사후 평가와 Proposal Oracle에만 사용했다.

## 2. Contact Sheet 구조

각 proposal의 기존 10%·50%·90% JPEG를 왼쪽부터 early·middle·late 순서로 FFmpeg `hstack`한 contact sheet 한 장으로 전달했다.

```text
[ early 10% ][ middle 50% ][ late 90% ]
```

원본 세 frame의 proposal ID, frame ID, timestamp는 local manifest에 유지했다. Validator는 proposal ID, 정확히 세 source frame, ID 순서, 10/50/90% timestamp와 non-empty JPEG를 검사한다. 최종 Candidate timestamp는 VLM 출력이 아니라 저장된 proposal에서만 가져온다.

| Test | Proposal | Logical frames | v0.1.1 images | v0.2 images | 감소율 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 01 | 4 | 12 | 12 | 4 | 66.67% |
| 02 | 6 | 18 | 18 | 6 | 66.67% |
| 03 | 6 | 18 | 18 | 6 | 66.67% |
| 04 | 4 | 12 | 12 | 4 | 66.67% |
| 05 | 4 | 12 | 12 | 4 | 66.67% |

## 3. 전체 실행 결과

| Test | Proposals | Logical / actual images | Provider outcome | Stage | Structured | Validator | Selection |
| --- | ---: | ---: | --- | --- | --- | --- | --- |
| 01 | 4 | 12 / 4 | 120초 timeout | `provider_request` | 실패 | 미실행 | 없음 |
| 02 | 6 | 18 / 6 | 120초 timeout | `provider_request` | 실패 | 미실행 | 없음 |
| 03 | 6 | 18 / 6 | 120초 timeout | `provider_request` | 실패 | 미실행 | 없음 |
| 04 | 4 | 12 / 4 | 120초 timeout | `provider_request` | 실패 | 미실행 | 없음 |
| 05 | 4 | 12 / 4 | 120초 timeout | `provider_request` | 실패 | 미실행 | 없음 |

- Proposal preparation: 5/5 성공
- Provider/Structured Output 성공: 0/5
- Valid proposal selection: 0/5
- Context error: 0/5
- Timeout: 5/5
- Invalid interval: 0건
- GT prompt 포함: 0건
- 자유 timestamp 생성: 0건
- Abstain: 0건 — Structured Output 전에 종료됨

## 4. Test별 상세 결과

### Test 01

- Fixed block: `block-0002`, 12.70~13.18초
- GT: 10.0~15.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- Provider 호출: 1회
- 결과: `TIMEOUT`, 120.0057초
- HTTP status: 없음
- Structured Output / validator: 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 응답 전 timeout으로 N/A
- Oracle: `proposal-003`, IoU 0.8475, Coverage 1.0000, Total Error 0.90초

Motion과 reaction을 연결하는 더 좋은 proposal은 집합 안에 있었지만 실제 VLM 선택 여부는 확인하지 못했다.

### Test 02

- Fixed block: `block-0001`, 3.04~10.96초
- GT: 7.0~11.0초
- Proposal / logical frame / actual image: 6 / 18 / 6
- Provider 호출: 1회
- 결과: `TIMEOUT`, 120.0059초
- HTTP status: 없음
- Structured Output / validator: 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 응답 전 timeout으로 N/A
- Oracle: `proposal-005` (`LAST_SEGMENT`, 5.86~10.96초), IoU 0.7704, Coverage 0.9900, Total Error 1.18초

v0.1.1의 19,392-token context 초과는 발생하지 않았지만 VLM이 `LAST_SEGMENT`를 선택하기 전에 timeout됐다.

### Test 03

- Fixed block: `block-0002`, 7.52~22.26초
- GT: 6.0~23.0초
- Proposal / logical frame / actual image: 6 / 18 / 6
- Provider 호출: 1회
- 결과: `TIMEOUT`, 120.0099초
- HTTP status: 없음
- Structured Output / validator: 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 응답 전 timeout으로 N/A
- Oracle: `proposal-002`, IoU 0.9072, Coverage 1.0000, Total Error 1.74초

긴 이야기 전체를 유지하는지 또는 일부 proposal을 과선택하는지는 평가하지 못했다.

### Test 04

- Fixed block: `block-0002`, 8.08~10.56초
- GT: 7.0~11.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- Provider 호출: 1회
- 결과: `TIMEOUT`, 120.0091초
- HTTP status: 없음
- Structured Output / validator: 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 응답 전 timeout으로 N/A
- Oracle: `proposal-004`, IoU 0.6923, Coverage 0.9450, Total Error 1.68초

짧은 위험 사건 proposal의 의미 선택은 확인하지 못했다.

### Test 05

- Fixed block: `block-0003`, 22.48~24.90초
- GT: 20.0~26.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- Provider 호출: 1회
- 결과: `TIMEOUT`, 120.0063초
- HTTP status: 없음
- Structured Output / validator: 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 응답 전 timeout으로 N/A
- Oracle: `proposal-002`, IoU 0.8070, Coverage 0.9200, Total Error 1.32초

Reaction 전후를 포함하는 padding proposal은 존재하지만 실제 선택 결과는 없다.

## 5. Proposal Oracle과 VLM 선택

Proposal Oracle과 Fixed Window oracle은 GT를 본 사후 참고치이며 실제 자동 선택 성능이 아니다.

| Test | Oracle proposal | Oracle IoU | Oracle Coverage | Oracle Total Error | VLM selection |
| --- | --- | ---: | ---: | ---: | --- |
| 01 | proposal-003 | 0.8475 | 1.0000 | 0.90초 | 없음 — timeout |
| 02 | proposal-005 | 0.7704 | 0.9900 | 1.18초 | 없음 — timeout |
| 03 | proposal-002 | 0.9072 | 1.0000 | 1.74초 | 없음 — timeout |
| 04 | proposal-004 | 0.6923 | 0.9450 | 1.68초 | 없음 — timeout |
| 05 | proposal-002 | 0.8070 | 0.9200 | 1.32초 | 없음 — timeout |

선택이 없으므로 VLM과 Oracle의 proposal ID 차이 또는 metric 차이를 계산할 수 없다. Provider failure를 IoU 0으로 변환하지 않았다.

## 6. 기존 Baseline 비교

| Test | Raw IoU / Total Error | Audio v0.1 | Visual v0.1 | Local VLM v0.1 | VLM v0.1.1 | VLM v0.2 | Proposal Oracle IoU | Fixed oracle IoU |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: |
| 01 | 0.0960 / 4.52 | 0.1200 / 4.40 | N/A | 준비 실패 | timeout | timeout | 0.8475 | 0.7241 |
| 02 | 0.4975 / 4.00 | 0.0000 / 7.82 | N/A | Provider 실패 | context 초과 | timeout | 0.7704 | 0.1333 |
| 03 | 0.8671 / 2.26 | 0.3224 / 11.52 | 0.1059 / 15.20 | 준비 실패 | context 초과 | timeout | 0.9072 | 0.6554 |
| 04 | 0.6200 / 1.52 | 0.3800 / 2.48 | 0.1500 / 3.40 | 준비 실패 | timeout | timeout | 0.6923 | 0.1333 |
| 05 | 0.4033 / 3.58 | 0.4400 / 3.36 | N/A | 준비 실패 | timeout | timeout | 0.8070 | 0.6082 |

v0.2는 v0.1.1의 context 초과 2건을 제거했지만 실제 selected Candidate 성능은 여전히 측정하지 못했다.

## 7. Latency와 Token Usage

- Latency: 120.0057, 120.0059, 120.0099, 120.0091, 120.0063초
- 평균 latency: 120.0074초
- Median latency: 120.0063초
- 정상 응답 input/output/total token usage: 5건 모두 N/A
- 실제 VLM image: v0.1.1 대비 모든 Test에서 66.67% 감소

v0.1.1의 평균 latency 72.2880초에는 Test 02·03의 빠른 HTTP 400 응답이 포함돼 있으므로 단순 평균 비교는 오해를 낳는다. 같은 timeout 유형인 Test 01·04·05는 두 버전 모두 약 120초였다. v0.2는 context 실행 가능성은 개선했지만 real eval latency를 timeout 아래로 줄이지 못했다.

## 8. 사전 성공 기준 판정

| 기준 | 결과 | 판정 |
| --- | --- | --- |
| Proposal preparation 5/5 | 5/5 | 통과 |
| Provider/Structured Output 최소 4/5 | 0/5 | 실패 |
| Valid proposal 선택 최소 3/5 | 0/5 | 실패 |
| Invalid interval 0건 | 0건 | 통과 |
| GT prompt 포함 0건 | 0건 | 통과 |
| 자유 timestamp 생성 0건 | 0건 | 통과 |
| Test 01/05 중 하나 Raw 대비 IoU·Coverage 공동 개선 | 선택 Candidate 없음 | 평가 불가/실패 |
| Test 02 Raw IoU 0.4975를 크게 악화하지 않음 | 선택 Candidate 없음 | 평가 불가/실패 |
| Selected median IoU 상승 | 선택 없음 | 평가 불가/실패 |
| Selected median Total Error 감소 | 선택 없음 | 평가 불가/실패 |
| v0.1.1 대비 context/latency 실행 가능성 개선 | context 오류 2→0, timeout 3→5 | 부분 통과 |

전체 성공 기준은 **미달**이다.

## 9. 실패 단계 구분과 Local VLM 한계

- Proposal generation failure: 0건
- Contact sheet/manifest failure: 0건
- Context-size failure: 0건
- Provider timeout: 5건
- Structured Output failure 이후 validator failure: 0건 — 해당 단계에 도달하지 못함
- Selection failure 또는 잘못된 proposal 선택: 평가 불가

Contact sheet는 synthetic 3-proposal Smoke에서 input tokens와 latency를 크게 줄였지만 실제 eval의 4~6 proposal에서는 120초 제한 안에 응답을 만들지 못했다. 로컬 처리의 개인정보 장점과 외부 API 비용 없음은 유지되지만, 현재 Mac native `qwen3-vl:4b` 구성은 실제 평가 payload의 latency 요구를 충족하지 못한다.

## 10. 외부 Vision 비교 필요성

OpenAI/Gemini Vision과의 비교 근거는 생겼다. 이번 비교의 우선 질문은 선택 품질 이전에 동일 contact-sheet payload의 실행 성공률, latency, token/image 비용과 개인정보 정책이다. 외부 Provider 비교에서도 proposal ID만 선택하게 하고 GT·oracle·원본 MOV/WAV를 보내지 않으며 동일 validator를 재사용해야 한다.

다만 이 문서는 Provider 변경을 구현하거나 호출하지 않는다. 데이터가 5개뿐이고 Local VLM의 의미 선택 결과가 0건이므로 모델 품질의 우열을 주장할 수 없다.

## 11. 의도적으로 하지 않은 것

- Timeout Test 재시도 또는 fallback
- Model, `num_ctx`, temperature, timeout 변경
- Prompt, proposal 종류·수·padding 변경
- Frame sampling 또는 contact-sheet layout 변경
- Ground Truth, oracle, 평가 지표, proposal kind를 VLM 입력에 포함
- Gemini/OpenAI 호출
- 기존 Baseline과 평가 문서 덮어쓰기
- Provider failure를 IoU 0으로 변환
- 커밋 또는 push
