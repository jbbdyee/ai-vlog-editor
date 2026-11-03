# WEB-08C — 기존 로컬 환경 적용 전 안전 게이트

상태: **승인 후 기존 로컬 DB 적용·FastAPI 교체 완료, 새 완료 렌더의 실제 재시작 복구 미검증**. 이 문서는 [WEB-08A 설계](web-08a-render-persistence-design.md)와 [WEB-08B 격리 검증](web-08b-render-persistence-validation.md)에 이어진다. 격리 검증과 이번 기존 개발 환경 적용을 구분한다.

## 적용 전 확인 (2026-10-28)

- Git `main`, HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB/EVAL/SEC 미커밋 변경과 보호 대상 백엔드 테스트 3개를 보존했다. 이 단계에서 제품 코드·DB 설정·Tailscale 설정은 수정하지 않았다.
- 기존 PostgreSQL 컨테이너는 healthy, IPv4 게시 주소는 `127.0.0.1:5432`, DB revision은 `ca3e4f5a6b7c`. FastAPI `127.0.0.1:8000`과 Vite `127.0.0.1:5173`은 HTTP 200. 현재 실행 중인 FastAPI의 OpenAPI에는 새 프로젝트별 렌더 기록 경로가 없어 기존 메모리 방식이다.
- 기존 12개 프로젝트의 소스 처리·장면 분석·렌더 상태 API에서 활성 작업 0개. PostgreSQL의 다른 active 쿼리도 0개였다. 이는 점검 시점의 결과이므로 적용 직전에 재확인한다.
- Tailscale Serve HTTPS 443은 Vite `127.0.0.1:5173`으로 연결되고, 기존 TCP 11434·2222 설정도 유지된다. 다른 tailnet 기기의 실제 접속은 이번 단계에서 재검증하지 않았다.
- `backend/alembic/versions/b8c01e2a4f60_add_project_render_runs.py`의 `down_revision`은 `ca3e4f5a6b7c`. 기존 테이블을 변경하지 않고 `project_render_runs`와 관련 제약·인덱스를 추가한다.

## 새 백업·격리 복원

기존 DB의 새 `pg_dump -Fc` 백업을 Git 제외 `temporary/web08c-backup-20261028/db.dump`에 만들었다. 크기 **81,692바이트**, SHA-256 `ed960134be40fbf227b63eab8fe9e293038279af6f2c7322492c30617bf87a20`. `pg_restore -l`을 통과했고, 별도 PostgreSQL 컨테이너의 새 DB `cutory_web08c_restore_20261028`(localhost 55432)에 `--exit-on-error`로 복원했다. 기존 DB와 복원 DB의 공개 스키마 **16개 테이블 행 수가 모두 일치**했다. 주요 수: 프로젝트 12, 소스 9, 후보 44, Evidence 120, 편집 계획 4. 복원 DB revision도 `ca3e4f5a6b7c`였다.

새 복원 DB에만 Alembic upgrade를 실행해 `b8c01e2a4f60`과 빈 `project_render_runs` 테이블을 확인했다. 직후 기존 DB revision `ca3e4f5a6b7c`를 다시 확인하고 사용자 적용 승인을 기다렸다. WEB-08B의 격리 실제 서버 재시작 E2E는 이번에 재실행하지 않았다.

`storage/originals/` 원본 9개(1,746,076,115바이트), `outputs/projects/` 기존 렌더 파일 17개(2,025,979바이트)의 상대 경로·크기·SHA-256 목록을 Git 제외 `temporary/web08c-backup-20261028/file-inventory.json`에 기록했다. 이 인벤토리 SHA-256은 `1e3037d188a8b0fa97bc8f87fd9621fe714379f31a20fefea5fe19c06b2d1e4f`. 제한된 프로세스에서 일부 자막 MP4 읽기가 거부되어 권한을 바꾸지 않고 접근 가능한 로컬 컨텍스트에서 26개 전체를 해시했다. 이 목록은 **적용 전 기준선**이며 적용 후 비교가 필요하다. 백업과 인벤토리에는 개인 데이터가 포함될 수 있으므로 Git에 추가하지 않는다.

