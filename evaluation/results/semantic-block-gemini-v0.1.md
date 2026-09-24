# Gemini Semantic Block Selector Evaluation v0.1

## 1. 실험 목적과 실행 상태

이 평가는 `gemini-3.5-flash`가 EditMemo와 메모 이전 TranscriptBlock만 보고 사용자의 메모가 가리키는 block ID 하나를 선택할 수 있는지 확인한다. LLM은 timestamp를 생성하지 않으며, 선택 이후 block 존재 여부와 시간 범위 검증, SceneCandidate 변환, Ground Truth 평가는 기존 deterministic 코드가 담당한다.

이전 Run 1은 API 호출 결과를 stdout에만 유지해 세션 분리 후 결과를 회수하지 못했으므로 무효 처리했다. 이 문서의 유효한 실행은 다음 Run 2뿐이다.

- Run ID: `gemini-semantic-v0.1-run2`
- 완료 결과: 5/5 JSONL 영속 저장
- 새 API 호출: 5회(Test당 1회)
- 자동 재시도와 fallback: 없음
- Provider 성공: 2/5
- Provider 실패: 3/5 (`UNAVAILABLE`)

## 2. Provider, 모델, 설정

- Provider: Google Gemini API
- Model: `gemini-3.5-flash`
- Prompt version: `semantic-block-gemini-v0.1`
- Structured Output: `response_mime_type="application/json"`와 `response_json_schema`
- Temperature: `0.0`
- Thinking level: `minimal`
- 응답 Schema: 선택 가능한 `block_id`, 제한된 `reasoning_code`, 240자 이하 summary
- 실행 중 설정 변경, Test별 prompt 조정, 재시도, 다른 모델 fallback 없음

무료 Tier 사용을 전제로 한 Spike다. 실제 과금 여부는 연결된 Google 프로젝트의 요금제와 quota에 따르며 이 평가에서는 금액을 추정하지 않았다. 5개 데이터와 단일 실행만으로 일반 성능을 주장할 수 없다.

## 3. 외부 전송 데이터와 평가 경계

Gemini에 전송한 정보는 다음뿐이다.

- EditMemo transcript
- 각 TranscriptBlock의 `block_id`, `start_seconds`, `end_seconds`, `transcript_text`
- 공통 prompt version과 선택 지침

Ground Truth, IoU, Coverage, Fixed Window 결과, 기존 평가 결과, segment ID는 전송하지 않았다. 원본 MOV, WAV, 이미지와 영상 프레임도 업로드하지 않았다. Ground Truth는 Gemini 선택과 deterministic validator가 끝난 뒤 CandidateEvaluator에만 전달했다.

로컬 중간 결과는 Git에서 제외된 `evaluation/tmp/gemini-semantic-run.jsonl`에 Test별 API 처리 직후 append하고 flush와 fsync를 수행했다. API key, Authorization header, `.env`, Provider 원문 응답은 저장하지 않았다.

## 4. Test별 상세 결과

### Test 01

- EditMemo: `에이아이아 지금 장면 꼭 살려줘.`
- Ground Truth: 10.0~15.0초

| Block | 구간 | Transcript |
| --- | ---: | --- |
| block-0001 | 1.24~9.90초 | `안녕하세요. 저는 김사과입니다. 지금은 간단한 동영상 테스트를 해보고 있습니다. 제가 물건을 하나 떨어뜨려 볼게요.` |
| **block-0002 (선택)** | **12.70~13.18초** | `아 뭐야.` |

- Selected block: `block-0002`
- Reasoning code: `RECENT_EVENT_REACTION`
- Reasoning summary: 현재 장면을 살려달라는 메모와 물건을 떨어뜨린 뒤의 반응 발화를 연결했다.
- Validator: 성공
- Provider error: 없음
- Latency: 10.9599초
- Token usage: input 303 / output 78 / total 381

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 12.70~13.18초 | 0.0960 | 0.0960 | 2.70초 | 1.82초 | 4.52초 |

관련 reaction block은 선택했지만 발화 길이가 0.48초뿐이라 GT의 무음·시각 구간을 대부분 놓쳤다. 이는 의미 선택과 별개인 transcript-only scene boundary 문제다.

### Test 02

