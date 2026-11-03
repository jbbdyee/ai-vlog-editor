# WEB-08A — 렌더 기록 영속화 및 재시작 복구 설계

상태: **설계·코드 조사 완료, 제품 구현·DB 변경·서버 재시작 E2E 미실행**. 조사 시 `main`, HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. WEB-01~07/EVAL-01/02의 미커밋 파일과 보호 대상 백엔드 테스트 3개를 보존했다. 기존 FastAPI `127.0.0.1:8000`·Vite `127.0.0.1:5173`은 HTTP 200, PostgreSQL 17.11 Compose 컨테이너는 healthy였다. 이번 조사에서 서비스 종료·재시작, DB 쓰기, 마이그레이션, 렌더 실행, 파일 변경, 유료 API 호출, 커밋·Push는 하지 않았다. [WEB-03](web-03-edit-render-validation.md), [WEB-04](web-04-react-e2e-validation.md), [WEB-07](web-07-render-preview-validation.md)의 실제 검증과 이 설계의 제안을 구분한다.

## 현재 구조와 재시작 시 손실

| 항목 | 코드 근거와 현재 동작 |
| --- | --- |
| 접수 | `backend/app/routers/projects.py:start_project_render`가 프로젝트 존재·편집 계획 유효성을 검사하고 `ProjectRenderRunRegistry.start`에 작업을 제출한다. 응답은 `202`, `accepted`, `status_url`이며 작업 ID는 없다. 같은 프로세스의 활성 프로젝트만 `409 RENDER_ALREADY_ACTIVE`로 막는다. |
| 계획 | `backend/app/models/edit_plan.py:ProjectSceneEditPlan/Item`은 프로젝트당 한 계획과 순서가 있는 후보 ID를 저장한다. `backend/app/services/project_scene_edit_plan.py:save_scene_edit_plan`은 Project 행 잠금 후 항목을 교체한다. 과거 계획 버전·렌더와의 FK는 없다. |
| 실행·ID | `backend/app/main.py:lifespan`이 단일 worker `ThreadPoolExecutor`와 프로세스별 registry를 만든다. `backend/app/services/project_render_execution.py:ProjectRenderRunRegistry`의 `_active`, `_snapshots`, `_completed`는 메모리 dict/set이다. `render_project_edit_plan`은 DB의 현재 계획을 다시 읽은 **뒤** `uuid4()`로 render ID를 만들므로 `QUEUED` 또는 초기 `RUNNING` 시에는 식별자가 없다. 현재 상태는 `NOT_STARTED/QUEUED/RUNNING/COMPLETED/FAILED`; 취소 상태·취소 API는 없다. 일반 예외는 안전 코드 `PROJECT_RENDER_FAILED`로 축약한다. `submit` 실패 시 이전 메모리 snapshot을 복원한다. |
| 계획 변경 방어 | `backend/app/services/project_rendering.py:_assert_plan_current`이 긴 작업 중 선택·순서 변경을 검사한다. 이는 실행 시점 계획의 영속적인 사본을 만들지는 않는다. |
| 파일 | 같은 서비스가 `outputs/projects/projects/<project_id.hex>/renders/<render_id.hex>/`에 `final.mp4`, 가능한 경우 `final.srt`, `final-subtitled.mp4`를 만든다. 실패한 기본 렌더의 `final.mp4`·SRT는 정리하고 기존의 다른 ID 디렉터리는 건드리지 않는다. SRT·하드 자막 실패는 기본 MP4 성공을 훼손하지 않는다. `backend/app/services/hard_subtitles.py:burn_hard_subtitles`는 임시 파일 검증 후 별도 MP4로 원자적 이동한다. |
| 조회 | `GET /projects/{id}/rendering`은 registry의 **마지막 시도**만 반환한다. 완료 결과가 있으면 파일 경로·크기 검사 후 URL을 내준다. 새로운 시도가 실패하거나 재시작하면 이전 성공 파일이 남아도 이 응답에 나오지 않는다. |
| 다운로드 | `GET /projects/{id}/renders/{render_id}/download`와 `/subtitled/download`는 프로젝트 존재, 32자리 소문자 hex ID, `_completed[(project_id, render_id)]`, 저장 루트 안의 정해진 파일·크기를 검사한다. 잘못된 ID 422, 없는 기록 404, 진행/실패 409, 없는 기본/자막 파일 404. `FileResponse`의 MP4·Range 응답은 WEB-07에서 확인했다. 프로젝트 연결 검증은 인증·사용자 소유권 검증이 아니다. |
| React | `web/src/api/edit-render.ts:getRendering/downloadPath`는 완료 상태와 프로젝트·렌더 ID에 정확히 맞는 URL만 허용한다. `web/src/features/edit/edit-render.tsx`는 프로젝트별 Query key로 현재 상태를 조회하고 활성 작업에만 폴링하며, `render-preview.tsx`는 완료 결과만 재생한다. 재시작 뒤 `NOT_STARTED`는 파일 복구로 해석하지 않는다. |

