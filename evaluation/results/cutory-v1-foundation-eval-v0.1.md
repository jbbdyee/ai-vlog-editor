# Cutory v1 Project Foundation Evaluation v0.1

## 목적

Cutory v1의 Project & Large Video Foundation이 다수 Source, 부분 실패, 재시작,
재사용, retry/reprocess, temporary cleanup과 Project API 상태 조회를 일관되게
지원하는지 검증한다. 새로운 Product 기능이나 실제 미디어 품질을 평가하는 작업은
아니다.

## 평가 환경

- Run ID: `cutory-v1-foundation-eval-v0.1-run1`
- 평가 일자: 2026-09-29 (Asia/Seoul)
- 평가 대상 commit: `d5907ab9fc32b3c5913d0f938c34eeecddf0430a`
- OS: Windows 학원 개발 PC
- Python: 3.12.14
- Docker Client / Server: 29.7.2 / 29.7.2
- PostgreSQL: `postgres:17.11`, Docker Compose, healthy
- Alembic head: `db81de89b2b5`
- Evaluation runner: `evaluation/run_v1_foundation_evaluation.py`
- 총 시나리오 실행 시간: 19.313초

## 평가하지 않은 범위

- 실제 대형 영상 120개의 Probe/STT 처리량과 처리 시간
- faster-whisper의 병렬 성능, GPU/CPU/memory benchmark
- Queue/Worker, distributed lock, 다중 server 장애 복구
- Mobile UI, SSE/WebSocket, Scene Intelligence, Agent/MCP/RAG
- `evaluation/data/eval_01.MOV` 재실행: 현재 PC에 파일이 없어 다운로드하지 않음

이번 120 Source 평가는 **Synthetic Scale Evaluation**이다. 실제 영상 120개를 AI로
분석했다고 해석하면 안 된다. 실제 MOV → Probe → Audio → faster-whisper → Memo →
MP4 및 Browser E2E는 과거 macOS 검증 기록인
`docs/integration-eval01-v0.1.md`, `docs/browser-e2e-v0.1.md`의 historical evidence로만
인용한다.

## Scenario 목록

| Scenario | Test 수 | 결과 | 시간(초) |
| --- | ---: | --- | ---: |
| 120 Source + second-run reuse | 1 | PASS | 5.962 |
| Partial failure + 재실행 정책 | 2 | PASS | 1.747 |
| Crash/restart + RUNNING blocked | 2 | PASS | 1.465 |
| Retry + Reprocess | 4 | PASS | 0.988 |
| 0 Memo + Result validity | 5 | PASS | 0.975 |
| Temporary cleanup | 4 | PASS | 0.923 |
| Fingerprint integrity | 1 | PASS | 0.806 |
| API/DB + Background boundary | 3 | PASS | 2.537 |
| Bounded concurrency + Session isolation | 2 | PASS | 1.938 |
| Empty Project | 2 | PASS | 1.971 |

## Scale 결과

- Synthetic Source: 120
- ProcessingStage: 480
- 첫 실행 processed/completed: 120 / 120
- failed/blocked/remaining: 0 / 0 / 0
- progress ratio: 1.0
- processor 예상 외 중복 호출: 0
- 실제 PostgreSQL Source/Stage 상태와 Project 집계 일치: PASS

### 두 번째 실행

- reused: 120
- processor actual call count: 0
- duplicate processing count: 0
- 유효한 완료 결과를 다시 실행하지 않는 기준: PASS

## Partial Failure 결과

10개 Source 중 5번째 Source를 결정적으로 실패시켰다.

- completed: 9
- failed: 1
- 실패 뒤 Source 처리 지속: PASS
- Project status: `COMPLETED_WITH_WARNINGS`
- 두 번째 선택에서 완료 Source 재사용, FAILED 보존, 자동 retry 없음: PASS

## Crash / Resume 결과

재시작 전 DB 상태를 `COMPLETED 2`, `STT RUNNING 1`, `READY 2`로 구성했다.

