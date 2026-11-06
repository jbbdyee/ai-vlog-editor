# WEB-08B — 렌더 기록 영속화·서버 재시작 복구 검증

상태: **제품 코드 구현 및 격리 DB·실제 영상 재시작 E2E 완료, 기존 PostgreSQL 미적용**. `main`, 시작 HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. [WEB-08A 설계](web-08a-render-persistence-design.md)에 따라 기존 WEB-01~07/EVAL-01/02 미커밋 파일과 보호 대상 백엔드 테스트 3개를 보존했다. Git 커밋·Push 없음. 이 기록의 재시작은 **격리 API(8001)**만 대상으로 하며 기존 API(8000)·Vite(5173)·PostgreSQL(5432)은 종료·재시작하지 않았다.

## 백업·격리 게이트

| 항목 | 실제 결과 |
| --- | --- |
| 기존 DB | `postgres:17.11` 기존 Compose 컨테이너 healthy. `pg_dump -Fc`와 `pg_restore -l` 검증 후 Git 제외 `temporary/web08b-backup-20261027-222632/db.dump`로 보관. 81,470바이트, SHA-256 `595911cd1be7d083d145a02d4cb9dd3c67000e07ac9eba1c9bc1d65db9e288b0` |
| 기존 렌더 | `outputs/projects/` 파일 17개, 총 2,025,979바이트를 같은 백업 폴더에 사본·상대 경로/크기/SHA-256 인벤토리로 보관. 제한된 프로세스에서 일부 하드 자막 파일 읽기 거부가 있어 권한을 바꾸지 않고 접근 가능한 로컬 컨텍스트에서 전체 사본 해시 일치를 확인 |
| 격리 DB | 별도 컨테이너 `cutory-web08b-isolated`, DB `cutory_web08b_restore`, 로컬 포트 `127.0.0.1:55432`, 별도 Docker volume `cutory_web08b_pgdata_20261027`; 기존 `postgres:17.11` 로컬 이미지 재사용·다운로드 없음. `pg_restore --exit-on-error` 성공. 원본/격리의 16개 테이블 행 수·Alembic `ca3e4f5a6b7c`가 일치했고 프로젝트 7개·소스 9개를 확인 |
| 격리 migration | 새 revision `b8c01e2a4f60`을 **격리 DB에만** upgrade. 격리 DB에서 `downgrade ca3e4f5a6b7c`와 재-upgrade를 검사한 뒤 실제 QA 실행. 기존 DB는 마지막 점검까지 `ca3e4f5a6b7c` 그대로 |
| 임시 인증정보 | 격리 컨테이너 시작에만 쓴 Git 제외 임시 env 파일은 시작 후 제거. `.env` 값·시스템 PATH·기존 볼륨을 수정하지 않음 |

백업과 복원 검증이 끝나기 전에는 마이그레이션을 실행하지 않았다. 위 백업과 격리 데이터는 개인 데이터가 포함될 수 있어 Git에서 제외되며 공개 문서에는 원본 프레임·전사 원문·비밀키·로컬 절대경로를 기록하지 않는다.

## 구현 및 API 계약