- EditMemo: `아 AIA 방금 장면 꼭 살려줘`
- Ground Truth: 7.0~11.0초

| Block | 구간 | Transcript |
| --- | ---: | --- |
| **block-0001 (선택)** | **3.04~10.96초** | `2번째 테스트 영상입니다 아 뭐야 떨어졌네` |
| block-0002 | 14.00~23.80초 | `다시 주었습니다 오늘은 영상 테스트를 하고 있는데요 이제 책상도 좀 정리하고 다음 테스트도 해보겠습니다` |

- Selected block: `block-0001`
- Reasoning code: `INSUFFICIENT_TRANSCRIPT_EVIDENCE`
- Reasoning summary: 메모의 `AIA`가 transcript에 명확하지 않지만 감탄과 물건이 떨어진 사건이 있는 block을 가장 가능성 높은 대상으로 선택했다.
- Validator: 성공
- Provider error: 없음
- Latency: 8.7691초
- Token usage: input 303 / output 85 / total 388

| Candidate | IoU | Coverage | Start Error | End Error | Total Error |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 3.04~10.96초 | 0.4975 | 0.9900 | 3.96초 | 0.04초 | 4.00초 |

Latest Transcript Block v0.1이 선택했던 무관한 `block-0002` 대신 사건 반응이 있는 `block-0001`을 선택했다. 이번 성공 사례에서는 의미 기반 선택이 시간상 최신 block 규칙의 실패를 해결했다.

### Test 03

- EditMemo: `에이아이아 방금 장면 꼭 살려줘.`
- Ground Truth: 6.0~23.0초

| Block | 구간 | Transcript |
| --- | ---: | --- |
| block-0001 | 1.62~4.28초 | `3번째 테스트 영상입니다.` |
| block-0002 | 7.52~22.26초 | `오늘 카페에 갔는데 제가 커피를 주문하고 자리에 앉았거든요. 그런데 한잔 이따가 보니까 제 커피가 아니라 옆사람 커피를 들고 온 거예요. 그래서 다시 카운터까지 꺼져다 줬어요.` |

- Provider error: `UNAVAILABLE`
- Validator: 미실행
- Candidate 및 평가 지표: 없음
- Latency와 token usage: Provider 성공 응답이 없어 기록되지 않음

재시도 금지 조건에 따라 같은 Test를 다시 호출하지 않았다. 따라서 긴 이야기 block을 유지하는지는 이번 Run에서 평가할 수 없다.

### Test 04

- EditMemo: `에이아이아 방금 장면 꼭 살려줘.`
- Ground Truth: 7.0~11.0초

| Block | 구간 | Transcript |
| --- | ---: | --- |
| block-0001 | 0.00~3.94초 | `4번째 테스트 영상입니다.` |
| block-0002 | 8.08~10.56초 | `오, 떨어뜨릴 뻔했다.` |

- Provider error: `UNAVAILABLE`
- Validator: 미실행
- Candidate 및 평가 지표: 없음
- Latency와 token usage: Provider 성공 응답이 없어 기록되지 않음

`떨어뜨릴 뻔했다` block 선택 여부는 이번 Run에서 평가할 수 없다.

### Test 05

- EditMemo: `에이야 에야 방금 장면 꼭 살려줘`
- Ground Truth: 20.0~26.0초

| Block | 구간 | Transcript |
| --- | ---: | --- |
| block-0001 | 0.00~11.12초 | `마지막 테스트 영상입니다 아 탱 떨어졌다` |
| block-0002 | 16.00~18.20초 | `다시 주워서 놓겠습니다` |
| block-0003 | 22.48~24.90초 | `큰일 날 뻔 했네` |

- Provider error: `UNAVAILABLE`
- Validator: 미실행
- Candidate 및 평가 지표: 없음
- Latency와 token usage: Provider 성공 응답이 없어 기록되지 않음

`큰일 날 뻔 했네` block 선택 여부와 transcript 경계 Coverage는 이번 Run에서 평가할 수 없다.

## 5. 전체 결과표

