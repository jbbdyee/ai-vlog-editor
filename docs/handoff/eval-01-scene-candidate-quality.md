# EVAL-01 — SceneCandidate 동결 GT 품질 평가 준비 진단

상태: **평가 자료·기존 출력 진단 완료, 동결 GT 기반 정량 품질 평가는 미실행**. 점검일 2026-10-26, Windows `main` HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. WEB-01~04의 미커밋 작업과 기존 백엔드 테스트 3개를 보존했다. 원본·시나리오·GT 초안·Manifest·평가 계약·알고리즘을 변경하지 않았고 신규 영상 분석, 외부 LLM/VLM 호출, DB 쓰기를 실행하지 않았다.

## 평가 계약과 입력 상태

- [focused dataset v0.1](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/README.md)의 B Autonomous 대상은 사람이 `should_consider`로 주석한 구간이다. 기존 계약의 target recall 판정은 **target coverage ≥ 0.70 및 temporal IoU ≥ 0.30**이다. Candidate reduction rate는 GT recall과 함께 보고해야 한다. 이 기준과 임계값은 변경하지 않았다. 정식 Precision/F1이나 후보 과다 생성의 합격 기준은 이 계약에서 확인하지 못해 임의로 정의하지 않았다.
- `evaluation/validate_focused_manifest.py`: **PASS**, 3 Project·18 Scenario·46 Coverage case, 문제 0건. 이는 사전 등록 구조 검사이며 촬영·GT 완료를 뜻하지 않는다.
- `evaluation/validate_focused_gt.py --mode draft`: **PASS**, 현존 P1 GT 초안 JSON 8개 구조 검사, 문제 0건. Autonomous 6개와 Memo 2개이며 모두 **미동결**이다.
- 같은 검증기의 `--mode freeze-ready`: **PENDING**, 미비 28건. P2/P3 source envelope 12건, COVERED task GT 13건, P1/P2/P3 Event GT 3건이다. 이 모드는 미디어 의미나 인간 동결 승인을 판정하지 않는다. 현존 파일에도 별도 승인된 freeze 기록이 없다.
- `evaluation/data/P1/`에 실제 MOV 7개가 있다. P1-S03은 보존 take01과 검토에서 선택한 take02를 구분한다. P2/P3 실제 미디어는 이 checkout에서 확인되지 않았다. P1-S01은 [08A/B 개발 사례](mvp-08a-scene-candidate-experiment-design.md)이며 독립 성능 집계에 넣지 않는다. P1-S02도 WEB-04에서 사용자 흐름 개발·검증에 사용됐다. 원본 해시는 [08D 점검](mvp-08d-p1-evaluation-environment-readiness.md)과 [WEB-04 기록](web-04-react-e2e-validation.md)에 보존한다.

## 재사용한 코드와 실행 범위

위 두 기존 검증기를 변경 없이 재실행했다. `evaluation/run_autonomous_baseline.py`는 **합성 신호**용이며 GT가 없어 recall/precision을 `null`로 보고한다. `backend/app/services/candidate_evaluator.py`는 과거 고정 Window 후보의 IoU/Coverage 함수로, 현재 focused Dataset B의 다수 후보·동결 GT 평가 실행기는 아니다. 이를 정식 B 점수로 재사용하지 않았다. [08B 오프라인 그룹화 실행기](../../evaluation/run_mvp08b_event_grouping.py)는 단일 P1-S01 개발 사례 탐색이며 제품 후보 품질 평가기가 아니다.

현재 `autonomous_discovery.py`의 승격은 같은 소스에서 반응 어휘+오디오, 전사 구조+오디오, 오디오+영상 Evidence의 **양의 길이 교집합**으로 구간을 만든다. 동일 구간을 중복 제거하고 후보와 겹치는 Evidence를 연결한다. QUALITY의 `STATIC_INTERVAL`은 부착 근거일 수 있지만 승격을 만들지 않는다. 후보에는 자동 추천 순위가 없다. 위 로직과 설정·기존 저장 결과는 수정하지 않았다.

읽기 전용 PostgreSQL 트랜잭션에서 WEB-04 격리 프로젝트의 P1-S01·S02 저장 소스를 조회했다. 양쪽 모두 소스 처리 `COMPLETED`이며, 저장된 **AUTONOMOUS 후보 생성 현황**은 다음과 같다. 숫자는 정답 비교와 무관한 구조 진단값이다. 연결 Evidence 수는 후보마다 저장된 행의 수로, 원본 Evidence의 고유 개수와 다르다.

| 소스 | 후보 수 | 후보 길이 최소·중앙값·최대 | 후보 길이 단순합 | 연결 Evidence 행 | 관찰 |
| --- | ---: | --- | ---: | ---: | --- |
| P1-S01 · 13.498초 | 5 | 0.18·0.52·2.14초 | 3.62초 | 13 | 4.08–4.60, 4.64–4.84, 5.54–6.12초로 짧게 나뉨 |
| P1-S02 · 36.228초 | 12 | 0.10·1.19·3.24초 | 18.32초 | 34 | 4.60–5.20과 4.60–5.26초처럼 겹치는 후보도 있음 |

