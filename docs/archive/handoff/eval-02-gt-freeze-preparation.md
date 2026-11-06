# EVAL-02 — GT 동결 준비 및 사람 중심 주석 작업표

상태: **준비 자료 점검·작업표 완료, 주석 작성·승인·GT 동결·정량 평가는 미실행**. 2026-10-26, Windows `main` HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB-01~04·[EVAL-01](eval-01-scene-candidate-quality.md) 미커밋 변경과 백엔드 테스트 3개를 보존했다. 이 문서는 [focused dataset v0.1](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/README.md)의 계약·Manifest·GT·임계값을 변경하지 않는다. AI 정답 생성, 자동 동결, SceneCandidate 결과를 정답에 복사하는 작업은 수행하지 않았다.

## 기존 계약과 현재 검사

- [사전 등록 Manifest](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/manifests/recording-scenarios.json) v3는 3 Project·18 Scenario를 계획하며 **GT가 아니다**. [Coverage](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/manifests/COVERAGE.md)의 `COVERED`만 freeze-ready의 필수 작업으로 취급하고 `CONDITIONAL`/`OPTIONAL`을 억지로 필수 GT로 승격하지 않는다.
- [주석 지침](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/ANNOTATION_GUIDE.md), [기존 주석 폴더 안내](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/annotations/README.md), `schema/common.schema.json` 및 Memo/Autonomous/VLM/Event 스키마를 재사용한다. Dataset B에서 `should_consider` 대상의 recall은 target coverage ≥ 0.70 **및** temporal IoU ≥ 0.30일 때만 인정한다. Candidate reduction rate와 GT recall을 함께 보고한다. 평가 기준은 바꾸지 않았다.
- 재실행: `python evaluation/validate_focused_manifest.py` → **PASS**, 3 Project·18 Scenario·46 Coverage case·문제 0. `python evaluation/validate_focused_gt.py --mode draft` → **PASS**, 현존 P1 초안 8 JSON·문제 0. 같은 검사 `--mode freeze-ready` → **PENDING**, 28건. 초안 구조 PASS는 사람의 정확성 승인이나 GT 동결이 아니다. 검증기는 미디어 의미·원본 해시 일치·사람 승인 여부를 검사하지 않는다.
- P1 초안은 Autonomous 6개와 Memo 2개다. P1-S01/S02/S05/S06의 `SELECTED` Memo에는 대상 구간의 사람 검토 외에 **실제 고정 Proposal manifest의 ID·fingerprint로 파생 매핑을 확정**해야 한다. 부적절한 Proposal을 정답으로 표시하거나 촬영 중 발화한 `P99`를 ID로 사용하지 않는다. P1-S03/S04의 기존 Memo 초안도 별도 인간 검토·동결이 필요하다. 현 스키마에는 기계 판독 가능한 인간 동결 승인 필드가 없어 freeze-ready PASS만으로 동결을 선언할 수 없다.

## Freeze-ready의 28개 미비 항목

아래 순번·코드·위치는 검사기의 **실제 출력 순서**다. `S`는 소스 envelope, `T`는 COVERED 작업 GT, `E`는 Project Event GT를 뜻한다. 표의 사람 판단은 모델 출력이나 기존 초안을 정답으로 수용하라는 뜻이 아니다. 자동 검사는 파일/참조/구간 구조를 확인할 뿐 내용의 참을 판정하지 않는다.

