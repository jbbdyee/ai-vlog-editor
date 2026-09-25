# Local VLM Proposal Selector Evaluation v0.1

## 1. 실험 목적과 실행 상태

Deterministic code가 생성한 3~6개 Scene Boundary Proposal과 대표 프레임을 로컬 VLM이 보고, EditMemo와 선택된 TranscriptBlock에 가장 관련된 proposal ID 하나를 선택할 수 있는지 평가한다. VLM은 timestamp를 생성하지 않으며 Ground Truth는 selection과 validator가 끝난 뒤 평가 및 Proposal Oracle 계산에만 사용한다.

- Run ID: `local-vlm-eval-v0.1-run1`
- Runtime: Mac native Ollama
- Model: `qwen3-vl:4b`
- Endpoint: `http://localhost:11434`
- Context: 16,384
- Temperature: 0.0
- 완료 레코드: 5/5
- 실제 Ollama 호출: 1회 (`eval_02`)
- 재시도 및 fallback: 없음

5개 terminal result는 `evaluation/tmp/local-vlm-proposal-run.jsonl`에 Test별로 즉시 append, flush, fsync했다. 그러나 이번 Run은 4개의 proposal 준비 실패와 1개의 Provider 실패로 인해 VLM 선택 성능을 측정하지 못했다.

## 2. 고정 Proposal과 Frame 설정

Proposal 우선순위는 다음과 같다.

1. `RAW_BLOCK`
2. `FIXED_PADDING`: 선택 block 앞뒤 2초
3. `TRANSCRIPT_CONTEXT`: 이전 block 종료부터 다음 block 시작 또는 memo 시작까지
4. `FIRST_SEGMENT`
5. `LAST_SEGMENT`
6. `SIGNAL_ENVELOPE`: 선택 block과 연결 가능한 기존 audio/visual interval 포함

동일 interval은 제거하고 최대 6개를 유지한다. 각 proposal은 10%, 50%, 90% 지점에서 정확히 3장의 JPEG를 추출하며 긴 변 512px, 원본 종횡비 유지, metadata 제거 설정을 공통 적용한다. VLM payload에는 proposal kind를 숨기고 중립 ID만 전달한다.

## 3. 개인정보 및 결정적 검증 경계

VLM에 전달하도록 허용한 정보는 EditMemo transcript, 선택 block ID/text, proposal ID/start/end와 대표 JPEG뿐이다. Ground Truth, IoU, Coverage, Boundary Error, Fixed Window/Proposal Oracle, 기존 winner, proposal kind, 원본 MOV/WAV는 전달하지 않았다.

VLM 출력 Schema에는 proposal ID 또는 명시적 abstain과 제한된 reasoning만 있고 timestamp 필드는 없다. 일반 Python validator만 저장된 proposal timestamp를 `SceneCandidate`로 변환한다.

## 4. Test별 결과

### Test 01

- Fixed selected block: `block-0002` (12.70~13.18초)
- Ground Truth: 10.0~15.0초
- 상태: `ProposalGenerationError`
- 실제 Ollama 호출: 없음
- Proposal / image count: 0 / 0
- Structured Output / validator: 미실행
- Candidate와 평가 지표: 없음
- Proposal Oracle: 계산 불가

선택 block이 마지막 transcript block이라 `next_block_start_seconds=None`이었다. 현재 generator는 이 경우 local search end를 block end와 같게 만든 뒤 “search range가 complete selected block을 포함해야 한다”는 검증에서 거부했다. 이는 VLM 선택 실패가 아니라 proposal 생성 실패다.

### Test 02

- Fixed selected block: `block-0001` (3.04~10.96초)
- Ground Truth: 7.0~11.0초
- Proposal / image count: 6 / 18
- 실제 Ollama 호출: 1회
- Provider error: `OllamaVLMProviderError`
- Latency: 2.3621초
- Structured Output / validator: 실패 전 미실행
- Selected proposal / reasoning / token usage: 없음
- Candidate와 선택 평가 지표: 없음

