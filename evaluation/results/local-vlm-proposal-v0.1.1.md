# Local VLM Proposal Selector Evaluation v0.1.1

## 1. 실험 목적과 실행 조건

v0.1에서 확인된 마지막 selected block의 proposal boundary bug를 수정하고 Provider 오류 진단을 보강한 뒤, 동일한 Local VLM 조건에서 `eval_01`~`eval_05`를 다시 평가했다. 이 실험은 proposal 준비 복구 효과와 현재 payload가 Mac native Ollama에서 실제 선택 단계까지 실행 가능한지를 측정한다.

- 공식 Run ID: `local-vlm-eval-v0.1.1-run2`
- Runtime: Mac native Ollama
- Endpoint: `http://localhost:11434`
- Model: `qwen3-vl:4b`
- `num_ctx`: 16,384
- Temperature: 0.0
- Prompt, proposal 종류, frame sampling: v0.1과 동일
- 재시도 및 fallback: 없음
- 완료 레코드: 5/5
- 실제 Ollama 요청: 5회, Test별 1회

최초 `run1` 시도는 실행 샌드박스의 localhost 격리로 Test 01·02가 Ollama에 도달하지 못해 중단했으며 공식 평가에서 제외했다. 호스트 localhost 접근이 가능한 실행에서 새 `run2`를 사용했고, 기존 run ID와 결과는 재사용하거나 덮어쓰지 않았다.

각 Test 결과는 API terminal outcome 직후 `evaluation/tmp/local-vlm-proposal-run.jsonl`에 append하고 `flush`와 `fsync`를 수행했다. Ground Truth는 VLM 요청에 포함하지 않고 VLM 요청 이후 Proposal Oracle과 Candidate 평가에만 사용했다.

## 2. 입력과 개인정보 경계

VLM에는 EditMemo transcript, selected block text, 중립 proposal ID와 start/end, proposal별 대표 JPEG 3장만 전달했다. Ground Truth, IoU, Coverage, Boundary Error, oracle, proposal kind, 기존 winner, 원본 MOV/WAV는 전달하지 않았다.

VLM 출력은 기존 proposal ID 또는 명시적인 abstain만 허용한다. VLM이 timestamp를 생성하는 필드는 없으며 Python validator만 저장된 proposal timestamp를 `SceneCandidate`로 변환한다.

## 3. 전체 실행 결과

| Test | Proposals | Images | Provider outcome | HTTP | Stage | Timeout | Structured | Valid selection |
| --- | ---: | ---: | --- | ---: | --- | --- | --- | --- |
| 01 | 4 | 12 | `TIMEOUT` | N/A | `provider_request` | yes | 실패 | 없음 |
| 02 | 6 | 18 | `HTTP_400` / context 초과 | 400 | `provider_request` | no | 실패 | 없음 |
| 03 | 6 | 18 | `HTTP_400` / context 초과 | 400 | `provider_request` | no | 실패 | 없음 |
| 04 | 4 | 12 | `TIMEOUT` | N/A | `provider_request` | yes | 실패 | 없음 |
| 05 | 4 | 12 | `TIMEOUT` | N/A | `provider_request` | yes | 실패 | 없음 |

- Proposal preparation 성공: 5/5 (100%)
- Provider/Structured Output 성공: 0/5 (0%)
- Valid proposal selection: 0/5 (0%)
- Invalid interval: 0건
- GT prompt 포함: 0건
- 자유 timestamp 생성: 0건
- Abstain: 0건 — Structured Output 전에 모두 종료됨

## 4. Test별 결과

### Test 01

- Fixed selected block: `block-0002`, 12.70~13.18초
- Ground Truth: 10.0~15.0초
- Proposal / image count: 4 / 12
- Provider 호출: 1회
- 결과: 120.0092초 후 timeout
- Provider code / stage: `TIMEOUT` / `provider_request`
- Structured Output / validator: 실패 전 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: Provider 응답 전 timeout으로 N/A
- Proposal Oracle: `proposal-003`, IoU 0.8475, Coverage 1.0000, Total Error 0.90초

v0.1에서 실패했던 마지막 block proposal 준비는 해결됐다. Raw보다 GT에 가까운 Context 계열 proposal이 집합 안에 있었지만 VLM 응답이 없어 실제 선택 여부는 확인하지 못했다.

### Test 02

