# n8n 렌더 완료 자동화 MVP — 설계와 구현 (2026-11-06)

상태: **코드 구현·격리 테스트 완료. 실제 n8n 2.46.6에서 합성 이벤트 검증 완료([1단계 기록](n8n-live-stage1-2026-11-06.md)). 8000 미반영·Cutory 실제 이벤트 미전송.** 서버·DB·Ollama·`.env`·렌더 결과 변경 없음. 아래 1~6은 구현 전 조사·설계, 0은 실제 구현 결과다.

## 0. 구현 결과 (2026-11-06)

### 구현

| 파일 | 내용 |
| --- | --- |
| `backend/app/services/render_events.py` (신규) | 설정(루프백 URL·32자 이상 토큰 검증, 값은 repr·오류에 안 나옴), 이벤트, 전송기(별도 스레드·큐 1000, 재시도, 종료 시 대기 최대 10초), JSONL 전송 기록, DB 읽기 전용 조회 |
| `backend/app/services/persistent_render_execution.py` | 선택 콜백 `on_terminal`(기본 None). 성공·실행 실패·시작 실패·lease 만료 `RECONCILIATION_REQUIRED`를 **커밋 후, 변경 행이 있을 때만** 발행. 실패 경로에 rowcount 확인 추가. 콜백 예외는 경고 로그만 |
| `backend/app/main.py` | 영속화가 켜져 있고 설정이 유효할 때만 전송기 생성. 잘못된 설정은 오류 코드만 경고하고 끔(서버는 정상 기동). 종료 시 렌더 executor 다음에 전송기 정리 |
| `backend/app/render_event_replay.py` (신규) | 재전송 CLI. 기본 목록만, `--send`에서 전송. PostgreSQL은 `SET TRANSACTION READ ONLY` |
| `deploy/n8n/` (신규) | 워크플로우 JSON, Code 노드 로직 원본 JS, 생성 스크립트, Node 검증 스크립트, README |
| `backend/tests/test_render_events.py` (신규) | 27건 |
| `.env.example` | 변수 이름 3개(값 없음) |

설계 대비 확정·변경 사항:
- 이벤트 대상: `COMPLETED`·`FAILED`(시작 실패 `RENDER_START_FAILED` 포함)·`RECONCILIATION_REQUIRED`(실행 실패와 lease 만료 모두). `INTERRUPTED`는 제외.
- 이벤트 ID: `render-<render_id hex>-<status 소문자>`. 본문은 정렬된 JSON으로 실시간·재전송이 바이트 단위로 같다(테스트로 확인).
- 재시도: 연결 오류·타임아웃·408·429·5xx만. 3xx(리다이렉트 미추적)·400·401·403·404·409는 재시도 없음.
- 전송 기록 필드: `ts, event_id, render_id, status, trigger(live/replay), delivery_id, attempt, max_attempts, outcome, http_status, error_type, receiver_result, elapsed_ms`. 결과값: `delivered, retrying, failed, rejected, abandoned_shutdown, dropped_shutdown, dropped_queue_full`.
- n8n 중복 처리: 이벤트 ID만 믿지 않는다. 고정 순서 기록 내용이 같아야 `duplicate`, 다르면 409. 임시 파일 + hard link로 동시 중복에도 기록은 하나. 기록 후 디스크에서 다시 읽어 확인한 다음 응답한다.
- 8000 런처 호환: 런처·`env_probe.py`의 금지 이름 검사는 상속 환경에만 적용되고 앱은 `.env`를 직접 읽으므로 런처 변경 없이 토큰을 `.env`에 둘 수 있다(코드 확인, 실제 기동 미검증).

### 검증