DB에는 현재 `projects`, `project_scene_edit_plans` 및 관련 후보 모델은 있으나 렌더 실행/결과 테이블은 없다(`backend/app/models/`, `backend/alembic/versions/`). Alembic은 `backend/alembic/env.py`에서 현재 모델 메타데이터와 `POSTGRES_*` 설정을 사용한다. `SPEC.md`, `IMP-PLAN.md`는 저장소에 없다. 이 문서는 기존 Source of Truth인 `docs/roadmap/v2-plan.md`의 범위를 변경하지 않는다.

## WEB-08B 권장 데이터 모델

기존 계획을 바꾸지 않고 **새 `project_render_runs` 테이블과 새 Alembic revision**을 추가한다. 과거 파일만 보고 행을 만들지 않는다.

| 필드·제약 | 목적 |
| --- | --- |
| `render_id` UUID PK, `project_id` UUID FK(`projects.id`), `(project_id, created_at, render_id)` 인덱스 | 요청 접수 전에 ID를 확정하고 프로젝트와 연결. project ID 없는 단독 ID 조회 금지 |
| `status` 제한 값 `QUEUED/RUNNING/COMPLETED/FAILED/INTERRUPTED/RECONCILIATION_REQUIRED` | DB가 상태의 기준. `NOT_STARTED`는 프로젝트에 기록이 없을 때의 API 표시값으로만 사용 |
| `created_at/started_at/finished_at` timezone aware | 시도 순서와 처리 시간. 동률은 ID로 결정 |
| `plan_snapshot` JSONB 또는 순서 있는 후보 ID·source ID·구간의 별도 읽기 전용 스냅샷, `plan_fingerprint` | 접수 시점 선택·순서·구간을 후속 계획 수정과 분리. 현재 계획 row FK만으로는 당시 선택을 복원할 수 없다. 스냅샷은 최소 필요 정보만 저장하고 전사 원문·원본 경로는 넣지 않는다 |
| `base_relpath`, `base_size_bytes`, `duration_seconds`, `video_codec`, `audio_codec`; `srt_relpath`, `hard_relpath`, `hard_size_bytes` nullable | 완료 파일 메타데이터. 절대경로가 아닌 저장 루트 상대 참조. 정해진 ID 디렉터리·파일명과 일치해야 함. SRT/하드 자막은 독립 상태·오류 코드와 연결 |
| `safe_error_code`, `subtitle_error_code`, `hard_subtitle_error_code` nullable | 사용자에게 노출 가능한 제한된 코드만 기록. 스택·비밀키·원본 경로 저장 금지 |
| `owner_token` 임의 UUID, `lease_expires_at`, `heartbeat_at`, `attempt_number`(초기 1), `interrupted_reason` nullable | 다중 프로세스 작업 소유권과 만료 후 수동 재시도 구분. 서버 PID만으로 소유권 판단하지 않음. 자동 재렌더는 없음 |
| 프로젝트당 `QUEUED/RUNNING` 한 건만 허용하는 PostgreSQL 부분 유니크 인덱스 | 프로세스별 메모리 락을 넘어 동시 렌더 차단. 만료된 행은 안전하게 `INTERRUPTED`로 상태 전이한 후에만 새 접수 |