| # | 검사 코드·대상 | 부족한 자료 | 사람이 할 판단 | 자동으로 확인할 것·선행 조건 |
| ---: | --- | --- | --- | --- |
| 01 | S · P2-S01 | 원본 식별과 source envelope | 실제 도착 구간·시나리오 대응 확인 | 원본 확보 후 SHA-256·길이·source ID·schema 검사 |
| 02 | S · P2-S02 | source envelope | 같은 실제 도착의 다음 POV인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 03 | S · P2-S03 | source envelope | 가방 내려놓기가 연속 사건인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 04 | S · P2-S04 | source envelope | 실제 반응과 무관한 소리 구간을 구별 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 05 | S · P2-S05 | source envelope | 앞 도착과 별도 외출인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 06 | S · P2-S06 | source envelope | 사건 없는 pan인지 원본에서 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 07 | S · P3-S01 | source envelope | 첫 외출 준비의 실제 행위 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 08 | S · P3-S02 | source envelope | 같은 준비의 연속 POV인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 09 | S · P3-S03 | 별도 등록의 source envelope | S02의 **정확한 바이트 복사**로 등록할지 사람 확인 | 원본/정확한 사본 확보 후 S02와 SHA-256 동일성·별도 source ID 검사; 임의 대체 금지 |
| 10 | S · P3-S04 | source envelope | 유사하지만 별도 준비인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 11 | S · P3-S05 | source envelope | 실제 의미 없는 우발 촬영인지 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 12 | S · P3-S06 | source envelope | 어둡거나 흔들린 영상의 행위 식별 가능성 확인 | 원본 확보 후 해시·길이·시나리오 참조 검사 |
| 13 | T · P1-S01 Memo | `SELECTED` Memo GT | 원본에서 메모 경계·참조 사건 확인 | 사람 검토 후 고정 Proposal ID·fingerprint 연결, Memo schema 검사 |
| 14 | T · P1-S02 Memo | `SELECTED` Memo GT | 앞 사건과 뒤 무관한 대화를 구별하고 메모 경계 확인 | 고정 Proposal ID·fingerprint와 소스 참조 검사 |
| 15 | T · P1-S05 Memo | `SELECTED` Memo GT | 가짜 `P99` 지시와 정상 메모를 구분해 시각 확인 | 고정 Proposal ID·fingerprint 검사; `P99` 임의 사용 금지 |
| 16 | T · P1-S06 Memo | `SELECTED` Memo GT | 개봉과 뒤의 별도 제스처, 불확실한 메모 시작 구분 | 고정 Proposal ID·fingerprint·구간 검사 |
| 17 | T · P1-S06 VLM | bounded 시각 GT | 전체 원본의 지식과 제한된 3-frame 표현에서 보이는 사실을 구분 | 고정 contact-sheet 표현·Proposal fingerprint·VLM schema·개인정보 정책 검사 |
| 18 | T · P2-S04 Autonomous | 반응/무관 소리 GT | 실제 의미 있는 장면과 audio-only 방해 구간 주석 | P2-S04 원본·envelope 후 시간 경계·`should_consider` 등 schema 검사 |
| 19 | T · P2-S04 VLM | bounded 시각 GT | 반응이 제한된 프레임에 보이는지 독립 판단 | 원본·고정 표현·Proposal fingerprint·privacy 검사 |
| 20 | T · P2-S06 Autonomous | 무사건/소리 GT | 실제 무사건 여부와 예외적 의미 구간 확인 | P2-S06 원본·envelope 후 구간·schema 검사 |
| 21 | T · P2-S06 VLM | bounded 시각 GT | pan의 의미를 제한된 프레임으로 판단 가능한지 확인 | 원본·고정 표현·Proposal fingerprint·privacy 검사 |
| 22 | T · P3-S01 Autonomous | 준비 사건 GT | 첫 준비 행동의 포함/제외 구간 확인 | P3-S01 원본·envelope 후 구간·schema 검사 |
| 23 | T · P3-S05 Autonomous | 우발 촬영 GT | 의미 있는 사건이 정말 없는지 전 영상 검토 | P3-S05 원본·envelope 후 빈/음성 구간 구조 검사 |
| 24 | T · P3-S06 Autonomous | 낮은 품질의 식별 가능한 행위 GT | 의미와 기술 품질을 분리해 판단 | P3-S06 원본·envelope 후 구간·schema 검사 |
| 25 | T · P3-S06 VLM | bounded 시각 GT | 어둡거나 흔들린 제한 프레임으로 판단 가능한지 확인 | 원본·고정 표현·Proposal fingerprint·privacy 검사 |
| 26 | E · P1 Project | Project Event GT | 반복 책상 사건의 동일성, 관계와 must-not-merge 검토 | P1 원본·고정 Candidate catalog 후 소유권·방향·참조·schema 검사 |
| 27 | E · P2 Project | Project Event GT | 도착 연속성, 반응→원인, 별도 출발 판단 | P2 원본·고정 catalog 후 방향·참조·schema 검사 |
| 28 | E · P3 Project | Project Event GT | 첫/둘째 준비 분리와 S02/S03 exact duplicate 판단 | P3 원본·고정 catalog 후 해시 동일성·방향·참조·schema 검사 |

`S` 12건 + `T` 13건 + `E` 3건 = **28건**이다. 하나의 신규 GT 문서가 source envelope와 작업 GT를 함께 해결할 수 있으므로 28건을 28개 파일로 오해하지 않는다. 기존 P1 Autonomous 6개·Memo 2개의 **인간 승인 미완료**는 이 28건에 별도 issue로 나타나지 않는다. Conditional/Optional의 실제 성립 여부, P1의 촬영 지시와 실제 촬영 간 차이, 모든 영상의 개인정보/시각적 충분성도 사람 검토가 필요하다.

## 현재 원본 영상 인벤토리

