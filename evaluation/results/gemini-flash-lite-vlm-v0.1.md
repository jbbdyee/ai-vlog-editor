# Gemini Flash-Lite VLM Proposal Selector Evaluation v0.1

## 1. 실험 목적과 고정 조건

현재 5개 Evaluation Dataset v0.1에서 Contact Sheet proposal을 `gemini-3.1-flash-lite`가 안정적으로 처리하고, 기존 deterministic proposal 중 EditMemo와 선택 transcript block에 관련된 proposal ID를 고를 수 있는지 평가한다. 이 평가는 일반적인 모델 우위를 주장하지 않으며 Provider feasibility, selection yield와 실패 유형을 확인한다.

- Run ID: `gemini-flash-lite-vlm-eval-v0.1-run1`
- Provider / model: Gemini API / `gemini-3.1-flash-lite`
- Prompt와 Structured Output: Flash-Lite feasibility Smoke와 동일
- Contact Sheet: proposal별 10%·50%·90% frame을 early·middle·late 순서로 수평 결합
- Proposal generator, selected block, validator, evaluator: Local VLM Contact Sheet v0.2와 동일
- Application-level 요청: Test별 최대 1회, 총 5회
- 명시적 retry와 fallback: 없음
- 완료 레코드: 5/5, Test별 append·flush·fsync 후 복구 확인

Ground Truth, IoU, Coverage, Boundary Error, Proposal Oracle, Fixed Window oracle, proposal kind와 기존 winner는 Gemini에 전달하지 않았다. Gemini가 출력한 것은 proposal ID 또는 abstain과 제한된 reasoning뿐이며 Candidate timestamp는 local proposal manifest에서만 가져왔다.

## 2. 외부 전송 범위와 개인정보 주의점

각 Test에서 Gemini API로 전송한 데이터는 EditMemo text, selected block ID/text, proposal ID/start/end 및 proposal별 Contact Sheet JPEG 한 장이다. Contact Sheet는 왼쪽부터 10%·50%·90% frame이며 기존 metadata 제거 정책을 유지했다.

원본 MOV, 전체 WAV, 불필요한 원본 frame, 로컬 파일 경로, Ground Truth, 평가 지표, oracle, API key는 전송하지 않았다. 다만 실제 eval frame의 픽셀은 Contact Sheet 형태로 외부 Provider에 전송됐으므로 향후 실제 사용자 데이터 적용 전에는 Provider 저장·학습·보존 정책을 별도로 검토해야 한다.

## 3. 전체 결과

| Test | Proposals | Logical / actual images | Selection outcome | Structured | Validator | Candidate | IoU | Coverage | Total Error |
| --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | ---: |
| 01 | 4 | 12 / 4 | abstain: `INSUFFICIENT_VISUAL_EVIDENCE` | 성공 | 성공 | N/A | N/A | N/A | N/A |
| 02 | 6 | 18 / 6 | `proposal-006` | 성공 | 성공 | 3.04~12.92 | 0.4049 | 1.0000 | 5.88초 |
| 03 | 6 | 18 / 6 | Provider HTTP 503 `UNAVAILABLE` | 실패 | 미실행 | N/A | N/A | N/A | N/A |
| 04 | 4 | 12 / 4 | abstain: `NO_RELEVANT_PROPOSAL` | 성공 | 성공 | N/A | N/A | N/A | N/A |
| 05 | 4 | 12 / 4 | `proposal-004` | 성공 | 성공 | 22.26~24.90 | 0.4400 | 0.4400 | 3.36초 |

- Proposal preparation: 5/5
- Provider/Structured Output 성공: 4/5
- Validator 성공: 4/5 전체 Test, Structured Output 성공 건에서는 4/4
- Valid proposal selection: 2/5
- 정상 abstain: 2/5
- Provider failure: 1/5
- Invalid interval: 0건
- GT prompt 포함: 0건
- 자유 timestamp 생성: 0건

Abstain과 Provider failure는 IoU 0으로 변환하지 않았다.

## 4. Test별 상세 결과