DB 경로만 믿지 않는다. API는 `output_root.resolve()`에서 `projects/<project_hex>/renders/<render_hex>/final.mp4` 등 **고정 파일명**을 재구성하고, `resolve()` 후 루트 이탈·중간 symlink·파일 누락·크기 불일치를 차단한다. 현재 기본 경로 검사와 자막 경로 검사의 강도를 맞추어 재검토한다. DB 완료는 파일이 실제로 다운로드 가능한 것과 별개다. SHA-256은 보안·무결성 요구가 확정되면 완료 시 기록할 수 있으나 매 Range 요청마다 전체 파일을 해싱하지 않는다. 크기/경로 검사는 요청 시 수행하고 FFprobe·선택적 해시는 완료 확정 시 및 격리 복구 검증 시 수행한다. 전송 직전 파일 교체 경쟁은 가능하므로 파일 교체를 허용하지 않는 로컬 운영 경계와 테스트가 필요하다.

## 상태 전이·실패 복구 정책

1. **접수:** 한 DB 트랜잭션에서 프로젝트 행 잠금, 계획 유효성·스냅샷 확인, 기존 활성 행/만료 lease 판정, 새 UUID와 `QUEUED` 행 생성·commit. 그 뒤 executor 제출. commit 전에는 `202`를 반환하지 않는다. 제출 실패 시 새 행을 `FAILED`와 `RENDER_START_FAILED`로 기록한다. 그 갱신도 실패하면 접수 상태를 불명확하게 성공으로 표시하지 않고 오류·감사 로그를 남기며 다음 조회에서 조정 필요 상태로 다룬다. 단순 HTTP 재요청은 새 렌더를 만들 수 있으므로 완료 여부를 먼저 조회하도록 안내한다. 네트워크 응답 유실에 대한 정확한 멱등성은 별도 client request key가 없으면 보장할 수 없다.
2. **실행:** worker는 자신의 `owner_token`과 현재 상태 조건으로 `QUEUED→RUNNING`을 원자적으로 claim한다. 렌더 ID·계획 스냅샷을 엔진에 전달하고 현재 계획과 일치하는지 재검사한다. 기존 렌더 알고리즘은 유지하되 ID 생성 위치와 입력 검증만 연결한다. 긴 FFmpeg 실행 중에도 독립 heartbeat가 lease를 갱신해야 한다. 상태 갱신은 소유 token/버전 조건으로 fencing하여 오래된 worker가 결과를 완료 처리하지 못하게 한다. lease 만료만으로 살아 있는 FFmpeg와 동시에 재렌더하지 않는다.
3. **완료:** FFmpeg/FFprobe 검사, 기본 MP4와 선택적 SRT/하드 자막의 실제 존재·스트림·길이·크기를 확인한 뒤에만 DB를 `COMPLETED`로 commit한다. 자막 실패는 기본 완료 및 각각의 오류 코드로 남긴다. 파일 성공 후 DB 완료 commit 실패는 **파일을 삭제하거나 재시도하지 않고** `RECONCILIATION_REQUIRED` 대상으로 분리한다. DB와 파일에 원자적 공동 commit이 없다는 점을 명시한다.
4. **재시작:** `COMPLETED`와 기본 파일이 모두 유효하면 조회·다운로드 허용. DB 완료이나 기본 파일 누락/변조면 기록은 보존하고 `download_available=false`, 파일 누락 오류로 표시하며 다운로드는 404; 자막만 누락이면 기본 영상은 유지하고 하드 자막은 `MISSING`/404. `QUEUED/RUNNING`은 정상 소유 lease가 있으면 그대로 진행 중일 수 있으므로 다른 프로세스가 시작했다는 이유만으로 중단시키지 않는다. 소유권 상실과 만료가 확인되면 `INTERRUPTED`로 표시하고 **자동 재시도하지 않는다**. 부분 파일은 격리·수동 조사 대상으로 보존하며 새 렌더의 성공 근거가 아니다.
5. **반복·동시성:** 동일 프로젝트 연속 렌더는 새 ID와 새 계획 스냅샷을 갖고 이전 완료 행·파일을 보존한다. 동시 요청은 DB 부분 유니크 인덱스/잠금으로 하나만 접수한다. 프로세스 여러 개가 있더라도 각 worker는 소유 token/lease로 제어한다. lease 회복·경합·오래된 프로세스의 늦은 완료를 실제 PostgreSQL 통합 테스트로 증명하기 전에는 다중 worker 운영을 지원한다고 표시하지 않는다. 사용자 취소 API는 이번 범위에 추가하지 않으며 `INTERRUPTED`는 서버 중단 상태다.