읽기 전용 SHA-256과 번들 FFprobe 9.0.2의 format duration을 **현재 파일에서 재측정**했다. 크기는 바이트다. macOS 보조 파일 `._*`는 영상에서 제외했다. 파일명은 Manifest가 지정한 영상 이름이 아니며, P1의 실제 영상·기존 초안·촬영자 검토 기록을 함께 대조한 대응이다. Manifest의 `recommended_duration_seconds`는 촬영 지침이며 짧거나 긴 영상을 임의로 보정하지 않는다.

| 시나리오 / 용도 | 저장소 상대 경로 | 크기 | 길이(초) | SHA-256·초안 대조 |
| --- | --- | ---: | ---: | --- |
| P1-S01 | `evaluation/data/P1/P1_S01_take01.MOV` | 141,327,567 | 13.498333 | `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2` · 일치 |
| P1-S02 | `evaluation/data/P1/P1_S02_take01.MOV` | 378,391,573 | 36.228333 | `f158d2260bd3c7b48d0d88a130d922ba0c8d20f191820ec8af0f58b1af78ce95` · 일치 |
| P1-S03 보존 take | `evaluation/data/P1/P1_S03_take01.MOV` | 375,833,662 | 36.011667 | `24031f14e7a403444545064cdeba845da0843fe070d099e1aaf2b51fc7c934db` · 초안 대상 아님 |
| P1-S03 선택 take | `evaluation/data/P1/P1_S03_take02.MOV` | 656,003,181 | 62.910000 | `ae9511b2167c632d0e80534221ff441b90d6ad0e2963ea697e81a28332c74313` · 일치 |
| P1-S04 | `evaluation/data/P1/P1_S04_take01.MOV` | 317,285,856 | 30.365000 | `c9508e46897bae6477a2159fb0404333839a2bb69f10e7d5b4f282f74b403450` · 일치 |
| P1-S05 | `evaluation/data/P1/P1_S05_take01.MOV` | 231,971,329 | 22.130000 | `a32ac2b77943e705f4c3ee0873650d29b1608ebfcaa50c2014c78d2ae11f5034` · 일치 |
| P1-S06 | `evaluation/data/P1/P1_S06_take01.MOV` | 52,479,057 | 31.930000 | `fc8ae4ae9c6eb5dbf57d14e452359ff1f42ee76482b10e387aaec143fef52639` · 일치 |

**주석 가능한 범위:** P1-S01~S06의 원본을 사람이 검토할 수 있다. S03은 검토 기록대로 take02를 대상으로 하고 take01은 보존한다. P1-S01은 08A/B 개발 사례이므로 새로운 독립 성능 집계에 넣지 않는다. S02도 WEB-04 기술 검증에 사용됐다. P2-S01~S06, P3-S01~S06에 대응하는 원본은 이 checkout의 `evaluation/data/`에서 **모두 누락**되어 파일명·해시·길이를 알 수 없다. P3-S03은 Manifest상 S02 원본의 정확한 바이트 복사로 **별도 등록 예정**이며 현재 복사본도 없다. 누락 영상을 추정 이름으로 만들거나 다른 영상으로 대체하지 않는다.

## 사람 중심 주석 작업표

기존 [08D의 블라인드 주석 절차](mvp-08d-p1-evaluation-environment-readiness.md)와 [주석 지침](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/ANNOTATION_GUIDE.md)을 사용한다. 새 앱·평가 체계·GT JSON을 만들지 않았다. 다음 빈 작업표는 **사람용 체크리스트**이며 schema-valid GT나 실제 주석이 아니다.

| 확인 항목 | 평가자가 직접 적을 값 / 확인 방법 |
| --- | --- |
| 사례 등록 | 불투명한 사례 ID, Manifest scenario ID, 선택 take, 원본 SHA-256·FFprobe 길이, 관찰 날짜 |
| 원본 관찰 | 전 구간 재생·필요 시 반복; 실제 행동/반응/메모/무사건 구간을 원본 시각 `start_seconds`–`end_seconds`로 기록 |
| Dataset B 구간 | `should_consider`, `should_exclude`, semantic/reaction/user value, 기술 문제, 예상 관측 modality·type, `ambiguity`, 판단 근거를 [Autonomous 스키마](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/schema/autonomous.schema.json)에 맞춰 사람 판단으로 작성 |
| 불명확한 경계 | 가능한 범위와 이유를 작업 메모에 적고 확실하지 않은 밀리초 정확도를 주장하지 않음. 의견을 모으기 전 후보 출력이나 초안 구간을 보지 않음 |
| Memo / VLM / Event | 각 [Memo](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/schema/memo.schema.json)·[VLM](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/schema/vlm.schema.json)·[Event](../../evaluation/datasets/cutory-v2-focused-eval-v0.1/schema/event.schema.json) 스키마와 기존 지침을 따름. Memo의 원본 의도/구간을 먼저 판단; Proposal ID는 고정 manifest에서 나중에 파생. VLM은 허용된 bounded 표현만 보고 판단 |
| 독립 검토 | 두 번째 평가자가 첫 주석·기존 GT 초안·D/C/SceneCandidate 출력 없이 같은 원본을 독립 기록. 이미 출력/초안을 본 사람의 결과는 독립 주석으로 표시하지 않음 |
| 불일치 조정 | 경계·사건 수·포함/제외·Event 동일성의 차이를 원본으로 재검토. 최초 기록과 조정 사유를 보존하고 필요하면 제3자 판정 |
| 승인·고정 | 지정된 사람 책임자가 media hash, GT revision, schema/validator 결과, 남은 모호성, privacy를 확인해 승인 기록을 별도로 남김. 기존 revision은 덮어쓰지 않고 수정 시 새 revision·`revision_reason` 보존 |