- Fixed selected block: `block-0001`, 3.04~10.96초
- Ground Truth: 7.0~11.0초
- Proposal / image count: 6 / 18
- Provider 호출: 1회
- 결과: HTTP 400, 1.0599초
- 안전한 Provider message: 요청 19,392 tokens가 `num_ctx=16,384`를 초과
- Provider code / stage: `HTTP_400` / `provider_request`
- Structured Output / validator: 실패 전 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 정상 응답 usage가 없어 N/A
- Proposal Oracle: `proposal-005` (`LAST_SEGMENT`, 5.86~10.96초), IoU 0.7704, Coverage 0.9900, Total Error 1.18초

핵심 oracle proposal은 v0.1과 동일하게 존재했지만 context 초과로 VLM이 이를 선택하는지 평가하지 못했다.

### Test 03

- Fixed selected block: `block-0002`, 7.52~22.26초
- Ground Truth: 6.0~23.0초
- Proposal / image count: 6 / 18
- Provider 호출: 1회
- 결과: HTTP 400, 0.3526초
- 안전한 Provider message: 요청 19,455 tokens가 `num_ctx=16,384`를 초과
- Provider code / stage: `HTTP_400` / `provider_request`
- Structured Output / validator: 실패 전 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: 정상 응답 usage가 없어 N/A
- Proposal Oracle: `proposal-002`, IoU 0.9072, Coverage 1.0000, Total Error 1.74초

긴 이야기의 Raw/Context 유지 여부나 짧은 proposal 과선택 여부는 Structured Output 부재로 확인하지 못했다.

### Test 04

- Fixed selected block: `block-0002`, 8.08~10.56초
- Ground Truth: 7.0~11.0초
- Proposal / image count: 4 / 12
- Provider 호출: 1회
- 결과: 120.0062초 후 timeout
- Provider code / stage: `TIMEOUT` / `provider_request`
- Structured Output / validator: 실패 전 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: Provider 응답 전 timeout으로 N/A
- Proposal Oracle: `proposal-004`, IoU 0.6923, Coverage 0.9450, Total Error 1.68초

관련 짧은 사건을 포함하는 proposal은 존재했지만 실제 선택 성능은 측정하지 못했다.

### Test 05

- Fixed selected block: `block-0003`, 22.48~24.90초
- Ground Truth: 20.0~26.0초
- Proposal / image count: 4 / 12
- Provider 호출: 1회
- 결과: 120.0119초 후 timeout
- Provider code / stage: `TIMEOUT` / `provider_request`
- Structured Output / validator: 실패 전 미실행
- Selected proposal, Candidate, IoU, Coverage, Boundary Error: N/A
- Token usage: Provider 응답 전 timeout으로 N/A
- Proposal Oracle: `proposal-002`, IoU 0.8070, Coverage 0.9200, Total Error 1.32초

Padding proposal이 Raw보다 reaction 전후 구간을 더 잘 포함할 가능성은 oracle로 확인됐지만 VLM 선택 결과는 없다.

## 5. Proposal Oracle과 VLM 선택 차이

Proposal Oracle은 GT를 본 사후 참고치이며 자동 선택 성능이 아니다. 이번 Run은 선택 결과가 전혀 없어 “VLM이 oracle과 다른 proposal을 선택했다”가 아니라 “Provider 실행 제약 때문에 선택 비교 자체가 불가능했다”가 정확한 결론이다.

| Test | Oracle proposal | Oracle IoU | Oracle Coverage | Oracle Total Error | VLM selection |
| --- | --- | ---: | ---: | ---: | --- |
| 01 | proposal-003 | 0.8475 | 1.0000 | 0.90초 | 없음 — timeout |
| 02 | proposal-005 | 0.7704 | 0.9900 | 1.18초 | 없음 — context 초과 |
| 03 | proposal-002 | 0.9072 | 1.0000 | 1.74초 | 없음 — context 초과 |
| 04 | proposal-004 | 0.6923 | 0.9450 | 1.68초 | 없음 — timeout |
| 05 | proposal-002 | 0.8070 | 0.9200 | 1.32초 | 없음 — timeout |

Oracle median IoU는 0.8070, median Coverage는 0.9900, median Total Error는 1.32초다. 이는 proposal 집합의 상한 참고치일 뿐 실제 시스템 성능이 아니다.

## 6. 기존 결과와 비교

Fixed Window와 Proposal Oracle은 Ground Truth를 본 사후 oracle이며 실제 자동 선택 결과가 아니다.

