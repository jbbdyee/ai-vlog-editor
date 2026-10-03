# Cross-video Event Grouping deterministic baseline v0.1

## Run scope

- runner: `evaluation/run_event_grouping_baseline.py`
- dataset: synthetic grouping mechanics + 600 Candidate scale
- actual media: 없음
- cross-video semantic GT: 없음
- LLM calls: 0
- VLM calls: 0
- new MCP Tool: 0

이 평가는 Event 의미 정확도가 아니라 pair reduction, conservative grouping mechanics와 incremental comparison 범위를 검증한다. Synthetic accepted `SAME_EVENT` edge는 grouping engine fixture이며 production semantic inference 결과가 아니다.

## Pair reduction result

- Candidate count: 600
- possible unordered pairs: 179,700
- retained pairs: 599
- reduction rate: 0.99666667
- retained reason: `SOURCE_NEIGHBOR_HINT` 599
- incremental new-Candidate possible pairs: 599
- incremental retained pairs: 1
- full pair materialization: 없음

Source ordering은 capture time이 아니라 deterministic weak neighborhood hint다. Transcript와 Evidence overlap도 pair retention reason일 뿐 `SAME_EVENT` 근거로 승격하지 않는다. Common token/evidence bucket에는 bounded cap을 적용하며 정확한 threshold는 최적값이 아니다.

## Focused grouping mechanics

- accepted relation fixture EventGroup: 2
- grouped Candidate: 4
- unassigned Candidate: 1
- singleton Group avoided: 1
- single bridge merge prevented: 1
- production deterministic relation: exact `DUPLICATE` only
- automatic `SAME_EVENT`: 0
- automatic `CONTINUATION`: 0
- automatic `REACTION_TO`: 0

Group expansion은 새 Candidate가 기존 모든 member와 직접 accepted `SAME_EVENT` edge를 가질 때만 허용한다. 하나의 bridge는 기존 Group 두 개를 합치지 않는다. 근거가 없거나 여러 Group과 충돌하는 Candidate는 실패가 아니라 unassigned다.

## PostgreSQL 17.11 integration

- 500 persisted Candidate possible pairs: 124,750
- retained pairs: 0
- EventGroup: 0
- unassigned: 500
- 새 Candidate 1개 추가 후 incremental possible comparisons: 500
- incremental retained pairs: 0
- scale scenario 최대 test rows: Project 1 + SourceVideo 1 + Candidate 501 + WorkItem 4 + Attempt 4 = 511
- Relation / EventGroup / Member rows: 0

별도 focused persistence scenario에서 canonical `DUPLICATE`, reverse duplicate 억제, accepted `SAME_EVENT` fixture Group, 새 Session durability, idempotent reuse와 cross-project 거부를 확인했다. Integration fixture는 테스트 후 정리된다.

## Runtime

- synthetic runner processing time: 0.243353초
- tracemalloc peak: 1,367,519 bytes

실행 환경에 따라 달라지는 참고값이며 운영 성능 보장을 의미하지 않는다.

## Known limitations / Step 7-C handoff

- 실제 cross-video media와 사람이 annotation한 Event GT가 없어 pair-filter recall, relation precision/recall과 grouping semantic accuracy를 계산할 수 없다.
- source ingestion order는 실제 capture order가 아니다.
- simple deterministic tokenization은 한국어 형태소나 semantic synonym을 이해하지 못한다.
- `SceneRelation`은 현재 WorkItem FK와 relation별 fingerprint를 직접 보유하지 않아 opaque work reference와 Group/WorkItem fingerprint를 사용한다.
- Step 7-C는 실제 focused GT와 Step 6 provider reliability를 확보한 뒤 retained pair에만 selective semantic relation을 적용해야 한다.