**격리:** 평가자에게 원본과 필요한 맥락만 안전하게 제공한다. 기존 P1 초안, Recorder Event, 촬영자 review notes, D/C 후보·Evidence·점수, 08B 기대 수치를 독립 주석자에게 노출하지 않는다. 이미 접한 사람은 검토자나 조정자로 참여할 수 있어도 독립 블라인드 평가자로 세지 않는다. 원본·프레임·개인정보·비밀값은 Git에 넣지 않는다. 기존 P1 초안은 버리지 않고 사람 검토 때 편향 위험을 밝힌 역사적 자료로 보존한다.

## 동결 전 검사와 책임

저장소 루트의 기존 `.venv`에서 아래 명령을 차례로 실행한다. `draft`의 PASS와 `freeze-ready`의 PASS도 각각 **검사 가능한 구조의 통과**를 뜻한다. 사람 승인과 실제 영상 진실성 확인은 별개다.

```powershell
.\.venv\Scripts\python.exe evaluation\validate_focused_manifest.py
.\.venv\Scripts\python.exe evaluation\validate_focused_gt.py --mode draft
.\.venv\Scripts\python.exe evaluation\validate_focused_gt.py --mode freeze-ready
```

1. P2/P3 원본을 확보한 뒤 **읽기 전용** FFprobe·SHA-256으로 Manifest 시나리오, 별도 source ID, P3 exact duplicate 조건을 확인한다. P1의 실제 촬영 편차는 review 기록에 유지하고 Manifest를 결과에 맞춰 변경하지 않는다.
2. 독립 주석·조정·개인정보 검토를 마친 뒤 기존 스키마에 맞는 문서를 **새 revision으로** 준비하고 `draft` 검사를 실행한다. `FAIL`은 구조/참조 오류로 수정; `PENDING`은 실제 미비로 남긴다. `SELECTED`의 Proposal ID/fingerprint는 고정된 실제 generator 출력에서 파생하고 매핑을 Provider 호출 전에 고정한다. `--proposal-index`가 필요한 경우 실제 fingerprint→ID 목록만 제공하며 가짜 ID를 넣지 않는다.
3. `freeze-ready`를 다시 실행해 28개 issue가 해결됐는지 확인한다. 미비가 남으면 **PENDING**을 유지한다. validator가 확인하지 못하는 원본 해시·semantic 사실·bounded 시각 충분성·주석자 독립성은 사람이 별도로 검사한다.
4. Project별 동결은 **지정된 인간 평가 책임자**가 원본 해시, 주석 원본/조정 이력, GT revision, 검사 결과를 검토하고 명시적으로 승인한다. 현재 승인자 지정과 승인 기록은 **미완료**다. 검사기를 통과하거나 이 문서를 작성한 행위는 동결이 아니다. 고정 뒤 수정이 필요하면 원본 revision과 평가 결과를 보존하고 revision·사유를 올린다.
5. 세 Project의 GT와 파생 ID 매핑이 고정되기 전에는 focused v0.1의 실제 semantic Provider 평가를 시작하지 않는다. Dataset B 정량 평가는 [EVAL-01](eval-01-scene-candidate-quality.md)의 미실행 상태를 유지하며, 동결 자료·고정 후보 출력·기존 coverage/tIoU 기준이 준비된 뒤 별도 수행한다.

**현재 차단 요인:** P2/P3 원본 12개 등록분, 13개 COVERED 작업 GT, 세 Project Event GT, 현존 P1 초안의 독립 인간 검토와 최종 승인, 고정 Proposal/Candidate catalog와 파생 매핑, P1-S06 등 bounded VLM 표현·privacy 검토가 필요하다. 이번 단계에서 GT·Manifest·스키마·검사기·제품 코드·원본 영상을 수정하거나 신규 분석을 실행하지 않았다.