- 완료 Source 재실행: 0
- reused Source: 2
- RUNNING Source: 1 BLOCKED
- READY 처리: 2
- 새 Session/Application context에서도 DB 상태 선택이 동일함: PASS

## Explicit stale recovery 결과

- `STT RUNNING`은 일반 resume에서 실행되지 않음
- 명시적 cutoff recovery 후 `FAILED`로 영속화
- safe error code: `STALE_EXECUTION_RECOVERED`
- 명시적 retry 후 STT와 downstream Memo 완료
- 자동 stale 추측이나 중복 실행 없음: PASS

## Retry 결과

- 대상: `STT FAILED`
- attempt count: 1 → 2
- Probe 중복 실행: 0
- temporary Audio dependency recreation 후 STT/Memo 완료
- 명시적 max attempts 도달 시 추가 retry 거부
- 무한 retry 없음: PASS

## Reprocess 결과

### STT부터 Reprocess

- invalidated: STT, MEMO_DETECTION (2 Stage)
- upstream reused: PROBE (1 Stage)
- AUDIO: temporary dependency recreation
- downstream reexecuted: STT, MEMO_DETECTION (2 Stage)
- 기존 Transcript/EditMemo current result 교체: PASS

### PROBE부터 Reprocess

- 네 Stage 전체 invalidation/reexecution
- attempt count 증가와 새 current result 저장: PASS

## 0 Memo 결과

- STT 성공, 탐지 EditMemo 0개
- MEMO_DETECTION status: `COMPLETED`
- EditMemo row: 0
- result validity: valid
- resume 시 Memo Detection 호출: 0

## Result Validity / Fingerprint 결과

| 조건 | 결과 |
| --- | --- |
| COMPLETED + valid result | 재사용 |
| STT COMPLETED + Transcript 없음 | invalid, STT downstream 재평가 |
| MEMO COMPLETED + memo 0개 | valid |
| input fingerprint mismatch | 재사용 거부 |
| config/tool version mismatch | 재사용 거부 |
| 명시적 integrity check에서 실제 파일 hash mismatch | 실행 차단 |

일반 resume에서는 대형 원본 SHA-256을 매번 다시 계산하지 않는다. 전체 hash 검증은
호출자가 명시한 integrity verification에서만 수행하는 현재 정책과 일치했다.

## Cleanup 결과

- 정상 성공 뒤 WAV/source temporary workspace 잔존: 0
- STT 실패 뒤 temporary 잔존: 0
- Memo 실패 뒤 temporary 잔존: 0
- Original source 보존: PASS
- cleanup 자체 실패는 안전한 warning으로 분리되고 원본 결과를 숨기지 않음: PASS

## API / DB Consistency

completed, failed, blocked, remaining 혼합 상태에서 직접 DB 상태와
`GET /projects/{id}/processing` 응답을 비교했다.

- total/completed/failed/blocked/remaining 일치: PASS
- progress ratio 일치: PASS
- Project status 일치: PASS
- registry가 비어 있는 restart context에서 DB 상태 조회: PASS
- 로컬 path, storage reference, Transcript 본문 비노출: PASS

## Background Execution

- `POST /projects/{id}/process`: HTTP 202
- controlled executor 실행 전 HTTP response 반환: PASS
- 동일 Project active 중 두 번째 시작: HTTP 409
- background processor 추가 호출: 0
- 완료 뒤 재호출 가능: PASS

이 executor/registry는 in-process 경계이며 durable job queue나 distributed lock이 아니다.

## Concurrency / Session Isolation

| configured max | observed max | 결과 |
| ---: | ---: | --- |
| 1 | 1 | PASS |
| 2 | 2 | PASS |

- configured limit 초과: 없음
- 서로 다른 Source worker의 동일 SQLAlchemy Session 객체 공유: 없음
- 운영/API 기본 concurrency: 1 유지
- 실제 faster-whisper 병렬 성능 주장은 하지 않음

## Empty Project

- total: 0
- progress ratio: 0.0
- divide-by-zero: 없음
- Project status: `CREATED`

## Known Environment Limitation