### Test 01

- Fixed block: `block-0002`, Raw 12.70~13.18초
- GT: 10.0~15.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- 결과: 정상 abstain, `INSUFFICIENT_VISUAL_EVIDENCE`
- 근거: Contact Sheet가 닫힌 노트북 뚜껑만 보여주고 EditMemo에 대응하는 사건이나 상호작용을 포착하지 못했다고 판단했다.
- Candidate와 metric: N/A
- Latency / tokens: 6.9486초 / 4,974 input / 73 output / 5,047 total
- Oracle: `proposal-003`, 9.90~15.80초, IoU 0.8475, Coverage 1.0000, Total Error 0.90초

좋은 proposal은 존재했지만 각 proposal의 sparse frame이 motion과 reaction의 연결 근거를 충분히 보여주지 못해 선택 단계에서 abstain했다.

### Test 02

- Fixed block: `block-0001`, Raw 3.04~10.96초
- GT: 7.0~11.0초
- Proposal / logical frame / actual image: 6 / 18 / 6
- 선택: `proposal-006`, `EVENT_AND_REACTION_CONNECTED`
- Candidate: 3.04~12.92초
- IoU / Coverage: 0.4049 / 1.0000
- Start / End / Total Error: 3.96 / 1.92 / 5.88초
- Latency / tokens: 6.2350초 / 7,271 input / 80 output / 7,351 total
- Oracle: `proposal-005`, 5.86~10.96초, IoU 0.7704, Coverage 0.9900, Total Error 1.18초

Gemini는 사건과 reaction을 포함한다는 이유로 더 긴 context인 `proposal-006`을 골랐다. GT를 거의 포함했지만 앞뒤를 과도하게 확장해 Raw IoU 0.4975보다 낮았고 oracle `proposal-005`를 선택하지 못했다.

### Test 03

- Fixed block: `block-0002`, Raw 7.52~22.26초
- GT: 6.0~23.0초
- Proposal / logical frame / actual image: 6 / 18 / 6
- 결과: HTTP 503 `UNAVAILABLE`, failure stage `generate_content`, timeout 아님
- Structured Output, validator, Candidate와 metric: N/A
- Failure latency: 5.0027초, token usage N/A
- Oracle: `proposal-002`, 5.52~24.26초, IoU 0.9072, Coverage 1.0000, Total Error 1.74초

Provider failure이므로 긴 이야기 유지 여부를 평가할 수 없다. 명시적 재시도나 fallback은 하지 않았다.

### Test 04

- Fixed block: `block-0002`, Raw 8.08~10.56초
- GT: 7.0~11.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- 결과: 정상 abstain, `NO_RELEVANT_PROPOSAL`
- 근거: transcript는 물건을 떨어뜨릴 뻔한 사건을 언급하지만 Contact Sheet는 노트북 키보드와 화면만 보여주며 물리적 행동이나 낙하 물체가 보이지 않는다고 판단했다.
- Candidate와 metric: N/A
- Latency / tokens: 6.2836초 / 4,959 input / 67 output / 5,026 total
- Oracle: `proposal-004`, 5.54~10.78초, IoU 0.6923, Coverage 0.9450, Total Error 1.68초

Proposal 집합에는 Raw보다 높은 IoU 후보가 있었지만 sparse visual evidence와 transcript를 연결하지 못했다.

### Test 05

- Fixed block: `block-0003`, Raw 22.48~24.90초
- GT: 20.0~26.0초
- Proposal / logical frame / actual image: 4 / 12 / 4
- 선택: `proposal-004`, `EVENT_AND_REACTION_CONNECTED`
- Candidate: 22.26~24.90초
- IoU / Coverage: 0.4400 / 0.4400
- Start / End / Total Error: 2.26 / 1.10 / 3.36초
- Latency / tokens: 9.8178초 / 4,967 input / 82 output / 5,049 total
- Oracle: `proposal-002`, 20.48~26.84초, IoU 0.8070, Coverage 0.9200, Total Error 1.32초

