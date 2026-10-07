# G5-B2 사전 등록 Coverage

이 표는 촬영 계획의 범위이지 달성된 GT·성능이 아니다. `COVERED`는 시나리오에 조건을 명시한 상태, `CONDITIONAL`은 촬영·STT·Proposal·bounded frame 처리 후 실제 성립을 확인해야 하는 상태다. `OPTIONAL`은 v0.1 필수 평가 밖이다. 조건이 성립하지 않으면 G5-B4에서 정직하게 `NOT_COVERED`로 기록하며 모델 결과를 보고 manifest를 바꾸지 않는다.

| Memo case | 상태 | 계획 Source | 조건 |
|---|---|---|---|
| A1 unique JUST_NOW | COVERED | P1-S01 | 쉬운 control |
| A2 multiple plausible | COVERED | P1-S03 | 두 행동이 모두 합당 |
| A3 EARLIER | COVERED | P1-S02 | 앞선 떨어뜨림 |
| A4 lexical recent distractor | COVERED | P1-S02 | 최근 책상 정리 |
| A5 semantic without lexical overlap | CONDITIONAL | P1-S06 | 시각적 선물 열기와 실제 transcript/proposal의 어휘 차이 확인 |
| A6 no valid earlier scene | COVERED | P1-S04 | 해당 행동 없음 |
| A7 insufficient transcript | CONDITIONAL | P1-S06 | 말 없는 행동; `INSUFFICIENT_EVIDENCE`가 정답인지 bounded input 확인 |
| A8 correct ambiguity | COVERED | P1-S03 | 사전에 target 하나를 정하지 않음 |
| A9 misleading lexical overlap | COVERED | P1-S02 | 정리 설명은 target 아님 |
| A10 spoken prompt injection | COVERED | P1-S05 | P99는 dummy speech |
| A11 STT noise | CONDITIONAL | P1-S02 또는 P1-S06 | 자연스러운 발화·환경 소음만 허용; 실제 STT 오류를 사전 가정하지 않음 |
| A12 meaningful quiet scene | COVERED | P1-S06 | 조용한 선물 열기 |

| Autonomous case | 상태 | 계획 Source | 조건 |
|---|---|---|---|
| B1 transcript + audio reaction | CONDITIONAL | P1-S01, P2-S04 | 실제 transcript/audio cue 확인 |
| B2 meaningful dialogue | COVERED | P3-S01 | 포장 설명 |
| B3 visual-only important | COVERED | P1-S06 | 행동 중 말 없음 |
| B4 quiet important | COVERED | P1-S06 | 조용한 행동 |
| B5 audio reaction, irrelevant visual | COVERED | P2-S04 | 빈 공간 + off-camera 웃음의 별도 구간 |
| B6 meaningless visual activity | COVERED | P2-S06 | 사건 없는 pan |
| B7 meaningful long silence | CONDITIONAL | P1-S06 | 실제 자연스러운 침묵이 analyzer 기준 충족 시만 |
| B8 meaningful static | CONDITIONAL | P2-S01 | 실제 정적 구도와 의미 여부 확인 |
| B9 filler | COVERED | P3-S05 | 비의도 장면 |
| B10 accidental recording | COVERED | P3-S05 | 카메라 실수 상황 |
| B11 poor quality but meaningful | COVERED | P3-S06 | 식별 가능한 저품질 |
| B12 false cross-modal coincidence | CONDITIONAL | P2-S06 | 실제 signal 시간 겹침 확인 |

| VLM case | 상태 | 계획 Source | 조건 |
|---|---|---|---|
| C1 visual important, little speech | COVERED | P1-S06 | 얼굴 없는 선물 행동 |
| C2 same transcript, different visual relevance | CONDITIONAL | P1-S02, P1-S06 | 동일 bounded transcript 의미의 두 Proposal이 실제 생성될 경우 |
| C3 visible nonverbal reaction | COVERED | P2-S04 | 손짓·몸짓, 얼굴 없음 |
| C4 quiet meaningful action | COVERED | P1-S06 | 선물 열기 |
| C5 meaningless motion | COVERED | P2-S06 | pan |
| C6 similar-looking proposals | CONDITIONAL | P3-S02, P3-S04 | bounded proposal와 frame 구성이 실제 유사할 때 |
| C7 poor quality, important | COVERED | P3-S06 | 품질과 가치 분리 |
| C8 insufficient bounded visual evidence | CONDITIONAL | P1-S06 | 3-frame contact sheet에 핵심 행동이 누락될 때만 |
| C9 multiple plausible | CONDITIONAL | P1-S03 | visual proposals 둘 이상 생성되고 구별 불가할 때만 |
| C10 visual text injection | OPTIONAL | 없음 | v0.1 촬영을 늘리지 않음; threat review 후 별도 버전 |

| Event case | 상태 | 계획 Source / pair | 조건 |
|---|---|---|---|
| D1 same Event across Sources | COVERED | P2-S01↔S02 | 실제 동일 도착 활동이어야 함 |
| D2 chronological continuation | COVERED | P2-S02→S03 | earlier→later |
| D3 reaction in separate Source | COVERED | P2-S04→S02 | reaction→trigger |
| D4 exact duplicate | CONDITIONAL | P3-S02↔S03 | byte-equal source fingerprint와 exact normalized Candidate interval 모두 필요 |
| D5 same location, different Event | COVERED | P2-S01↔S05 | ARRIVAL-01 vs DEPARTURE-02 |
| D6 same people, different Event | CONDITIONAL | P2-S02↔S05, P3-S01↔S04 | 동일 인물이 실제 등장·확인될 경우; 얼굴은 촬영하지 않음 |
| D7 similar transcript, different Event | CONDITIONAL | P3-S01↔S04 | 실제 STT 유사성 확인 |
| D8 different transcript, same Event | CONDITIONAL | P3-S01↔S02 | 다른 발화·무발화와 동일 포장 활동 확인 |
| D9 adjacent but unrelated | COVERED | P2-S04↔S05 | 파일 순서만 인접 |
| D10 visually similar, unrelated | COVERED | P3-S02↔S04 | 다른 포장 Event |
| D11 legitimately unassigned | COVERED | P3-S05 | Event에 억지 배정 금지 |
| D12 bridge overmerge | CONDITIONAL | P3-S01/S02 vs P3-S04 | 실제 retained bridge가 생긴 경우만; PACKING-01/02 must-not-merge는 항상 유지 |

현재는 실제 media·Candidate·Proposal이 없으므로 `COVERED`도 정확도 보증이 아니다. Relation GT와 EventGroup GT는 G5-B4에서 별도 주석으로 만든다. 같은 Event identity만으로 `SAME_EVENT` Relation을 모든 pair에 자동 부여하지 않는다.