| 항목 | 결과 |
| --- | --- |
| 신규 백엔드 테스트 27건 | OK. 설정 거부(비 루프백·Tailscale 주소·URL 쿼리·짧은 토큰 등), 요청 헤더·본문, 재시도 순서·같은 전송 ID, 4회 후 실패, 4xx/3xx 비재시도, 종료 시 긴 대기 중단, 큐 초과·기록 실패 내성, 로그·기록에 토큰·URL 없음 |
| registry 통합(SQLite·가짜 결과) | 콜백 시점에 DB가 이미 해당 상태, 성공·실패·부분 출력, 콜백 예외에도 `COMPLETED` 유지, 소유권 상실 시 이벤트 없음, `COMPLETED` 커밋 차단(trigger) 시 완료 이벤트 없이 `RECONCILIATION_REQUIRED`만, lease 만료 1회만 발행·`INTERRUPTED` 미발행, 롤백된 전이 미발행, 시작 실패 발행, 재전송 본문 동일·기간·프로젝트 필터 |
| 가짜 수신 서버(127.0.0.1 임의 포트) | 실시간 `recorded` → 재전송 `duplicate`(파일 1개), 수신 서버 꺼짐 → 4회 `ConnectError` 후 `failed`·렌더 `COMPLETED` 유지, 토큰 불일치 403 `rejected`, 수신 측 500 → 4회 후 `failed` |
| 백엔드 전체 | 670건 OK, skip 38(DB 통합 29, QA-01/03 PostgreSQL 4, Windows symlink 3, 하드 자막 Docker·글꼴 2). 신규 테스트 skip 0. 하드 자막 2건은 작업 디렉터리 기준 글꼴 경로라 skip됐고, 실행되면 Docker 컨테이너를 띄우므로 이번 범위에서 실행하지 않음 |
| Node 24 로직 검증 | `check-record-render-event.mjs` 17항목 + 8개 프로세스 동시 중복(하나만 `recorded`, 임시 파일 0) 통과. Cutory가 만든 4종 페이로드와 실제 개발 DB의 완료 렌더 4건 페이로드(읽기 전용 조회, 전송 없음)도 `recorded`→`duplicate` 통과 |
| 재전송 CLI | `--help`, 개발 DB 목록 조회 4건(전송 없음), 설정 없을 때 `--send` 거부(exit 2) |

### 미검증

- ~~실제 n8n에서 워크플로우 import·자격증명 연결·활성화, 응답 코드 표현식, Code 노드 `fs` 허용·task runner, `~/.n8n-files` 경로·hard link~~ → 2026-11-06 1단계에서 확인. 그 과정에서 task runner 샌드박스에 `process` 전역이 없어 JS를 수정했고, n8n 실행 이력에 Webhook 헤더(토큰)가 평문 저장되는 것을 발견했다. [1단계 기록](n8n-live-stage1-2026-11-06.md)
- 8000 반영 후 실제 렌더와 연결된 실시간 전송, 종료 중 대기 이벤트 처리.
- uvicorn 기본 설정에서 `cutory.render_events` INFO 로그는 콘솔에 나오지 않는다(WARNING만 표시). 추적은 JSONL 파일 기준.

## 1. 현재 구조 (코드 확인)

렌더 상태의 기준은 `project_render_runs` 한 행이다(`backend/app/services/persistent_render_execution.py`, 8000은 `CUTORY_RENDER_PERSISTENCE_ENABLED=1`).

| 시점 | 위치 | DB 상태 |
| --- | --- | --- |
| `POST /projects/{id}/render` | `routers/projects.py` `start_project_render` → `registry.start` | 트랜잭션 1: `QUEUED` 행 생성(소유 토큰·lease 45초). 활성 행은 프로젝트당 1개(부분 unique index) |
| 시작 실패 | `start` 안 advisory lock 실패·executor 제출 실패 | `FAILED`/`RENDER_START_FAILED`, API는 500 |
| 작업 시작 | `run()` | `QUEUED→RUNNING`(토큰 일치 시) |
| 진행 중 | heartbeat 스레드 5초 | `lease_expires_at` 갱신 |
| 성공 | `run()` 출력 경로·크기·SHA-256 확인 후 | `RUNNING→COMPLETED`(토큰 일치, rowcount 확인, 0이면 예외) |
| 실패 | `run()` except | `FAILED`(코드) 또는 부분 MP4가 있으면 `RECONCILIATION_REQUIRED`. rowcount 미확인 |
| 소유 프로세스 사라짐 | `_interrupt_expired` — `start`·`snapshot`·`history`(GET) 때 지연 실행 | `INTERRUPTED` 또는 `RECONCILIATION_REQUIRED` |