- `backend/app/models/render.py`와 Alembic revision에 `project_render_runs`를 추가했다. 새 렌더 ID는 접수 전에 결정하고, 프로젝트 FK, 순서 있는 후보/source/시각 스냅샷 및 SHA-256 fingerprint, `QUEUED/RUNNING/COMPLETED/FAILED/INTERRUPTED/RECONCILIATION_REQUIRED`, 시각·상대 결과 참조·크기·코덱·안전 오류 코드, 소유 token·heartbeat·lease를 기록한다. 프로젝트당 활성 행 하나만 허용하는 부분 유니크 인덱스가 있다. 예외 메시지·원본 경로·전사 원문은 DB에 저장하지 않는다. API의 안전한 메시지는 코드와 고정 응답에서 만든다.
- `PersistentProjectRenderRunRegistry`는 프로젝트 행 잠금과 DB 트랜잭션으로 접수하고, 별도 heartbeat와 PostgreSQL advisory lock으로 살아 있는 다른 프로세스의 작업을 보호한다. `render_project_edit_plan`에는 사전 ID·계획 스냅샷 검증을 연결했으며 편집·FFmpeg 알고리즘은 변경하지 않았다. 최종 파일의 고정 상대 경로·루트·symlink·크기를 다시 검사한 후에만 `COMPLETED`를 commit한다. DB 갱신 실패 시 완료를 반환하지 않고 파일은 보존한다. lease 만료와 소유 lock 해제가 확인된 작업은 파일 유무에 따라 `INTERRUPTED` 또는 `RECONCILIATION_REQUIRED`로 표시하고 자동 재렌더하지 않는다.
- 선택적 SRT·하드 자막 결과의 사후 파일 검증이 실패해도 검증된 기본 MP4의 완료 상태는 유지한다. 누락된 결과 참조는 저장하지 않고 해당 자막 오류 코드만 기록한다. 이 후속 방어 경로는 합성 파일 단위 테스트로 확인했으며 실제 렌더 E2E에서 장애를 주입하지 않았다.
- 기존 `POST /projects/{id}/render`의 `202/accepted/status_url`에 `render_id`만 추가했다. `GET /projects/{id}/rendering`은 최신 DB 시도를 반환하며 중단·누락을 구분한다. 새 `GET /projects/{id}/renders?limit=20&before=<render_id>`는 프로젝트 범위의 페이지형 기록과 각 결과 가용성을 제공한다. 기본·자막 다운로드 URL, MP4 MIME, 파일명, Range 응답은 유지한다. 과거 성공 렌더는 새 시도가 실패해도 해당 ID로 접근할 수 있다. 존재하지 않는 프로젝트/렌더, 소속 불일치, 미완료·파일 누락은 구분한다.
- React는 프로젝트별 Query key로 기록을 읽고 이전 완료 ID를 선택해 기존 WEB-07 플레이어·다운로드를 재사용한다. 최신 실패·중단과 과거 성공을 같이 표시하며 파일 누락은 재생 버튼을 비활성화한다. 새 요청과 프로젝트 전환 때 선택 상태를 초기화한다.
- **적용 게이트:** `CUTORY_RENDER_PERSISTENCE_ENABLED=1`일 때만 앱 시작 시 새 테이블 존재를 확인하고 DB registry를 사용한다. 테이블 없이 활성화하면 시작을 거부한다. 승인 전 기존 DB/서버는 기존 메모리 경로로 계속 동작한다. 이 기능 플래그는 사용자 인증이나 공개 배포 허가가 아니다.

## 검증 수준별 결과

| 수준 | 결과와 한계 |
| --- | --- |
| Python 단위·관련 회귀 | `unittest` 48건 중 **32 통과, 16 건너뜀, 실패 0**. 새 영속 API 전용 7건은 DB 상태·계획 스냅샷·재시작 객체 재조회·Range·기본/자막 누락·프로젝트 불일치·이전 성공 보존·중복·lease·완료 DB 갱신 실패·경로 방어와 SRT 누락 시 기본 MP4 보존을 합성 파일/SQLite로 확인. 16건은 기존 Windows 선택적 실행 조건이며 통과로 집계하지 않음. 보호 대상 테스트 3개는 수정하지 않음 |
| 실제 PostgreSQL 통합 | 복원한 격리 DB에서 두 registry의 동시 접수 시 두 번째 거부, 살아 있는 작업이 advisory lock을 쥔 상태에서 의도적으로 만료시킨 lease는 `QUEUED` 유지, 완료 후 다른 registry 조회 성공, 소유자가 없는 만료 행은 `INTERRUPTED` 및 과거 성공 접근 유지를 확인. 테스트용 합성 바이트는 실제 영상 검증으로 집계하지 않음 |
| React 단위·빌드 | Vitest 33건 통과·실패 0, TypeScript 검사와 Vite production build 통과. 신규 2건은 최신 실패 중 과거 성공 선택과 중단·파일 누락 안내. JSDOM 미디어 메서드 미구현 로그는 실패가 아님 |
| Mock Chrome | 기존 브라우저 테스트 7건 통과·실패 0. API 응답을 가로채는 테스트로 실제 서버/미디어 검증과 구분 |
| 실제 Chrome·격리 FastAPI/DB | 복원 DB의 기존 P1-S01·S02 프로젝트 계획(2개 후보, 두 소스)을 **새 격리 출력**으로 실제 렌더했다. 기본 `final.mp4`·`final.srt`·한국어 하드 자막 `final-subtitled.mp4`가 생성됐고 DB에 완료 ID가 남았다. 격리 API 프로세스를 실제 종료·재시작한 뒤 같은 프로젝트 조회·기록 목록·두 MP4 재생/seek/프레임 디코딩·두 다운로드 SHA-256 일치를 Chrome에서 확인. 자막 약 2초 캡처에서 한국어 표시를 확인. 전체 프레임·다른 브라우저/OS·정량 편집 품질은 미검증 |