| Proposal | Kind | Interval | Oracle IoU | 비고 |
| --- | --- | ---: | ---: | --- |
| proposal-001 | RAW_BLOCK | 3.04~10.96 | 0.4975 | 기존 Raw |
| proposal-002 | FIXED_PADDING | 1.04~12.96 | - | |
| proposal-003 | TRANSCRIPT_CONTEXT | 0.00~14.00 | - | |
| proposal-004 | FIRST_SEGMENT | 3.04~5.86 | - | |
| **proposal-005** | **LAST_SEGMENT** | **5.86~10.96** | **0.7704** | Oracle best |
| proposal-006 | SIGNAL_ENVELOPE | 3.04~12.92 | - | |

Proposal Oracle은 `proposal-005`다.

- IoU: 0.7704
- Coverage: 0.9900
- Total Boundary Error: 1.18초

즉 Test 02에는 Raw보다 좋은 proposal이 실제로 존재했다. 하지만 Provider가 Structured Output 전에 실패했기 때문에 VLM이 이를 선택할 수 있는지는 평가하지 못했다. 저장된 provider code는 예외 클래스 수준이라 세부 안전 메시지는 이 Run 결과에 남지 않았다.

### Test 03

- Fixed selected block: `block-0002` (7.52~22.26초)
- Ground Truth: 6.0~23.0초
- 상태: `ProposalGenerationError`
- 실제 Ollama 호출: 없음
- Proposal / image count: 0 / 0
- Candidate, 평가 지표와 Proposal Oracle: 없음

Test 01과 동일하게 선택 block이 마지막 block인 local search 처리에서 중단됐다. 긴 이야기 전체를 VLM이 유지하는지는 평가하지 못했다.

### Test 04

- Fixed selected block: `block-0002` (8.08~10.56초)
- Ground Truth: 7.0~11.0초
- 상태: `ProposalGenerationError`
- 실제 Ollama 호출: 없음
- Proposal / image count: 0 / 0
- Candidate, 평가 지표와 Proposal Oracle: 없음

짧은 위험 사건 proposal 선택은 평가하지 못했다.

### Test 05

- Fixed selected block: `block-0003` (22.48~24.90초)
- Ground Truth: 20.0~26.0초
- 상태: `ProposalGenerationError`
- 실제 Ollama 호출: 없음
- Proposal / image count: 0 / 0
- Candidate, 평가 지표와 Proposal Oracle: 없음

Reaction 전후 visual event를 포함하는 proposal 선택은 평가하지 못했다.

## 5. 전체 결과

abstain은 IoU 0으로 바꾸지 않으며, 이번 Run에는 Structured Output 자체가 없어 abstain 결과도 없다.

| Test | Preparation | Provider / Structured | Selected | IoU | Coverage | Total Error | Proposal Oracle |
| --- | --- | --- | --- | ---: | ---: | ---: | --- |
| 01 | 실패 | 미호출 | N/A | N/A | N/A | N/A | N/A |
| 02 | 성공 | Provider 실패 | N/A | N/A | N/A | N/A | proposal-005 / 0.7704 |
| 03 | 실패 | 미호출 | N/A | N/A | N/A | N/A | N/A |
| 04 | 실패 | 미호출 | N/A | N/A | N/A | N/A | N/A |
| 05 | 실패 | 미호출 | N/A | N/A | N/A | N/A | N/A |

- Provider/Structured Output 성공률: 0/5 (0%)
- 실제 호출 기준 Provider 성공률: 0/1 (0%)
- Valid proposal selection rate: 0/5 (0%)
- 평균 호출 latency: 2.3621초 (실제 호출 1건, 실패 응답)
- 확인 가능한 token usage: 없음
- Selected Candidate median IoU/Coverage/Total Error: 계산 불가

## 6. 기존 Baseline과 사후 Oracle 비교

Fixed Window와 Proposal Oracle은 GT를 본 사후 참고치이며 실제 자동 선택 성능이 아니다.