Raw의 0.4033/0.4033보다 IoU와 Coverage가 함께 소폭 개선됐지만 reaction 전후의 전체 visual event를 포함한 oracle proposal 대신 짧은 구간을 선택했다.

## 5. Gemini 선택과 Proposal Oracle

Proposal Oracle은 GT를 본 사후 upper bound이며 자동 시스템 성능이 아니다.

| Test | Gemini selection | Gemini IoU | Oracle best | Oracle range | Oracle IoU | Oracle Coverage | Oracle Total Error | 차이 |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | --- |
| 01 | abstain | N/A | proposal-003 | 9.90~15.80 | 0.8475 | 1.0000 | 0.90 | 좋은 후보를 선택하지 않음 |
| 02 | proposal-006 | 0.4049 | proposal-005 | 5.86~10.96 | 0.7704 | 0.9900 | 1.18 | 긴 context 과선택 |
| 03 | Provider failure | N/A | proposal-002 | 5.52~24.26 | 0.9072 | 1.0000 | 1.74 | 선택 평가 불가 |
| 04 | abstain | N/A | proposal-004 | 5.54~10.78 | 0.6923 | 0.9450 | 1.68 | 좋은 후보를 선택하지 않음 |
| 05 | proposal-004 | 0.4400 | proposal-002 | 20.48~26.84 | 0.8070 | 0.9200 | 1.32 | 짧은 reaction proposal 과선택 |

Proposal generation failure는 0건이었다. 관측된 병목은 1건의 Provider availability failure와 4건 중 2건의 abstain, 선택 2건 모두 oracle과 다른 selection이다.

## 6. 기존 Baseline 비교

| Test | Raw IoU / Total Error | Audio v0.1 | Visual v0.1 | Local VLM v0.1 | Local VLM v0.1.1 | Local VLM v0.2 | Gemini Flash-Lite v0.1 | Proposal Oracle IoU | Fixed oracle IoU |
| --- | ---: | ---: | ---: | --- | --- | --- | --- | ---: | ---: |
| 01 | 0.0960 / 4.52 | 0.1200 / 4.40 | N/A | 준비 실패 | timeout | timeout | abstain | 0.8475 | 0.7241 |
| 02 | 0.4975 / 4.00 | 0.0000 / 7.82 | N/A | Provider 실패 | context 초과 | timeout | 0.4049 / 5.88 | 0.7704 | 0.1333 |
| 03 | 0.8671 / 2.26 | 0.3224 / 11.52 | 0.1059 / 15.20 | 준비 실패 | context 초과 | timeout | Provider 503 | 0.9072 | 0.6554 |
| 04 | 0.6200 / 1.52 | 0.3800 / 2.48 | 0.1500 / 3.40 | 준비 실패 | timeout | timeout | abstain | 0.6923 | 0.1333 |
| 05 | 0.4033 / 3.58 | 0.4400 / 3.36 | N/A | 준비 실패 | timeout | timeout | 0.4400 / 3.36 | 0.8070 | 0.6082 |

Valid selection이 있었던 Test 02·05의 paired 비교는 다음과 같다.

| Median | 대응 Raw | Gemini selected | 변화 |
| --- | ---: | ---: | --- |
| IoU | 0.4504 | 0.4224 | 하락 |
| Coverage | 0.6967 | 0.7200 | 상승 |
| Total Boundary Error | 3.79초 | 4.62초 | 증가 |

전체 Raw 5개 median은 IoU 0.4975, Coverage 0.6200, Total Error 3.58초다. Gemini는 2개만 Candidate를 만들었으므로 전체 Raw median과 직접 동일 표본 비교하지 않는다.

## 7. Latency와 Token Usage

| Test | 성공 응답 | Latency | Input | Output | Total |
| --- | --- | ---: | ---: | ---: | ---: |
| 01 | 예 — abstain | 6.9486초 | 4,974 | 73 | 5,047 |
| 02 | 예 — selection | 6.2350초 | 7,271 | 80 | 7,351 |
| 03 | 아니오 — 503 | 5.0027초 | N/A | N/A | N/A |
| 04 | 예 — abstain | 6.2836초 | 4,959 | 67 | 5,026 |
| 05 | 예 — selection | 9.8178초 | 4,967 | 82 | 5,049 |