| Test | Selected Block | Candidate | IoU | Coverage | Start Error | End Error | Total Error | Latency | Tokens | Provider Error |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Test 01 | block-0002 | 12.70~13.18 | 0.0960 | 0.0960 | 2.70 | 1.82 | 4.52 | 10.9599초 | 381 | 없음 |
| Test 02 | block-0001 | 3.04~10.96 | 0.4975 | 0.9900 | 3.96 | 0.04 | 4.00 | 8.7691초 | 388 | 없음 |
| Test 03 | 없음 | 없음 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | UNAVAILABLE |
| Test 04 | 없음 | 없음 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | UNAVAILABLE |
| Test 05 | 없음 | 없음 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | UNAVAILABLE |

성공한 2개 Test만 대상으로 한 집계는 다음과 같다. Provider 실패를 임의로 0점 처리하지 않았으므로 5개 전체의 평균 성능으로 해석하면 안 된다.

| 지표 | 평균 | 중앙값 |
| --- | ---: | ---: |
| IoU | 0.2967 | 0.2967 |
| Coverage | 0.5430 | 0.5430 |

- 성공 응답 평균 latency: 9.8645초
- 확인 가능한 총 token usage: input 606 / output 163 / total 769
- Provider 성공률: 40% (2/5)

## 6. Baseline 비교

Fixed Window 값은 시스템이 자동으로 선택한 결과가 아니라 각 Test의 여러 Window를 Ground Truth로 사후 비교한 **oracle 최고 IoU 및 oracle 최저 Total Error**다.

| Test | Fixed Window oracle 최고 IoU | Latest Block IoU | Gemini IoU | Latest → Gemini 변화 |
| --- | ---: | ---: | ---: | --- |
| Test 01 | 0.7241 | 0.0960 | 0.0960 | 동일 block, 동일 IoU |
| Test 02 | 0.1333 | 0.0000 | 0.4975 | 관련 과거 block 선택으로 개선 |
| Test 03 | 0.6554 | 0.8671 | N/A | Provider 실패로 비교 불가 |
| Test 04 | 0.1333 | 0.6200 | N/A | Provider 실패로 비교 불가 |
| Test 05 | 0.6082 | 0.4033 | N/A | Provider 실패로 비교 불가 |

| Test | Fixed Window oracle 최저 Total Error | Latest Block Total Error | Gemini Total Error |
| --- | ---: | ---: | ---: |
| Test 01 | 1.60초 | 4.52초 | 4.52초 |
| Test 02 | 26.00초 | 19.80초 | 4.00초 |
| Test 03 | 7.88초 | 2.26초 | N/A |
| Test 04 | 26.00초 | 1.52초 | N/A |
| Test 05 | 2.68초 | 3.58초 | N/A |

Test 02에서는 의미 기반 선택이 Latest Block의 핵심 실패를 해결했고 Fixed Window oracle보다도 높은 IoU를 얻었다. 반면 Test 01에서는 선택 자체는 타당해도 transcript block 경계가 너무 짧아 Fixed Window oracle보다 낮았다.

## 7. 성공, 실패와 남은 문제

### 해결된 문제

- Test 02에서 단순 최신성 대신 사건성과 반응을 근거로 과거 `block-0001`을 선택했다.
- deterministic validator가 LLM이 반환한 ID를 입력 block의 기존 timestamp로 변환해 LLM이 시간을 직접 만들지 못하게 했다.

### 해결되지 않은 문제

- Scene boundary: Test 01처럼 올바른 reaction block을 골라도 음성 timestamp만으로 GT의 앞뒤 시각 구간을 복구할 수 없다.
- Provider 가용성: Test 03~05는 `UNAVAILABLE`로 선택 결과 자체가 없었다. 자동 재시도와 fallback을 금지한 실험 조건에서 이는 그대로 실패로 기록됐다.
- 평가 완전성: 실제 Candidate 지표가 있는 Test가 2개뿐이므로 모델 선택 품질의 평균이나 일반화 성능을 판단할 수 없다.
- 데이터 규모: 전체 데이터가 5개이고 단일 실행이므로 prompt나 모델의 일반적 성능을 결론 내릴 수 없다.

이번 결과는 의미 기반 선택이 Test 02 유형을 해결할 가능성을 보여주지만, transcript-only 경계 문제와 Provider 실패를 해결하지 않는다. 다음 기술 결정은 이 성공 사례와 실패 기록을 함께 근거로 해야 한다.
