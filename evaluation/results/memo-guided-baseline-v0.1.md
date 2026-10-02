# Memo-guided Scene Discovery deterministic baseline v0.1

## 범위와 데이터

- production provider call: LLM 0, VLM 0
- 지원: `KEEP`, `JUST_NOW`, `EARLIER`, same-source only
- 로컬 `evaluation/data/`에는 `.gitkeep`만 있어 요청된 eval_01~eval_05 실제 자료는 사용할 수 없었다.
- 아래 수치는 실제 영상 평가가 아니라 `evaluation/run_memo_guided_baseline.py`의 5개 synthetic focused case 결과다.

## Baseline config

Production 기본값은 JUST_NOW lookback 30초, EARLIER lookback 120초, fixed window 5/10/15/30초, transcript gap 2초, context expansion 2초, JUST_NOW compatibility gap 2초, proposal budget 12다. 이는 historical fixed-window 후보와 transcript block의 기존 2초 gap을 보수적으로 재사용한 첫 평가값이며 최적값을 뜻하지 않는다. Synthetic ambiguity case만 두 block을 분리해 abstention을 검증하기 위해 transcript gap 0.1초를 명시했다.

## 실행 결과

명령: `.\.venv\Scripts\python.exe -m evaluation.run_memo_guided_baseline`

- cases: 5
- Proposal Recall@K: 1.0 (GT가 있는 4 case)
- 평균 proposal 수: 5.2
- selection accuracy when selection expected: 0.5 (2/4)
- 최종 선택 case: 2
- 선택된 case 평균 tIoU: 1.0
- 평균 target coverage: 1.0
- 평균 start/end boundary error: 0.0초 / 0.0초
- abstention: 3 (`MULTIPLE_JUST_NOW_BLOCKS` 1, `EARLIER_NEEDS_REFERENCE` 1, `NO_TRANSCRIPT_PROPOSAL` 1)
- LLM calls: 0
- VLM calls: 0

## Failure analysis

| taxonomy | count | 해석 |
|---|---:|---|
| SEMANTIC_AMBIGUITY | 1 | memo 직전 호환 block이 둘이라 임의 선택하지 않음 |
| INSUFFICIENT_EVIDENCE | 2 | EARLIER semantic reference 부재 1, transcript proposal 부재 1 |
| MEMO_DETECTION_FAILURE | 0 | 이 focused harness는 persisted memo부터 시작 |
| INTENT_PARSE_FAILURE | 0 | 모든 synthetic memo가 KEEP 구조를 가짐 |
| SEARCH_REGION_MISS | 0 | synthetic GT는 configured region 안에 있음 |
| PROPOSAL_MISS | 0 | 네 GT case 모두 겹치는 proposal 존재 |
| SELECTION_ERROR | 0 | 잘못 선택한 case 대신 보수적으로 abstain |
| OUTPUT_VALIDATION_FAILURE | 0 | manifest validator 통과 |
| PERSISTENCE_FAILURE | 0 | 별도 PostgreSQL integration test에서 검증 |

## 알려진 한계와 Step 6 handoff

실제 eval_01~eval_05가 없어 이 결과를 제품 정확도로 해석할 수 없다. deterministic parser는 기존 structured memo field만 사용하며 semantic reference를 새로 추출하지 않는다. 따라서 `EARLIER`나 “먹었던 거”, “웃긴 부분” 같은 의미 참조는 안전하게 abstain한다. 실제 dataset에서 proposal miss와 selection error를 다시 분리 측정한 뒤에만 LLM/VLM 또는 다른 semantic improvement의 필요성을 판단한다.
