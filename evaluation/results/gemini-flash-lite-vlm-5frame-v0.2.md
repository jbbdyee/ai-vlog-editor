# Gemini Flash-Lite VLM 5-frame Contact Sheet Feasibility v0.2

## 1. 실험 가설

Proposal당 3개 frame보다 5개 frame이 사건의 시작, 전개, 반응 흐름을 더 잘 보여주어 VLM proposal selection에 필요한 temporal evidence를 개선할 수 있는지 확인하려 했다.

이번 단계는 selection 품질 평가 전의 Provider feasibility Smoke이며 Ground Truth와 실제 eval frame을 사용하지 않았다. 모델, proposal 집합, selection 판단 기준, Structured Output Schema와 deterministic validator는 기존 Gemini Flash-Lite VLM v0.1과 동일하게 유지했다.

## 2. 3-frame에서 5-frame으로 변경한 내용

기존 sampling:

```text
10% / 50% / 90%
```

신규 sampling:

```text
10% / 30% / 50% / 70% / 90%
```

각 timestamp는 다음 결정식으로 계산한다.

```text
proposal.start + (proposal.end - proposal.start) * fraction
```

각 proposal의 다섯 JPEG를 cell 크기와 해상도를 줄이지 않고 FFmpeg `hstack`으로 수평 결합한다.

```text
[10%][30%][50%][70%][90%]
```

- Config version: `contact-sheet-v0.2-5frame`
- Layout: `horizontal_5`
- Proposal count 정책: 기존과 동일
- Synthetic Smoke proposal: 3개
- Logical source frames: 15개
- 실제 Gemini image parts: Contact Sheet 3장

## 3. 구현 및 테스트 결과

Manifest는 proposal ID, 정확히 5개의 source frame ID와 timestamp, `(0.1, 0.3, 0.5, 0.7, 0.9)` fractions, layout, config version을 보존한다. Validator는 frame 누락·중복·순서, 결정식 timestamp, proposal 범위, layout/config mismatch와 빈 JPEG를 거부한다.

기존 3-frame 설정은 기본 config로 유지했으며 proposal ID, start/end, Candidate 생성 및 selection validator의 의미는 바꾸지 않았다. Prompt의 selection 판단 기준은 유지하고 Contact Sheet의 early → early-middle → middle → late-middle → late 배열 설명만 반영했다.

- 관련 단위 테스트: 43개 통과
- 전체 테스트: 183개 통과
- 3-frame 회귀: 확인되지 않음
- 로컬 synthetic 5-frame 생성: 15 logical frames → 3 non-empty Contact Sheets 성공
- API key, image bytes, base64, 전체 prompt는 JSONL에 저장하지 않음

## 4. Synthetic Smoke Run 1

- Run ID: `gemini-vlm-contact-sheet-5frame-smoke-v0.2-run1`
- Provider / model: Gemini / `gemini-3.1-flash-lite`
- Config: `contact-sheet-v0.2-5frame`
- Proposal / logical frames / image parts: 3 / 15 / 3
- Application-level 호출: 1회
- 결과: HTTP 503 `UNAVAILABLE`
- Failure stage: `generate_content`
- Timeout: 아니오
- Latency: 5.4254초
- Structured Output: 생성 전 실패
- Validator: 미실행
- Selection과 token usage: N/A

## 5. Synthetic Smoke Run 2

- Run ID: `gemini-vlm-contact-sheet-5frame-smoke-v0.2-run2`
- Provider / model: Gemini / `gemini-3.1-flash-lite`
- Config: `contact-sheet-v0.2-5frame`
- Proposal / logical frames / image parts: 3 / 15 / 3
- Application-level 호출: 1회
- 결과: HTTP 503 `UNAVAILABLE`
- Failure stage: `generate_content`
- Timeout: 아니오
- Latency: 1.7500초
- Structured Output: 생성 전 실패
- Validator: 미실행
- Selection과 token usage: N/A

Provider의 안전한 메시지는 모델이 높은 요청량을 처리 중이라는 내용이었다. 두 run 모두 terminal 결과를 ignored runtime JSONL에 append·flush·fsync했고 다시 읽어 복구했다. Runtime JSONL은 Git에 포함하지 않는다.

## 6. Feasibility 판정

두 번의 독립 Smoke가 모두 Structured Output 이전 HTTP 503으로 종료되어 5-frame payload의 end-to-end feasibility를 측정하지 못했다.

다음과 같이 해석하지 않는다.

- 5-frame 구현 실패
- Context 또는 payload size 실패
- Structured Output Schema 실패
- Deterministic validator 실패
- VLM selection 품질 실패

로컬 frame 생성, Contact Sheet 조립, manifest와 validator의 mock/unit 경로는 정상이다. 관측된 실패는 두 run 모두 Gemini Provider availability 단계의 `UNAVAILABLE`이다. Provider 응답이 없었으므로 input token 증가율, 정상 latency와 selection 품질은 계산할 수 없다.

## 7. 기존 3-frame 결과와의 차이

| 항목 | 3-frame Synthetic Smoke | 5-frame Run 1 | 5-frame Run 2 |
| --- | ---: | ---: | ---: |
| Logical frames | 9 | 15 | 15 |
| Actual image parts | 3 | 3 | 3 |
| Input tokens | 3,795 | N/A | N/A |
| Latency | 6.553초, 성공 | 5.4254초 후 503 | 1.7500초 후 503 |
| Structured Output | 성공 | 미생성 | 미생성 |
| Validator | 성공 | 미실행 | 미실행 |

3-frame v0.1은 eval_01~05에서 4/5 Structured Output을 생성했지만 valid selection은 2/5였다. 5-frame Spike는 sampling density가 그 selection 실패를 개선하는지 평가하기 위한 것이었으나 Provider 503 때문에 selection 단계에 도달하지 못했다. 실패 latency는 정상 처리 latency와 직접 비교하지 않는다.

## 8. 추가 동일 Smoke를 중단한 이유

동일 설정의 독립 run 두 개가 모두 동일한 Provider availability 오류로 종료됐다. 같은 실험을 계속 반복하면 sampling 가설 검증보다 일시적 Provider 상태를 반복 측정하게 되고 외부 호출만 증가한다.

따라서 이번 v0.2 범위에서는 다음을 중단한다.

- 동일 5-frame Synthetic Smoke 추가 반복
- eval_01~05 실행
- 결과를 얻기 위한 prompt, frame 수, 해상도 또는 모델 변경
- fallback 또는 다른 Provider 자동 전환

## 9. 향후 재개 조건

5-frame 평가를 재개하려면 현재 실험과 분리된 새 계획에서 다음 조건을 먼저 충족해야 한다.

1. Gemini Provider availability를 별도의 최소 요청으로 확인할 명시적 실행 계획이 있다.
2. 동일 `gemini-3.1-flash-lite`, `contact-sheet-v0.2-5frame`, 15 logical frames와 3 image parts 조건을 유지한다.
3. Synthetic Smoke가 Structured Output과 deterministic validator까지 한 번 완주한다.
4. 실제 eval Contact Sheet 외부 전송 범위와 개인정보 정책을 다시 확인한다.
5. 새 run ID, 호출 횟수 제한, 재시도 정책과 성공 기준을 사전에 고정한다.

이 조건 전에는 5-frame eval_01~05 selection 품질을 주장하거나 3-frame 결과와 비교하지 않는다.