## 승인 후 실제 적용·검증 (2026-10-28)

적용 직전 12개 프로젝트의 처리·분석·렌더 상태 조회에서 활성 작업 0개·조회 오류 0개, PostgreSQL의 다른 active 쿼리 0개를 다시 확인했다. DB는 healthy·`127.0.0.1:5432`, revision `ca3e4f5a6b7c`, 백업 크기와 SHA-256 및 격리 복원 revision은 기준선과 일치했다. 보호 대상 테스트 3개 변경량도 유지됐다.

승인 범위에서 기존 DB에 `alembic upgrade b8c01e2a4f60`을 적용했다. revision은 `b8c01e2a4f60`, 새 `project_render_runs`는 0행이다. 기존 사용자 데이터 테이블 15개의 행 수는 적용 전과 모두 같았다. 기존 QA 렌더 파일을 자동 등록하지 않았다.

FastAPI만 `CUTORY_RENDER_PERSISTENCE_ENABLED=1`로 교체했다. 첫 종료 명령이 실패해 기존 프로세스가 포트를 계속 점유했고, 첫 새 프로세스는 바인딩 오류로 종료됐다. 기존 API가 계속 응답하는 것을 확인한 뒤 **식별한 기존 FastAPI 프로세스 트리만** 종료하고 다시 시작했다. 최종 FastAPI는 `127.0.0.1:8000`에서 기동했고 OpenAPI에 `GET /projects/{project_id}/renders`가 나타났다. 이 과정에서 DB·Vite·Tailscale Serve는 재시작하지 않았다.

기존 프로젝트 조회, 후보 조회, 편집 계획 조회, 렌더 상태 조회는 모두 HTTP 200이었다. 프로젝트 응답의 `source_count`와 `/processing`의 소스 상태를 확인했다. `/projects/{id}/sources`는 POST 전용이어서 GET 405가 정상 계약이다. 새 렌더 기록 조회는 HTTP 200·0건이며, 렌더 상태는 `NOT_STARTED`다. 실제 Chrome에서 Vite→FastAPI로 프로젝트 화면에 접속해 “저장된 렌더 기록이 없습니다” 안내 표시와 JavaScript 페이지 오류 0건을 확인했다. 신규 렌더가 없으므로 기존 환경의 **완료 기록을 가진 상태에서 FastAPI를 다시 시작해 조회·재생·다운로드하는 검증은 미실행**이다. 기존 QA 파일은 자동 복구됐다고 표시하지 않는다.

적용 후 파일 인벤토리 26개를 다시 전부 해시해 원본 9개·기존 렌더 17개의 상대 경로·크기·SHA-256이 적용 전과 모두 일치했다. PostgreSQL은 healthy·localhost 게시를 유지하고, Vite HTTP 200과 Tailscale Serve HTTPS 443·TCP 11434·2222 설정도 유지됐다. 다른 tailnet 기기의 실제 접속은 이번에 확인하지 않았다.

## 복구 및 남은 검증

새 영상 렌더는 실행하지 않았다. 완료 기록의 기존 환경 재시작 복구와 두 MP4 재생·다운로드는 신규 기록이 생긴 뒤 별도로 검증해야 한다. 현재 빈 기록 API·React 표시는 확인했지만 이는 완료 파일의 복구 검증이 아니다.

향후 장애 시 새 렌더 접수를 멈추고 DB 덤프와 파일 인벤토리를 보존한다. 이전 코드·기능 플래그 상태로 되돌리는 절차를 우선한다. 기존 DB 백업을 현 DB 위에 바로 복원하거나 신규 기록이 있는 테이블을 임의로 drop하지 않는다. 복원·다운그레이드가 필요하면 데이터 손실 범위를 판단하고 별도 승인 후 진행한다.

기존 DB migration 및 FastAPI 교체는 사용자 승인 후 수행했다. Git 커밋·Push는 하지 않았다.