두 소스 17개 후보 모두 연결 Evidence가 2개 이상이다. P1-S01 연결 행은 AUDIO 5·VISUAL 2·TRANSCRIPT 3·QUALITY 3, P1-S02는 AUDIO 12·VISUAL 3·TRANSCRIPT 12·QUALITY 7이다. 이는 **저장 행의 연결 상태**만 보여준다. 각 후보의 정확한 승격 쌍, GT상 의미, 과잉 여부를 이 집계만으로 확정하지 않는다. P1-S01 5개 구간·승격 쌍의 상세 재현은 [08A 기준선](mvp-08a-scene-candidate-experiment-design.md)과 [08B 결과](mvp-08b-event-grouping-experiment.md)에 있다. WEB-04의 17개 후보는 화면·렌더 기술 검증 결과이며 품질 점수가 아니다.

## 공식 평가 결과와 실패 유형

| 요청 지표 | EVAL-01 결과 | 이유 |
| --- | --- | --- |
| 후보 생성 성공률 | **미평가** | 평가 모집단과 동결 GT가 없고, 확인한 2개 처리 소스에 후보가 생성됐다는 기술 사실만 있음 |
| GT 중첩·target recall·검출 누락 | **미평가** | 동결 `should_consider` 구간 부재. P1 초안이나 Recorder Event를 정답으로 승격하지 않음 |
| Precision·F1·과다 생성률 | **미평가** | 공식 정의/판정 기준과 동결 판정 자료가 없음. 12개 후보 자체는 false positive 증거가 아님 |
| 소스별 수·길이·Evidence 연결 | **참고 진단 완료** | 위 2개 저장 소스의 읽기 전용 DB 조회. P1-S03~S06/P2/P3의 현재 분석 출력은 이번 평가에 포함하지 않음 |
| 동일 입력 재현성 | **미평가** | 신규 분석 재실행·스냅샷 비교를 수행하지 않음. 08B의 단일 사례 기준선 재현과 구분 |

관찰된 실패 **위험**은 짧은 후보 분절(P1-S01), 겹치는 후보의 사용자 선택 부담(P1-S02), P1 외 일반화 자료 부족이다. 앞의 둘을 GT 검출 실패·false promotion으로 판정할 근거는 아직 없다. P1-S01 분절의 코드상 원인은 [08A](mvp-08a-scene-candidate-experiment-design.md)의 교집합 경계와 오디오 활동 공백 재구성으로 확인됐다. P1-S02의 의미적 실패 유형·사용자 편집 영향은 독립 주석 후 확인해야 한다. 잘 검출한 장면, 시나리오별 성능 차이, 추천 품질 합격을 이번 결과로 선언하지 않는다.

## 후속 우선순위와 재검증

1. **평가 선행 조건:** P1~P3의 실제 대상 미디어·블라인드 독립 주석을 확보하고 기존 계약대로 GT를 검토·동결한다. 현재 근거는 freeze-ready PENDING 28건과 P2/P3 미디어 부재다. 데이터 보호·주석 불일치·기존 초안에 의한 누출이 위험이다. 재검증은 기존 Manifest/GT validator, 미디어 SHA-256 대조, 인간 승인 기록 확인으로 수행한다. 평가 결과에 맞춘 GT 수정은 하지 않는다.
2. **평가 실행 준비:** 동결 GT와 고정된 후보/분석 버전·소스 해시·출력 스냅샷의 대응을 사전 등록하고, Dataset B의 target coverage+tIoU, 후보 축소율, 누락·근거 계보를 계산할 재현 가능한 읽기 전용 실행을 마련한다. 현 코드에는 focused B 정식 scorer가 확인되지 않았다. 매칭 방식·중복 후보·무후보·실패 소스를 결과를 본 뒤 바꾸면 편향 위험이 있다. 기존 계약 외 수치는 참고 지표로 분리한다. 동일 입력 반복과 수동 표본 대조로 검증한다.
3. **품질 개선 후보, 적용 보류:** P1-S01의 0.18~0.58초 분절과 08B의 D/C 탐색을 근거로, 동결·독립 자료에서 사건 커버리지와 false merge를 함께 비교한다. 변경 범위는 향후 후보 그룹화/표시 실험이며 이번에는 제품 코드 변경이 없다. 긴 외피의 불필요 구간·짧은 반응 손실이 회귀 위험이다. P1-S01은 개발 사례로 분리하고 P2/P3 및 무관한 사건·조용한 장면을 포함해 기존 기준으로 다시 측정한다.
4. **겹침 후보 분석, 적용 보류:** P1-S02의 4.60초 시작 후보 2개를 근거로 중복/겹침이 선택 부담을 높이는지 독립 주석과 사용자 선택 기록에서 확인한다. 임의 병합은 서로 다른 사건의 false merge와 Evidence 계보 손실 위험이 있다. 개선안을 채택할 경우 후보 수, target recall, 누락, false merge와 기존 편집 API 회귀를 함께 검증한다.

공식 정량 결과가 없으므로 위 순위는 **평가 가능 상태 확보와 가설 검증 순서**다. 성능 향상 우선순위를 확정한 결과가 아니다. [08C 독립 평가 절차](mvp-08c-independent-evaluation-readiness.md)와 [08D 블라인드 주석 준비](mvp-08d-p1-evaluation-environment-readiness.md)를 따른다. 신규 분석·평가 실행은 동결 자료와 격리 출력이 준비된 뒤 별도 수행한다.