- executor는 `ThreadPoolExecutor(max_workers=1)`로 처리·장면 분석·렌더가 공유한다. 별도 이벤트·outbox·로깅·외부 HTTP 호출 코드는 없다(`httpx` 0.28.1은 이미 의존성에 있음).
- 이벤트 발행 가능 지점: (A) `COMPLETED` 커밋 직후, (B) 실패 커밋 직후(rowcount 확인 추가 필요), (C) `_interrupt_expired`(GET 부수효과라 MVP 제외, 재전송 도구로 보완).
- 인메모리 registry(영속화 꺼짐)는 MVP 대상이 아니다.
- 테스트 기반: `test_persistent_render_api.py`가 SQLite + `ManualExecutor` + 가짜 렌더 결과로 렌더 없이 상태 전이를 검증한다.

## 2. n8n·Docker·네트워크 (읽기 전용 확인)

- n8n: 실행 파일·이미지·`~/.n8n`·프로세스·5678 포트 모두 없음 → **미설치**. 저장소 문서·코드에 n8n/webhook 언급 없음 → 기존 워크플로우 없음.
- Node: Git Bash PATH에 없음. Docker 엔진 사용 가능.
- 수신 포트: 8000·8001·5173·5432 모두 `127.0.0.1`. 11434는 Ollama(127.0.0.1·::1)와 tailscaled(Tailscale 주소). 5174 Vite(별도) 실행 중. 5678 비어 있음.
- 컨테이너: Cutory postgres(5432), 격리 DB `cutory-web08b-isolated`(55432), 별도 프로젝트 `ai-baby-care` 7개(18000·18501·55433·6380, 자체 ollama). n8n 컨테이너·볼륨 없음.
- 네트워크: `ai-vlog-editor-https-github-com_default`, `ai-baby-care_default` bridge. n8n은 별도 compose 프로젝트·네트워크로 두면 충돌 없음.
- `.env` 변수 이름에 n8n 관련 없음. 8000 런처는 상속 환경에서 `TOKEN|SECRET|KEY` 이름을 차단하지만 앱은 `.env`를 직접 읽는다.
- 미확인: 컨테이너에서 호스트 `127.0.0.1:8000` 접근 가능 여부(설계상 불필요), 고정할 n8n 버전, n8n Code 노드의 `crypto` 사용 허용 여부.

## 3. 추천 설계

원칙: FastAPI/DB가 유일한 기준, n8n은 사후 처리만. 알림 실패는 렌더 상태를 절대 바꾸지 않는다.

1. `render_events.py`(신규): 설정이 없으면 비활성(현재 동작 그대로). `CUTORY_N8N_WEBHOOK_URL`(loopback `http://127.0.0.1:5678/webhook/...`만 허용), `CUTORY_N8N_WEBHOOK_TOKEN`(`.env`, repr·로그 숨김).
2. registry에 선택 콜백 `on_terminal`(기본 None) 추가. 지점 (A)·(B)에서 **커밋 성공·rowcount 1일 때만** 호출. 콜백 예외는 삼킨다.
3. 전송은 렌더 executor와 분리된 단일 스레드에서 `httpx` POST. 타임아웃 3초, 연결 오류·429·5xx만 최대 3회(1·4·15초) 재시도, 4xx는 재시도 없음. 실패 시 `event_id`·오류 종류만 로그.
4. 페이로드(스키마 v1): `event_id`(결정적, 구현은 `render-<hex>-<status>`), `type`(`render.completed`/`render.failed`), `project_id`, `render_id`, `status`, `safe_error_code`, `finished_at`, `duration_seconds`, `file_size_bytes`, `status_url`. 파일 경로·프로젝트 이름·자막·프롬프트 제외.
5. 인증: `Authorization: Bearer <token>` → n8n Webhook 노드 Header Auth 자격증명. HMAC은 후속 옵션. 비밀값은 URL에 넣지 않는다.
6. 누락 복구: DB 읽기 전용 재전송 CLI(`--since`, `--dry-run`) — 기간 안의 종료 행을 같은 `event_id`로 다시 보냄. 전송 기록 테이블 없음(마이그레이션 없음).
7. n8n: Docker `127.0.0.1:5678`만 공개, 별도 compose·볼륨, 진단 끔. 워크플로우: Webhook(Header Auth, 즉시 200) → `event_id`로 중복 제거 → 로컬 파일 기록(`event_id` 파일명, 덮어쓰기라 멱등). 외부 알림 서비스 없음. n8n은 Cutory를 호출하지 않는다.

