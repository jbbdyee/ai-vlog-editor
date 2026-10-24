# MVP-08B — SceneCandidate 로컬 사건 그룹화 오프라인 실험

상태: **오프라인 탐색 실험 완료, 제품 반영 미실행, 정식 품질 평가 미실행**. 기준 `main` 커밋 `4261227f38bd817226835f582450c98e2b5ac950`, 실행일 2026-10-24 (Asia/Seoul). [MVP-08A 설계](mvp-08a-scene-candidate-experiment-design.md)를 따르며 [v2 Detailed Plan](../roadmap/v2-plan.md)의 제품 `EventGroup`이나 자동 추천을 구현한 결과가 아니다. P1-S01 한 건의 저장 결과와 합성 부정 사례만 사용했다.

## 환경·입력·격리

- Windows checkout, Python 3.12.15의 기존 `.venv`, 로컬 PostgreSQL의 **읽기 전용 트랜잭션**을 사용했다. 외부 LLM/VLM API, FFmpeg, STT 또는 원본 영상 재분석은 호출하지 않았다.
- 실제 촬영 소스는 `evaluation/data/P1/P1_S01_take01.MOV`다. 이번 실험 입력은 해당 소스의 **기존 저장 분석 work item, SceneCandidate, SceneEvidence**다. 영상 SHA-256 `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2`는 [07A](mvp-07a-real-video-validation.md) 당시 확인한 값이며 이번 단계에서 원본을 다시 해시하거나 디코딩하지 않았다.
- 소스 ID `741a67b7-8d6b-44a8-8c5e-e023ec6991a5`, 길이 13.498초. 분석 버전 `autonomous-discovery-v0.1`, 승격 함수 버전 `autonomous-promotion-v0.3`. 저장 work ID·fingerprint와 전체 근거 ID는 Git 제외 결과 JSON에 보존했다.
- 실험 코드 [오프라인 실행기](../../evaluation/run_mvp08b_event_grouping.py)와 [전용 테스트](../../evaluation/tests/test_mvp08b_event_grouping.py)는 제품 서비스·API·DB 스키마와 분리했다. 결과 JSON은 `evaluation/tmp/mvp08b-p1-s01-offline-01.json` 및 동일 입력 반복 실행의 `...-02.json`에 새 파일로 기록했다. 두 파일의 SHA-256은 모두 `313223e662a5f30dd5194fe10d023873a2d3676aff1ecb6e5dfb7c905868ceab`이다. `evaluation/tmp/`는 Git 제외 경로다. 기존 결과를 덮어쓰지 않았다.

재현 명령(기존 로컬 DB와 `.env`가 준비된 환경에서, 새로운 출력 파일명 사용):

```powershell
.\.venv\Scripts\python.exe -m evaluation.run_mvp08b_event_grouping --source-id 741a67b7-8d6b-44a8-8c5e-e023ec6991a5 --output evaluation/tmp/mvp08b-repeat.json --reference-interval 4.00 6.22
.\.venv\Scripts\python.exe -m unittest evaluation.tests.test_mvp08b_event_grouping -v
.\.venv\Scripts\python.exe -m unittest backend.tests.test_autonomous_discovery -q
```

`--reference-interval`은 그룹화가 끝난 **후** 커버리지 계산에만 전달된다. 그룹화 함수와 입력 구조에는 Recorder Event·GT·평가 정답 필드가 없다.

## D 기준선 재현 — 성공

저장된 TRANSCRIPT·AUDIO·VISUAL modality 결과를 디코딩해 **현재** `build_promotion_manifest()`에 재입력했다. 재생한 후보 5개의 시작·종료 시각과 승격 규칙이 저장 후보와 모두 일치했다. 각 승격 쌍이 후보에 연결된 SceneEvidence에도 존재하는지 확인했다. Evidence 진단 수는 TRANSCRIPT 2, AUDIO 20, VISUAL 2, QUALITY 1이다. 아래 `∩`는 승격의 원본 근거이며, QUALITY는 겹쳐 부착될 뿐 승격 입력이 아니다.

