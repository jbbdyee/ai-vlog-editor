# Selective Text LLM Transcript Proposal Selector v0.1

## Run scope

- capability: `TRANSCRIPT_PROPOSAL_SELECTOR`
- provider baseline: OpenAI
- default model: `gpt-6-luna`
- prompt version: `transcript-proposal-selector-v0.1`
- schema version: `transcript-proposal-selection-v0.1`
- dataset: Step 4의 5개 synthetic focused case
- actual media / real GT: 없음
- VLM calls: 0
- new MCP Tool: 0

이 환경에는 `OPENAI_API_KEY`가 없어 actual Provider integration은 실행하지 않았다. Mock/contract 테스트를 actual API 성공으로 표현하지 않으며, 아래 selective LLM semantic quality 지표는 미측정이다.

## Deterministic baseline

동일한 Proposal generator와 manifest를 사용한 Step 4 결과다.

- cases: 5
- Proposal Recall@K: 1.0 — GT가 있는 4 case
- average Proposal count: 5.2
- deterministic selection accuracy when expected: 0.5 (2/4)
- deterministic solved: 2
- semantic escalation eligible: 2
  - `MULTIPLE_JUST_NOW_BLOCKS`
  - `EARLIER_NEEDS_REFERENCE`
- no transcript로 AI가 해결할 수 없어 호출하지 않는 case: 1
- actual Provider calls: 0 — API key 없음
- actual AI invocation rate: 계산 불가
- VLM calls: 0

## Actual provider metrics

| Metric | Result |
| --- | --- |
| Invocation success | 미측정 |
| Structured output success | 미측정 |
| Python validation success after actual response | 미측정 |
| Selective LLM selection accuracy | 미측정 |
| Abstention correctness | 미측정 |
| tIoU / Coverage / Boundary error | 미측정 |
| Latency | 미측정 |
| Input / output tokens | 미측정 |
| Cost | 미측정 |

## Contract and persistence validation

- deterministic unique selection에서 Provider call 0
- ambiguous bounded Proposal에서 Provider call 정확히 1
- `SELECTED`와 `AMBIGUOUS`/`NO_MATCH`/`INSUFFICIENT_EVIDENCE` 분리
- Provider failure, timeout, parse failure와 semantic abstention 분리
- unknown Proposal ID와 selected/status invariant 위반 거부
- timestamp field와 extra field를 strict schema가 거부
- 240자 초과 summary 거부
- prompt injection 문자열을 transcript DATA로 유지하고 unknown/path ID 거부
- Candidate timestamp는 local Proposal manifest에서만 획득
- Candidate confidence는 null
- full Memo/Transcript/prompt/response를 Evidence에 저장하지 않음
- 동일 semantic input/provider/model/prompt/schema는 완료 결과 재사용
- model 변경은 semantic cache를 무효화
- 실제 PostgreSQL 17.11에서 WorkItem, Attempt, Candidate, Evidence와 재사용 durability 확인

## Provider and model rationale

Repository에는 `openai==3.19.2`와 Responses API Structured Outputs experimental adapter가 이미 존재한다. `gpt-6-luna`는 bounded Proposal classification처럼 집중형·고빈도 작업을 위한 현재 비용 효율 모델이고 Structured Outputs를 지원한다. 모델은 `CUTORY_SEMANTIC_TEXT_MODEL` 환경변수로 교체할 수 있으며 business logic에는 provider 분기를 넣지 않았다.

## Known limitations

- actual OpenAI request를 실행하지 않아 semantic improvement를 확인하지 못했다.
- 실제 Memo-focused media/GT가 없어 synthetic 결과를 제품 정확도로 해석할 수 없다.
- 현재 parser는 semantic reference를 별도로 추출하지 않으며 bounded Memo text가 selector 입력을 보완한다.
- 올바른 Proposal 선택과 scene boundary 품질은 별개의 문제다.
- 자동 retry/fallback과 VLM production integration은 구현하지 않았다.

## Reproduction

Provider key가 없는 안전한 계약 실행:

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_selective_text_llm_baseline
```

`OPENAI_API_KEY`가 현재 process에 안전하게 설정된 별도 환경에서는 같은 명령이 실제 selective call 결과를 출력한다. Key, full prompt와 raw response는 결과 파일에 저장하지 않는다.