## 4. 장애·중복

| 상황 | 동작 |
| --- | --- |
| 타임아웃 후 재시도·재전송으로 중복 | 같은 `event_id`, n8n에서 무시 |
| n8n 중지 | 연결 거부 → 재시도 후 로그. 렌더·UI 영향 없음. 재전송 CLI로 복구 |
| 렌더 성공, 알림 실패 | 행은 `COMPLETED` 유지, 다운로드 정상 |
| 워크플로우 비활성(404)·토큰 불일치(401/403) | 재시도 없음, 로그 |
| 8000 종료 중 대기 이벤트 | 유실 가능 → 재전송 CLI. 종료 지연은 최대 약 20초로 제한 |
| `INTERRUPTED` 전이 | MVP는 실시간 이벤트 없음, 재전송 대상 |

## 5. 테스트 계획 (렌더·LLM·VLM 없음)

1. 전송기 단위: `httpx.MockTransport`로 헤더·페이로드·재시도 횟수·4xx 비재시도·비활성·비 loopback URL 거부·로그에 토큰 없음.
2. registry 통합(SQLite·`ManualExecutor`·가짜 결과): 성공 1건=이벤트 1건, 콜백 시점에 DB가 이미 `COMPLETED`, 실패·`RECONCILIATION_REQUIRED` 코드, 콜백 예외에도 상태 유지, 소유권 상실·완료 커밋 실패 시 완료 이벤트 없음.
3. 재전송 CLI: SQLite 고정 데이터로 `event_id` 동일성, `--dry-run` 무전송.
4. 로컬 가짜 수신기(127.0.0.1 임의 포트) 왕복.
5. (승인 후) n8n 컨테이너에 합성 이벤트만 POST하는 스모크. 실제 렌더 연동 E2E는 미검증으로 남김.
보호 테스트 3개는 수정하지 않는다.

## 6. 승인 필요 (실제 설치 전)

- ~~n8n 이미지 버전 선택·pull, 별도 compose 프로젝트·볼륨 생성, `127.0.0.1:5678` 컨테이너 기동, `NODE_FUNCTION_ALLOW_BUILTIN=fs,path` 설정~~ (2026-11-06 1단계 승인·완료, 2.46.6 고정)
- ~~Header Auth 자격증명 생성, 워크플로우 import·활성화~~ (테스트 토큰으로 완료. 실제 토큰으로 교체 필요)
- n8n 실행 이력 보존 정책(실행 이력에 토큰 평문 저장 — [1단계 기록](n8n-live-stage1-2026-11-06.md))
- n8n 소유자 계정 생성(사용자 직접, 선택)
- 실제 `.env`에 URL·토큰 추가(토큰 생성은 사용자 또는 로컬 생성 후 값 미출력)
- 기능 활성화를 위한 8000 재시작 1회(고친 `stop_server.py` 첫 실사용 포함)
- 실제 렌더 1회로 하는 E2E 여부. 대안: 합성 이벤트 POST와 재전송 CLI `--send`로 기존 완료 렌더 4건 전송(렌더 없음)
- 코드 커밋