| Test | Raw IoU / Total Error | Audio IoU / Total Error | Visual IoU / Total Error | Local VLM | Proposal Oracle IoU | Fixed Window Oracle IoU |
| --- | ---: | ---: | ---: | --- | ---: | ---: |
| 01 | 0.0960 / 4.52 | 0.1200 / 4.40 | N/A | 준비 실패 | N/A | 0.7241 |
| 02 | 0.4975 / 4.00 | 0.0000 / 7.82 | N/A | Provider 실패 | 0.7704 | 0.1333 |
| 03 | 0.8671 / 2.26 | 0.3224 / 11.52 | 0.1059 / 15.20 | 준비 실패 | N/A | 0.6554 |
| 04 | 0.6200 / 1.52 | 0.3800 / 2.48 | 0.1500 / 3.40 | 준비 실패 | N/A | 0.1333 |
| 05 | 0.4033 / 3.58 | 0.4400 / 3.36 | N/A | 준비 실패 | N/A | 0.6082 |

이번 결과로 VLM이 기존 Baseline보다 개선됐다고 주장할 수 없다. 다만 Test 02의 Proposal Oracle은 proposal 집합 안에 Raw보다 좋은 경계가 있었음을 보여준다. 이 Test는 “proposal 자체가 나쁨”이 아니라 Provider/selection을 평가하지 못한 경우다. 나머지 네 Test는 proposal 집합을 만들지 못했으므로 proposal-generation failure다.

## 7. 사전 성공 기준 판정

| 기준 | 결과 | 판정 |
| --- | --- | --- |
| Provider/Structured Output 최소 4/5 | 0/5 | 실패 |
| Valid proposal 선택 최소 3/5 | 0/5 | 실패 |
| Invalid interval 0건 | Candidate 생성 없음 | 통과하되 성능 의미 없음 |
| GT prompt 포함 0건 | 0건 | 통과 |
| 자유 timestamp 생성 0건 | 0건 | 통과 |
| Test 01 또는 05 Raw 대비 IoU·Coverage 공동 개선 | 둘 다 준비 실패 | 실패/평가 불가 |
| Test 02 Raw IoU 0.4975 보존 | 선택 Candidate 없음 | 실패/평가 불가 |
| Selected median IoU 상승 | 선택 결과 없음 | 실패/평가 불가 |
| Selected median Total Error 감소 | 선택 결과 없음 | 실패/평가 불가 |

따라서 Local VLM Proposal Selector v0.1은 사전 성공 기준에 **미달**이다.

## 8. 실패 유형과 다음 단계

이번 Run의 우선 실패는 VLM의 시각 의미 판단이 아니다.

1. Test 01/03/04/05: 마지막 selected block에 대한 local search 기본 경계 처리로 proposal 생성 실패
2. Test 02: proposal 6개와 이미지 18장까지 생성됐으나 Provider 단계 실패
3. Structured Output, validator, 실제 proposal 선택 성능은 5개 모두 평가되지 않음

다음 단계는 별도 버전에서 proposal generator의 `next_block_start=None` 처리와 Provider 오류 진단 보존을 먼저 검증하는 것이다. 그 후 같은 고정 데이터로 proposal coverage/oracle을 확인해야 한다. 현재 상태에서 OpenAI/Gemini Vision과 비교하면 local VLM 모델 성능이 아니라 준비 파이프라인과 payload 실행 가능성 차이를 비교하게 되므로 아직 근거가 부족하다.

## 9. 의도적으로 하지 않은 것

- 실패 결과를 보고 generator, prompt, proposal 종류/순서, frame 수·해상도 변경
- 모델, `num_ctx`, temperature 변경 또는 fallback
- 실패 Test 재시도
- Ground Truth, 평가 지표, oracle을 VLM payload에 포함
- Gemini/OpenAI 호출
- 기존 Raw/Audio/Visual/Fixed Window Baseline 수정
- 선택/abstain이 없는데 IoU를 0으로 기록
- 커밋 또는 푸시