## API·React 호환성

- `POST /projects/{id}/render`의 `202`와 `accepted/status_url`, `GET /projects/{id}/rendering`의 기존 필드, 두 다운로드 경로·Content-Type·Range·파일명은 유지한다. 접수 응답에 `render_id`를 **추가**하면 새 React가 확정 ID를 추적할 수 있다. 기존 클라이언트가 추가 필드를 허용하는지 회귀 검사한다.
- `GET /rendering`은 DB의 최신 시도를 우선 표시한다. 새 시도가 실패/중단되면 이전 성공을 최신 성공으로 가장하지 않는다. 완료/실패/중단 상태가 표현되도록 기존 `status` enum에 `INTERRUPTED`와 필요 시 `RECONCILIATION_REQUIRED`를 추가하므로 React 타입·문구·폴링 종료 조건을 동시 갱신한다. 기존 성공 응답의 URL 형식은 그대로 유지한다.
- 이전 성공을 최신 실패와 구분해 다시 열기 위해 `GET /projects/{id}/renders?limit=&cursor=`의 프로젝트 범위 페이지 조회를 **최소 추가 계약**으로 둔다. 항목별 ID·상태·계획 시점·파일 가용성을 제공하고, 사용자가 선택한 완료 ID는 기존 다운로드 URL을 사용한다. WEB-08B는 이 목록 API와 최소 React 선택 UI를 포함하되, 첫 번째 검증 게이트는 `GET /rendering`으로 최신 완료 렌더의 재시작 복구를 먼저 확인한다. 전체 기록은 새 DB 행으로만 보존한다.
- 렌더 기록이 없으면 현재와 같은 `NOT_STARTED`; 기존 파일만 있는 경우에도 `NOT_STARTED`. React는 프로젝트 재진입 시 서버에서 조회하고, 완료 URL 검증 뒤에만 재생한다. 파일 누락·자막 누락·중단 상태는 별도 안내를 표시한다. 다운로드는 DB의 **해당 프로젝트·렌더 ID의 완료 행**과 파일 검증을 모두 통과해야 한다. 이는 사용자 인증을 대체하지 않는다.

## 이전 데이터·마이그레이션·롤백