| 저장 후보 ID | 구간·길이(초) | 생성 근거와 연결 |
| --- | --- | --- |
| `af8261aa-06bc-403e-b6ff-600a1a7b6da6` | 2.44~2.62 · 0.18 | AUDIO_ACTIVITY 2.44~2.62 ∩ VISUAL_ACTIVITY 2.40~2.80 |
| `73af993a-2666-4e9c-85d0-563df63069a7` | 4.08~4.60 · 0.52 | AUDIO_ACTIVITY 4.08~4.84 ∩ VISUAL_ACTIVITY 3.80~4.60 |
| `f64ea389-0ee7-4b17-b0b0-9d14d15e6e20` | 4.64~4.84 · 0.20 | TRANSCRIPT_STRUCTURE 4.64~6.12 ∩ AUDIO_ACTIVITY 4.08~4.84; STATIC_INTERVAL 부착 |
| `e78b6409-b0f2-4c2d-b374-c50e7659f9bb` | 5.54~6.12 · 0.58 | TRANSCRIPT_STRUCTURE 4.64~6.12 ∩ AUDIO_ACTIVITY 5.54~6.48; STATIC_INTERVAL 부착 |
| `a15a9a2f-50ce-45fb-b5b5-c8dfb419badb` | 8.86~11.00 · 2.14 | TRANSCRIPT_STRUCTURE 8.44~11.00 ∩ AUDIO_ACTIVITY 8.86~11.26; STATIC_INTERVAL 부착 |

5개 후보 길이 합계와 합집합 길이는 모두 3.62초다. 저장 후보와 Evidence는 수정하지 않았다. 자동 추천 점수·순위는 없고, MVP-07A의 5.54~6.12초 선택은 검증 스크립트가 Recorder Event와의 겹침으로 수행했다.

## C 그룹화 규칙과 추적성

`EventProposal`은 **실험용 불변 자료구조**다. 원본 후보 ID·구간, 연결 Evidence ID·유형·원본 구간, 전체 외피, 양성 Evidence 지지 구간, Evidence가 전혀 없는 구간, 두 Evidence의 교집합으로 확인된 후보 구간, 그 교집합이 없는 구간을 별개 필드로 남긴다. 같은 원본 Evidence가 후보별 SceneEvidence 행으로 복제돼 있으므로 `modality + evidence_type + 시작·끝`을 같은 근거의 식별자로 사용한다. QUALITY `STATIC_INTERVAL`과 SILENCE는 연결 정보로 보존하되 **그룹 연결 근거와 양성 지지 구간에서 제외**한다.

두 후보가 같은 승격 Evidence를 공유하고, 그 Evidence가 두 후보 사이를 시간적으로 가로지를 때만 묶는다. 간격이 두 이웃 후보 길이의 합 이상이면 묶지 않는다. 묶음의 기존 후보 구간 합집합이 전체 외피의 절반 이하가 되어도 묶지 않는다. 서로 다른 `TRANSCRIPT_STRUCTURE` 근거를 한 묶음에 넣지 않는다. 이 값과 관계 규칙은 Recorder Event 4.00~6.22초 또는 GT 경계·합격 기준을 입력받아 계산하지 않았다. 다만 P1 현상을 이미 보고 고안한 **탐색적 규칙**이므로 P1 성과를 독립 검증 성능으로 주장할 수 없다. 긴 전사가 실제로 무관한 사건을 잇거나 한 사건이 여러 전사 구간에 걸치면 오병합·과분할이 남을 수 있다.

## 실제 EventProposal 결과

| 실험 제안 ID | 외피·길이(초) | 포함 원본 후보 ID 앞부분 | 양성 Evidence 지지 | Evidence 전무 간격 | 두 근거 교집합이 없는 간격 |
| --- | --- | --- | --- | --- | --- |
| `offline-9928aee8261bb2a6` | 2.44~2.62 · 0.18 | `af8261aa` | 2.44~2.62 | 없음 | 없음 |
| `offline-f9da1c0c663e739d` | 4.08~6.12 · 2.04 | `73af993a`, `f64ea389`, `e78b6409` | 4.08~6.12 | **없음** | **4.60~4.64 (0.04초), 4.84~5.54 (0.70초)** |
| `offline-cd13a998d4218b52` | 8.86~11.00 · 2.14 | `a15a9a2f` | 8.86~11.00 | 없음 | 없음 |

4.84~5.54초에는 오디오 활동 Evidence가 없지만, 4.64~6.12초 전사 Evidence는 존재한다. 따라서 이 0.70초를 “Evidence가 전혀 없는 구간”이라고 부르지 않는다. **교차 modality의 후보 지지가 없는 구간**이다. 4.60~4.64초도 오디오 활동 4.08~4.84초가 걸쳐 있으므로 Evidence 전무 구간은 아니다. 제안의 전체 원본 후보·Evidence ID는 격리 JSON에서 역추적할 수 있다.