실제 렌더 검증 중 첫 Chrome 실행은 MP4 생성·완료 ID 기록까지 성공했지만, 뒤따른 화면의 동명 버튼 선택자 때문에 테스트가 실패했다. 이를 수정해 다시 실행할 때 Playwright가 `test-results/`를 초기화하여 첫 ID 파일이 사라져 **두 번째 새 렌더**가 생성됐다. 두 렌더는 서로 다른 ID 디렉터리에 보존됐고 기존 결과를 덮어쓰지 않았다. 이후 테스트는 ID를 환경변수로 고정해 추가 렌더 없이 통과시켰다. 최종 재시작 검증 ID는 `906fbe02-6234-4164-9af2-6fc3d1923234`이며 첫 ID `93277f77-372d-4996-ac3c-83eb61c77f5c`도 격리 DB/출력에 남았다. 이 시험 기록은 기존 DB나 QA 렌더의 자동 등록이 아니다.

최종 격리 결과: 기본 MP4 253,677바이트/SHA-256 `2d2150168971c9a8e633e68fd464f24d76833e661317cd49ec86a8cd4bae5c2d`, 자막 MP4 268,513바이트/SHA-256 `3b720a6e77add537c8391a0483bec4fa14fb22f487a9be73cd59598fefc6a523`, SRT 172바이트. 두 MP4는 FFprobe 기준 5.433333초, H.264 영상/AAC 오디오다. 같은 계획·원본·결정적 설정으로 생성돼 WEB-04 산출물과 바이트 해시가 일치하지만 이번에는 새 DB ID·격리 경로에서 생성됐다. 캡처는 Git 제외 `web/test-results/`에만 있다.

실행 전후 `storage/originals/` 9개(총 1,746,076,115바이트)와 기존 `outputs/projects/` 17개의 경로·크기·SHA-256은 백업 인벤토리와 모두 일치했다. 원본 영상·GT·Manifest·기존 렌더를 수정하거나 삭제하지 않았다. 마지막 확인에서 기존 DB `cutory:5432`는 `ca3e4f5a6b7c`, 격리 DB `cutory_web08b_restore:55432`만 `b8c01e2a4f60`이다.

## 남은 위험·기존 환경 적용 절차

1. **별도 승인 필요:** 기존 DB에 마이그레이션 적용, 기존 API 프로세스 교체, `CUTORY_RENDER_PERSISTENCE_ENABLED=1` 설정은 하지 않았다. 기존 서버는 현재 메모리 방식이며 새 화면의 기록 조회는 그 서버에서 제공되지 않는다. 승인 시 백업 재확인→기존 API 작업 정지/무중단 계획→migration→테이블 확인→새 API 프로세스 활성화→기존 데이터·새 격리 프로젝트로 회귀 확인 순서로 진행한다. 실패 시 새 접수를 중단하고 DB/파일 백업을 유지한 채 이전 코드·기능 플래그 해제로 되돌린다. 실제 DB에서 신규 행이 생긴 후에는 테이블을 무단 drop하지 않는다.
2. 프로세스 사이 동시성·lease는 격리 DB 두 registry로 검사했다. 실제 여러 FastAPI worker/호스트, 장시간 FFmpeg 중 DB 장기 장애, 작업 소유 lock의 네트워크 단절은 별도 운영 검증이 필요하다. 인증·사용자 소유권이 없어 외부 공개 배포는 불가하다.
3. 파일과 DB는 하나의 트랜잭션이 아니므로 완료 직전 장애의 파일은 수동 조사 대상으로 남고 자동 등록·재렌더하지 않는다. 완료 이후 파일 교체 경쟁, 다른 브라우저의 자막 `attachment` 재생, 정량 영상 품질은 미검증이다. 과거 QA 파일만으로는 당시 계획/상태를 증명할 수 없으므로 자동 이관하지 않는다.