`test_symlink_escape_is_not_served`는 Windows의 symlink 생성 권한 부족으로
`WinError 1314`가 발생해 테스트 본문 진입 전에 **environment-blocked** 상태다.
테스트를 통과했다고 계산하지 않았고 삭제, 완화 또는 skip 처리하지 않았다.

## v1 Completion Gate

| Gate | 판정 | 근거 유형 |
| --- | --- | --- |
| Target backend migration / Baseline regression | PASS | 현재 구조 + 전체 regression |
| PostgreSQL persistence / Product model | PASS | 실제 PostgreSQL integration |
| Project create/read / Source registration | PASS | Project API + ingestion tests |
| ProcessingStage / Transcript / EditMemo persistence | PASS | Source processing integration |
| Real Probe/Audio/STT/Memo | PASS | historical real-media evidence, 이번 run에서 미재실행 |
| Valid result reuse / duplicate 방지 | PASS | 120 Source second run |
| Retry / stale recovery / reprocess / invalidation | PASS | 이번 evaluation run |
| Source partial failure / state consistency | PASS | 10 Source + mixed-state API |
| Original/Temporary lifecycle / cleanup | PASS | filesystem fixture evaluation |
| 100+ synthetic scale | PASS | 실제 PostgreSQL 120 Source/480 Stage |
| Small real-media integration | PASS | historical evidence, 이번 run에서 미재실행 |
| Crash/resume / bounded processing | PASS | restart simulation + concurrency test |
| Project FastAPI flow | PASS | 실제 PostgreSQL API integration |
| `/videos/process` regression decision | PASS | Baseline 경로로 공존한다고 문서화 |
| Evaluation / Failure Analysis | PASS | 본 문서 |
| Privacy/local-first review | PASS | local storage 및 allowlist API 검증 |
| v2 handoff contract | PASS | v1 plan, architecture/data-flow 문서 경계 유지 |

## Success Criteria

요청된 16개 평가 기준을 모두 만족했다. 실제 heavy-media 100개 성능은 이 PASS의
의미에 포함되지 않는다.

## Final Result

**PASS — Cutory v1 Project & Large Video Foundation completion gate 충족.**

이 판정은 Project/Data/Processing foundation에 한정된다. Queue/Worker, 분산 실행,
Scene Intelligence, Creative Editing 및 Final Mobile UX가 완료됐다는 뜻은 아니다.

## Failure Analysis

이번 평가에서 Product behavior 실패는 발견되지 않았다.

### 잔여 위험 1 — In-process execution durability

- Symptom: process 종료 시 executor에 등록된 실행 자체는 사라질 수 있음
- Expected: v1은 DB 상태를 보존하고 사용자 재요청으로 resume 가능
- Actual: 기대와 일치
- Likely Cause: durable queue/worker가 v1 비범위
- Impact: 자동 재개가 아니므로 사용자가 다시 시작해야 함
- Suggested Next Action: 실제 운영 규모와 장애 관찰 후 queue/worker 필요성을 평가

### 잔여 위험 2 — Heavy-media scale 미측정

- Symptom: 120개 실제 영상의 시간·CPU/GPU·memory 사용량 데이터 없음
- Expected: 이번 Step은 synthetic/state reliability 평가
- Actual: 기대와 일치
- Likely Cause: 개인정보·디스크·실행 비용을 고려해 synthetic fixture 사용
- Impact: 운영 capacity와 적정 concurrency는 아직 확정할 수 없음
- Suggested Next Action: 승인된 비식별 media corpus가 준비되면 별도 performance evaluation

### 잔여 위험 3 — Windows symlink test environment-blocked

- Symptom: symlink 생성 전에 `WinError 1314`
- Expected: 권한 있는 환경/CI에서 path escape 방어 실행
- Actual: 현재 PC에서 environment-blocked
- Likely Cause: Windows symlink 생성 권한
- Impact: 이번 PC에서는 해당 보안 assertion을 실행하지 못함
- Suggested Next Action: symlink 권한이 있는 CI에서 원본 테스트를 그대로 실행