## D 대비 C의 탐색적 비교

| 지표 | D: 기존 후보 | C: 로컬 사건 제안 | 해석 |
| --- | ---: | ---: | --- |
| 원본 후보 수 | 5 | **5개 모두 보존** | 삭제·재생성 없음 |
| 표시 단위 수 | 5 | 3 | 3개를 한 제안으로 연결 |
| 표시 구간 외피 합계 | 3.62초 | 4.36초 | 0.74초 증가; 모두 교차 modality 비지지 간격 |
| 양성 Evidence가 전혀 없는 포함 시간 | 해당 없음 | 0초 | 전사가 오디오 공백을 가로지름 |
| 교차 modality 후보 지지 없는 포함 시간 | 0초 | 0.74초 | 길어진 외피의 비용 |
| Recorder Event 4.00~6.22초와 합집합 겹침 | 1.30/2.22초 = 58.56% | 2.04/2.22초 = 91.89% | **사후 참고치**. 외피가 빈 부분을 채웠기 때문이며 사건 품질 합격 아님 |

P1-S01의 뒤쪽 메모 발화 후보 8.86~11.00초는 앞 사건 그룹에 합쳐지지 않았다. 그러나 독립 GT가 없으므로 실제 false merge 0건이라고 정량 선언하지 않는다. 간격이 짧아도 공유 승격 Evidence가 없는 합성 사례, 긴 공백을 공유 전사가 가로지르는 사례, 서로 다른 전사 두 개가 오디오를 통해 연쇄 연결되는 사례에서는 그룹을 분리하는지 검사했다. 합성 결과는 실제 영상 의미 정확도 증거가 아니다.

## 검증 결과와 미실행 범위

- 전용 단위 테스트 **10건 통과**: 입력 순서 결정성·불변성, 근거 ID 추적, 빈 입력, 겹침·동일 구간 다른 ID, 무관한 근접 사건, 공통 QUALITY만 있는 경우, 긴 간격과 상대 경계, 서로 다른 전사의 연쇄 연결 차단, 유효하지 않은 ID·소스·시각·근거, 간격·커버리지 경계.
- P1-S01 실제 저장 work 재생 **성공**: 현재 승격 함수 결과와 DB 후보 5개 일치. 같은 DB 입력으로 격리 JSON을 두 번 생성했고 SHA-256이 동일했다. 읽기 전용 트랜잭션과 불변 자료구조를 사용했으며 원본 후보·Evidence를 쓰지 않았다.
- 관련 제품 회귀 `backend.tests.test_autonomous_discovery` **22건 통과**. 제품 코드·API·DB 스키마·의존성은 변경하지 않았다. 전체 제품 테스트는 불필요한 재실행을 피했다.
- P2·P3 실제 영상, 정식 GT 품질 평가, 사람의 그룹 의미 판정, Streamlit 사용자 조작, 렌더·자막 재생성은 **미실행**이다. 이번 checkout의 `evaluation/data/`에는 P1만 있고, focused dataset의 GT도 미동결이다. P1의 다른 촬영 파일은 이번 실험에서 분석하지 않았다.

## 실패 위험·제품 반영 권고

이번 입력에서 기준선 재생 실패와 실행 오류는 없었다. C가 4.84~5.54초의 오디오 공백을 포함하는 **2.04초 외피**를 만들었다는 점이 핵심 품질 위험이다. 전사에는 지지가 있어도 실제 영상에 사건이 이어지는지는 확인되지 않았다. 긴 발화가 여러 사건을 포괄하면 false merge, 서로 다른 전사 구간의 단일 사건은 과분할이 발생할 수 있다. 원본 후보 계보가 남아도 제품이 제안 외피만 표시하면 짧은 반응이 묻힐 수 있다.

**현 단계에서 제품 반영은 권하지 않는다.** D 후보 생성과 사용자 대상 API를 유지하고 C를 오프라인 비교 대상으로 둔다. 다음 단계 전에는 P1의 다른 사건과 P2·P3의 독립적인 영상·주석·무관한 근접 사건 부정 사례를 확보하고, 병합 규칙·지표·실패 기준을 검증 전에 고정해야 한다. GT freeze 전 탐색 지표와 정식 Dataset B 품질 판정을 분리한다. 제품 반영을 논의한다면 기존 후보와 Evidence 계보, 비지지 간격 표시, 선택·렌더 경로의 회귀 확인이 필요하다. 기존 평가 계약·GT·Manifest는 결과에 맞춰 수정하지 않는다.