- Successful response 평균 latency: 7.3212초
- Successful response median latency: 6.6161초
- Successful response 총 input/output/total tokens: 22,171 / 302 / 22,473
- Local qwen3-vl Contact Sheet v0.2: 5/5 약 120초 timeout, Structured Output 0/5
- Gemini Flash-Lite: 4/5 응답 및 Structured Output, 1/5 빠른 HTTP 503

현재 payload에서는 Gemini Flash-Lite가 Local VLM보다 operational feasibility를 크게 개선했지만 Provider availability failure는 남아 있다.

## 8. 사전 성공 기준 판정

| 기준 | 결과 | 판정 |
| --- | --- | --- |
| Proposal preparation 5/5 | 5/5 | PASS |
| Provider/Structured Output 최소 4/5 | 4/5 | PASS |
| Invalid interval 0건 | 0건 | PASS |
| GT prompt 포함 0건 | 0건 | PASS |
| 자유 timestamp 생성 0건 | 0건 | PASS |
| Valid proposal selection 최소 3/5 | 2/5 | FAIL |
| Test 01 또는 05 Raw 대비 IoU·Coverage 공동 개선 | Test 05에서 0.4033→0.4400 공동 개선 | PASS |
| Test 02 Raw IoU 0.4975 크게 훼손하지 않음 | 0.4049로 하락, Total Error 4.00→5.88 | FAIL |
| Valid Candidate median IoU가 대응 Raw보다 상승 | 0.4504→0.4224 | FAIL |
| Valid Candidate median Total Error 감소 | 3.79→4.62초 | FAIL |
| Successful latency/token 기록 | 4건 모두 기록 | PASS |
| Local처럼 120초 timeout 반복 여부 | timeout 0건 | PASS |

전체 사전 성공 기준은 **미달**이다. Provider feasibility는 확인됐지만 selection yield와 quality 기준을 충족하지 못했다.

## 9. 결론과 다음 단계

현재 5개 Evaluation Dataset v0.1에서 Gemini Flash-Lite는 Local qwen3-vl의 실행 병목을 크게 줄여 4/5 Structured Output을 만들었다. 그러나 좋은 proposal이 모든 Test에 있었음에도 selection은 2건뿐이었고, 두 selection 모두 oracle과 달랐다. Test 01·04에서는 frame evidence가 사건을 보여주지 못한다고 abstain했고, Test 02는 긴 context를 과선택했으며 Test 05는 reaction 중심의 짧은 proposal을 선택했다.

따라서 다음 우선순위는 proposal 종류를 늘리거나 OpenAI를 즉시 비교하는 것보다 **현재 sparse Contact Sheet 표현과 selection prompt가 사건 연결 근거를 충분히 전달하는지 분리 평가하는 prompt/representation 개선 실험**이다. Proposal Oracle이 높아 proposal 생성 자체가 일차 병목은 아니다. 다만 같은 v0.1 결과를 보고 즉시 tuning하지 않고, 별도 버전·사전 기준으로 수행해야 한다. 외부 Provider 간 품질 비교는 representation/prompt 조건을 고정한 뒤 필요할 때 진행하는 것이 타당하다.

## 10. 의도적으로 하지 않은 것

- Test별 retry, fallback 또는 실패한 Test 재호출
- `gemini-3.5-flash`, OpenAI, Local Ollama 호출
- Model, prompt, proposal 종류·수·padding, Contact Sheet, frame sampling 변경
- Ground Truth, oracle, 평가 지표, proposal kind를 Gemini 입력에 포함
- Provider output 숫자로 Candidate timestamp 생성
- STT, Memo Detector, CandidateEvaluator 또는 기존 Baseline 수정
- 기존 평가 문서 덮어쓰기
- Step 2 변경사항 commit 또는 push