- WEB-08B 전에 PostgreSQL의 일관된 백업과 복구 시험, 기존 QA 렌더의 상대 경로·크기·해시 목록을 **Git 밖**에 보관한다. 마이그레이션은 기존 테이블을 수정/삭제하지 않는 추가 revision으로 만들고, 별도 격리 DB에서 upgrade·downgrade·기존 데이터 보존을 먼저 검증한다. 실행 중인 프로세스와 DB schema의 버전 불일치를 피하는 정지/교체 절차를 수립한다.
- 새 테이블은 과거 렌더 파일을 자동 import하지 않는다. 폴더명에 project/render UUID가 있어도 파일만으로 실행 완료·계획 스냅샷·자막 실패 상태를 확정할 수 없다. 수동 이관이 필요하면 DB의 프로젝트 소속, 당시 기록·파일 검증·사람 승인에 근거한 **별도 읽기 전용 감사→명시적 이관** 절차를 설계한다. WEB-07 시험용 메모리 주입을 제품 복구로 옮기지 않는다.
- 롤백은 먼저 새 코드의 기록 생성을 중단하고 DB·파일 스냅샷을 보존한 뒤, 호환되는 이전 코드로 돌아가는 순서다. 신규 렌더 행을 가진 상태에서 테이블을 곧바로 drop하지 않는다. Alembic downgrade는 격리 DB에서만 연습하고 실제 환경의 drop은 데이터 보존·승인 후 수행한다. 백업 복원은 기존 사용자 DB/원본/QA 결과를 덮어쓰지 않는 새 격리 환경에서 먼저 검증한다.
- 출력 루트는 로컬 저장소에 한정하고 인증·소유권은 여전히 없다. DB의 프로젝트-렌더 관계는 파일 경계 검증이지 외부 사용자 권한 검증이 아니다. 공개 배포는 별도 인증·권한 설계 전까지 금지한다.

## WEB-08B 순서와 검증 게이트

| 순서 | 예상 변경·마이그레이션/API | 검증·회귀 위험·롤백/완료 기준 |
| --- | --- | --- |
| 1. 백업·격리 준비 | 제품 코드 없음; 백업 명령·QA 프로젝트/출력 인벤토리 | 기존 DB·QA 파일 해시 보존, 별도 복원 시험. 실패 시 구현 착수 중지 |
| 2. DB 모델 | `backend/app/models/` 새 렌더 모델, `__init__.py`, `backend/alembic/versions/` 새 revision; 기존 테이블 비파괴 | migration upgrade/downgrade·제약·인덱스·기존 행 보존을 격리 PostgreSQL에서 확인. 실패 시 격리 DB만 재설정 |
| 3. 실행/저장 연결 | `project_render_execution.py`, `project_rendering.py`, 필요 시 새 repository, `main.py`; 접수 전 ID·계획 스냅샷·상태 전이·lease/fencing | 단위: 상태 전이·제출/완료 DB 실패·계획 변경·자막 실패·결정성. 실제 DB: 동시 POST/다중 세션·lease 만료·늦은 worker. 위험: 중복/기존 결과 훼손; 새 ID 디렉터리 격리, 문제 시 신규 접수 중단 |
| 4. 읽기/API | `routers/projects.py` 기존 조회·다운로드를 DB 기준으로 변경, 프로젝트별 페이지형 기록 목록 추가 | API: 202/409/404/422/206·프로젝트 혼동·경로 순회/symlink·파일 누락·자막만 누락·오래된 성공 보존. 이전 URL·MIME·파일명 유지. 실패 시 이전 코드 복귀, 새 행·파일 보존 |
| 5. React·실제 재시작 | `web/src/api/edit-render.ts`, `web/src/features/edit/`, 테스트; README/TODO/v2/handoff | 단위와 Mock: 새 ID·중단/누락·프로젝트 분리·폴링 종료. 격리 QA의 실제 Chrome→FastAPI→PostgreSQL→FFmpeg 새 렌더 후 서버 재시작, 기본/자막 MP4 재생·Range/다운로드 해시 확인. 과거 QA 렌더 자동 복구를 주장하지 않음 |

**완료 판정:** 새로 접수된 렌더의 DB 기록·계획 스냅샷·파일이 일치하고, 실제 API 프로세스를 재시작한 뒤 동일 프로젝트/ID의 완료 파일을 조회·재생·다운로드할 수 있어야 한다. 중단/누락/자막 실패/동시 요청/다중 프로세스 경계는 각기 실패·제한으로 정확히 표시해야 한다. 단위·Mock·실제 DB 통합·실제 서버 재시작 E2E의 통과/실패/건너뜀을 별도로 보고한다. 품질 정량 평가나 공개 배포의 완료를 뜻하지 않는다.