| Test | Raw IoU / Total Error | Audio v0.1 | Visual v0.1 | Local VLM v0.1 | Local VLM v0.1.1 | Proposal Oracle IoU | Fixed Window oracle IoU |
| --- | ---: | ---: | ---: | --- | --- | ---: | ---: |
| 01 | 0.0960 / 4.52 | 0.1200 / 4.40 | N/A | 준비 실패 | timeout | 0.8475 | 0.7241 |
| 02 | 0.4975 / 4.00 | 0.0000 / 7.82 | N/A | Provider 실패 | context 초과 | 0.7704 | 0.1333 |
| 03 | 0.8671 / 2.26 | 0.3224 / 11.52 | 0.1059 / 15.20 | 준비 실패 | context 초과 | 0.9072 | 0.6554 |
| 04 | 0.6200 / 1.52 | 0.3800 / 2.48 | 0.1500 / 3.40 | 준비 실패 | timeout | 0.6923 | 0.1333 |
| 05 | 0.4033 / 3.58 | 0.4400 / 3.36 | N/A | 준비 실패 | timeout | 0.8070 | 0.6082 |

v0.1.1은 proposal preparation을 1/5에서 5/5로 복구했다. 그러나 Provider/Structured Output 성공률은 여전히 0%이므로 Raw, Audio, Visual과 실제 selected Candidate 지표를 비교할 수 없다.

## 7. Latency와 Token Usage

- Test별 latency: 120.0092, 1.0599, 0.3526, 120.0062, 120.0119초
- 5개 요청 평균 latency: 72.2876초
- Median latency: 120.0062초
- Timeout: 3/5
- HTTP 400 context 초과: 2/5
- 정상 응답 기준 input/output/total token usage: 모두 N/A
- 오류 메시지에서 확인된 prompt token: Test 02 19,392, Test 03 19,455

오류 메시지의 prompt token은 정상 API usage 필드가 아니므로 총 token usage로 합산하지 않았다.

## 8. 사전 성공 기준 판정

| 기준 | 결과 | 판정 |
| --- | --- | --- |
| Proposal preparation 5/5 | 5/5 | 통과 |
| Provider/Structured Output 최소 4/5 | 0/5 | 실패 |
| Valid proposal 선택 최소 3/5 | 0/5 | 실패 |
| Invalid interval 0건 | 0건 | 통과 |
| GT prompt 포함 0건 | 0건 | 통과 |
| 자유 timestamp 생성 0건 | 0건 | 통과 |
| Test 01 또는 05 Raw 대비 IoU·Coverage 공동 개선 | 선택 Candidate 없음 | 평가 불가/실패 |
| Test 02 Raw IoU 0.4975를 크게 훼손하지 않음 | 선택 Candidate 없음 | 평가 불가/실패 |
| Selected median IoU 상승 | selected 결과 없음 | 평가 불가/실패 |
| Selected median Total Error 감소 | selected 결과 없음 | 평가 불가/실패 |

Local VLM Proposal Selector v0.1.1은 전체 사전 성공 기준에 **미달**이다. 이번 버전에서 입증된 개선은 proposal preparation bug 해소뿐이다.

## 9. 실패 원인 분리와 다음 단계

v0.1.1에서는 proposal 집합 자체가 모든 Test에 생성됐고 각 Test에 Raw보다 높은 IoU의 oracle proposal이 존재했다. 따라서 이번 실패는 proposal 생성 실패가 아니라 현재 고정 payload와 local Provider 실행 한계다.

- 6 proposals × 3 images인 Test 02·03은 현재 16,384 context에 들어가지 않는다.
- 4 proposals × 3 images인 Test 01·04·05는 context 오류 대신 120초 timeout으로 끝났다.
- Structured Output 이전 실패이므로 `qwen3-vl:4b`의 의미 선택 품질은 여전히 측정되지 않았다.

현재 결과만으로 OpenAI/Gemini Vision의 선택 품질과 Local VLM을 비교하는 것은 이르다. 비교 전에 별도 버전의 실험으로 payload/context/timeout 실행 가능성을 명시적으로 다루거나, 동일 입력을 수용하는 외부 Provider를 실행 가능성 기준으로 비교해야 한다. 어느 경우든 이번 v0.1.1 결과를 보고 같은 버전 설정을 변경해서는 안 된다.

## 10. 의도적으로 하지 않은 것

- 실패 Test 재시도 또는 fallback
- Model, prompt, `num_ctx`, temperature 변경
- Proposal 종류·수, ±2초 padding 변경
- Frame 수·해상도·sampling 변경
- Ground Truth, oracle, 평가 지표, proposal kind를 VLM 입력에 포함
- Gemini/OpenAI Vision 호출
- Raw/Audio/Visual/Fixed Window Baseline 변경
- Provider 실패나 abstain을 IoU 0으로 변환
- 기존 v0.1 평가 문서 수정
- 커밋 또는 푸시
