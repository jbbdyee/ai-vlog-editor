# QA-03 — 렌더 결과 파일 SHA-256 무결성 구현과 격리 검증

상태: **제품 코드·Alembic revision 작성, 합성 파일·격리 PostgreSQL 검증 완료. 현재 개발 DB 미적용, 실행 중 FastAPI 미교체.** 시작 Git `main`, HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB/DEV/QA/EVAL 미커밋 변경과 보호 대상 백엔드 테스트 3개(변경량 6/1, 6/1, 1/1, 파일 SHA-256 동일)를 보존했다. 커밋·Push 없음. 실제 영상 렌더·유료 API 호출 없음. [QA-01 결함](qa-01-render-recovery.md)과 [QA-02 설계](qa-02-render-integrity-design.md)를 기준으로 했다.

## 문제·원인

- **문제:** 렌더 완료 후 기본 MP4를 같은 크기의 다른 바이트로 바꾸면 다운로드 API가 200, `download_available=true`를 반환했다(QA-01 재현).
- **원인:** `project_render_runs`는 경로·크기·코덱만 저장하고 콘텐츠 해시가 없었다. 제공 경로는 경로·symlink·크기만 확인했다. 또한 Starlette `FileResponse`는 응답 시점에 경로를 **다시 열기** 때문에 검사 후 경로가 바뀌면 다른 파일을 보낼 수 있었다.

## 해결

### 1. DB·모델 (revision `e3a1c9d27b45`, down `b8c01e2a4f60`)

- `project_render_runs.base_sha256`, `srt_sha256`, `hard_sha256`: nullable `varchar(64)`.
- CHECK `ck_project_render_runs_{column}`: `NULL OR (length = 64 AND ltrim(col, '0123456789abcdef') = '')` — 소문자 64자리 16진수만 허용. PostgreSQL·SQLite에서 같은 의미로 동작해 단위 테스트(`create_all`)와 migration이 동일한 제약을 쓴다.
- 기존 행은 NULL 유지, **backfill 없음**, 상태 변경 없음. downgrade는 세 컬럼을 삭제하므로 기록된 해시 증거가 사라진다(격리 DB에서 확인).
- `main.py`: 영속 모드 시작 시 세 컬럼이 없으면 명확한 메시지로 시작을 거부한다(새 코드+미적용 DB에서 렌더 조회가 500을 내는 대신 즉시 실패).

### 2. 완료 시 기록 (`persistent_render_execution.py`)

- 기존 `verified_output`(고정 경로·루트·symlink·크기) 통과 후, 같은 파일 핸들에서 스트리밍 SHA-256을 계산한다(`record_output_digest`). 해시 중 장치·inode·크기·mtime이 바뀌거나 경로가 다른 파일로 교체되면 실패한다.
- **기본 MP4 해시 실패 → COMPLETED 미기록.** 기존 예외 경로를 그대로 타며 파일이 남아 있으면 기존 정책대로 `RECONCILIATION_REQUIRED`/`RENDER_RECOVERY_REQUIRED`가 된다(자동 재렌더·자동 공개 없음).
- SRT·하드 자막 MP4는 실제 생성·검증된 파일 각각의 해시를 기록한다. 해당 파일만 실패하면 기존과 같이 그 파일을 제외하고 `SUBTITLE_OUTPUT_INVALID`로 남기며 기본 MP4 완료는 보존한다.
- COMPLETED 갱신 직전 세 파일의 식별자(장치·inode·크기·mtime)를 다시 확인해 해시→commit 사이 교체를 좁힌다. owner token·상태 fencing, lease, advisory lock 등 기존 상태 전이·동시성 제어는 변경하지 않았다. DB와 파일의 완전한 원자성은 주장하지 않는다.
- 프로세스 로컬 registry(영속화 비활성 모드)도 완료 시 해시를 붙인다. 파일이 없거나 읽을 수 없으면 해시 None으로 남아 제공되지 않는다(보호 테스트의 기존 COMPLETED+404 계약 유지).

### 3. 제공 정책 (`routers/projects.py`, `render_integrity.py`, `verified_file_response.py`)

| 파일 상태 | 상태 API | 다운로드·미리보기·Range |
| --- | --- | --- |
| 일치 | `integrity_status=VERIFIED`, 가용 | 200/206, `ETag: "sha256-<digest>"` |
| 없음·일반 파일 아님·symlink·경로 불일치 | `MISSING`, `safe_error_code=RENDER_FILE_MISSING` | 404 `RENDER_NOT_FOUND` (기존 계약 유지) |
| 크기 다름 또는 SHA-256 불일치 | `CORRUPT`, `RENDER_FILE_CORRUPT` | 409 `RENDER_FILE_CORRUPT` |
| 해시 없는 과거 COMPLETED 기록 | `UNVERIFIED`, `RENDER_FILE_UNVERIFIED` | 409 `RENDER_FILE_UNVERIFIED` |
| 하드 자막만 불일치/해시 없음/누락 | `hard_subtitle_status=CORRUPT/UNVERIFIED/MISSING` | 409 `SUBTITLED_RENDER_CORRUPT`/`_UNVERIFIED`, 404 `SUBTITLED_RENDER_NOT_FOUND`; 기본 MP4는 계속 제공 |
| 기본 MP4 문제(하드 자막 정상이어도) | `hard_subtitle_status=BASE_UNAVAILABLE` | 하드 자막 다운로드도 기본 MP4 오류 코드로 차단(기존 종속 계약) |
| SRT만 불일치 | `subtitle_integrity_status=CORRUPT`(진단) | 기본·하드 자막 MP4 유지. SRT 제공 API는 추가하지 않음 |

- NULL 해시는 일치로 간주하지 않는다. 기록 상태(COMPLETED)·스냅샷·파일은 삭제·FAILED 전환·자동 재등록하지 않고, 현재 가용성만 false로 보고한다. 원래 바이트로 복원되면 다시 제공된다. 기준 해시는 자동 갱신하지 않는다.
- 응답 필드 `integrity_status`, `subtitle_integrity_status`, `hard_subtitle_integrity_status`는 추가(선택) 필드라 기존 클라이언트와 호환된다. 검증 실패 응답은 JSON 오류 본문뿐이며 파일 바이트를 포함하지 않는다(테스트로 확인).
- 상태·기록 API는 전체 해시를 읽으므로 이벤트 루프가 아닌 threadpool에서 계산한다.

### 4. 검사-제공 경쟁 조건(TOCTOU)

- **경로 교체:** 검증한 **열린 핸들 그대로** 스트리밍한다(`VerifiedFileResponse`, Starlette 1.6 `FileResponse`의 Range/416/multipart 동작 유지, `pathsend` 미사용). 검증 후 경로를 다른 파일로 바꿔도 검증된 바이트만 나간다.
- **Windows(현재 배포 호스트):** 핸들을 `FILE_SHARE_READ`만 허용해 연다. 열려 있는 동안 다른 프로세스의 쓰기·이름 변경·삭제가 실패한다(테스트로 확인). 이미 쓰기 핸들을 가진 프로세스가 있으면 열기에 실패해 MISSING으로 차단된다.
- **POSIX:** `O_NOFOLLOW`로 열지만 강제 잠금이 없어 같은 inode의 제자리 수정은 막지 못한다. 완화: 전체 응답은 스트리밍 중 다시 해시하고 마지막 청크를 보류해 불일치 시 연결을 중단(완성된 잘못된 파일을 보내지 않음), Range 응답은 마지막 청크 전에 핸들 식별자(장치·inode·크기·mtime)를 재확인. mtime까지 되돌리는 의도적 제자리 수정과 Range 일부 바이트는 남은 위험이다.

### 5. React

- 기본 파일: 누락(`기본 파일 누락`)·SHA-256 불일치(`기본 파일 변형 감지`)·해시 없음(`무결성 기록 없음`)을 기록 목록과 결과 영역에서 구분해 안내한다. 기록은 삭제하지 않고 해당 항목의 “이 결과 보기”만 비활성화한다.
- 하드 자막: `CORRUPT`, `UNVERIFIED`, `BASE_UNAVAILABLE` 표시. SRT 불일치는 진단 문구만 표시.
- 다운로드 409 코드를 사용자 문구로 변환하고 상태·기록을 다시 조회한다. 미리보기 `<video>` 오류 시에도 상태를 다시 읽어 정확한 원인으로 전환한다.
- 이전 성공/최신 실패 표시 정책은 유지. 새 필드가 없는 기존 API 응답에서도 기존 문구(`기본 파일 누락`)로 동작한다.

## 검증

### 백엔드 테스트(합성 바이트·SQLite)

`backend/tests/test_qa03_render_integrity.py` **23건 통과**: 완료 시 세 파일 해시 기록, 기본 해시 실패·해시 후 교체 시 COMPLETED 미기록, SRT 해시 실패 시 SRT만 제외, 완료 시 하드 자막 누락, 같은 크기 다른 바이트(상태·목록·다운로드·Range·하드 자막 종속 차단, 기록 보존, 원본 복원 시 재가용), 다른 크기, 파일 누락(기존 404), 하드 자막만 손상, SRT만 손상, 해시 없는 과거 기록(보존·차단·backfill 없음), 하드 자막 해시 없음, 새 registry 객체(재시작) 후 조회·이후 변조 차단, 이전 성공+최신 실패, Range(단일·suffix·multipart·416·If-Range), 동시 Range 16+전체 4, 프로세스 로컬 registry 해시, 무결성 원시 함수, SQLite CHECK, 검증 후 경로 교체, Windows 쓰기 거부, 스트리밍 중 불일치 중단, 미검증 핸들 제공 거부.

변이 확인: 라우터의 해시 비교를 무력화한 변이에서 핵심 5개 테스트가 모두 실패했다(테스트가 공허하지 않음).

### QA-01 expected failure 재검증

- 구현 후 **수정 없이** 일회용 격리 DB(`cutory_qa01_qa03rerun_*`, 55432)에서 실행: 정상 2건 통과, 해당 테스트는 여전히 expected failure였다. 원인은 이 테스트의 첫 assertion이 결함 당시 관측값인 **다운로드 200**을 단언하고 있었기 때문이며, 실제 응답은 409로 바뀌었다(`AssertionError: 409 != 200`).
- 결함이 실제 구현으로 해결됐으므로 `@expectedFailure`를 제거하고 단언을 차단 계약(다운로드·Range 409 `RENDER_FILE_CORRUPT`, 응답 본문에 변조 바이트 없음, `download_available=false`, `safe_error_code=RENDER_FILE_CORRUPT`, DB 행 COMPLETED 유지·해시 형식)으로 바꿨다. 재실행 **3건 모두 통과**. 일회용 DB는 제거했다.

### 격리 migration 검증(55432 `cutory-web08b-isolated`, 기존 DB 3개 미변경)

| 시험 | 결과 |
| --- | --- |
| `test_qa03_migration_isolated.py`(빈 일회용 DB) | base→b8 후 6개 렌더 행(COMPLETED 2·FAILED·INTERRUPTED·RECONCILIATION_REQUIRED·QUEUED) 삽입, b8에서 새 코드 시작 거부 확인 → e3 upgrade: 단일 head, 세 컬럼 nullable `varchar(64)`, CHECK 3개, 전 테이블 행 수·기존 컬럼 md5 동일, NULL 유지(backfill 0), 잘못된 값(대문자·63/65자·비16진수·공백) 거부, 올바른 값 허용, 새 코드 시작 성공 → b8 downgrade: 컬럼 제거, 행 수·기존 컬럼 md5 동일 → e3 reupgrade: 동일, 기록했던 해시는 사라져 NULL(증거 손실 확인). **통과** |
| WEB-08C 백업 복원(`db.dump` SHA-256 `ed9601…7bf87a20`, revision `ca3e4f5a6b7c`) | ca3→b8→e3→b8→e3 각 단계에서 기존 15개 테이블+`project_render_runs`의 행 수와 전체 행 md5가 복원 직후·b8과 모두 일치(프로젝트 12, 소스 9, 후보 44, Evidence 120, 렌더 0). 재업그레이드 후 non-null 해시 0. **PASS** |

설명: 첫 migration 시험은 65자 값이 CHECK 이전에 `varchar(64)` 길이 제한(`DataError`)으로 거부되어 테스트의 예외 기대(`IntegrityError`만)가 틀렸다. 두 예외 모두 DB 거부로 인정하도록 테스트를 고쳐 재실행했다. 모든 일회용 DB는 제거했다.

### 회귀

- 백엔드 전체 `unittest discover`: **593건 중 554 통과, 36 건너뜀, 3 실패.** 3 실패는 테이블 집합 단언(`test_alembic_foundation`, `test_database`, `test_product_models`)으로, WEB-08B의 `project_render_runs` 추가 이후 기대 집합이 갱신되지 않은 **기존 실패**다. QA-03 변경 전 기준 실행에서 `test_alembic_foundation`의 같은 실패를 확인했고, 나머지 두 건은 변경 전 실행하지 않았지만 같은 누락 테이블(`project_render_runs`)을 보고한다. QA-03은 테이블을 추가하지 않았으며 범위 밖이라 수정하지 않았다. 건너뜀에는 Windows symlink 권한, 환경변수 전용 격리 DB 테스트 등이 포함되며 통과로 집계하지 않는다. 보호 대상 3개 파일은 그대로 통과한다.
- 참고: 이 Claude Code 세션은 `.venv`의 기준 Python 경로가 Codex 가상화 경로라 기준 인터프리터에 `.venv` site-packages를 `site.addsitedir`로 더해 실행했다. `PYTHONPATH`만 쓰면 pywin32 `.pth`가 처리되지 않아 MCP 테스트 2건이 import 오류를 내며, 이는 실행 환경 문제로 확인했다.
- React Vitest 전체 **52건 통과**(기존 45+QA-03 7), TypeScript `tsc -b` 통과, Vite 빌드는 스크래치 경로로 출력해 통과(`web/dist` 미변경).
- Mock Chrome(Playwright, 실행 중 Vite 5173 재사용·재시작 없음, 모든 API 모의): QA-03 2건+QA-01/WEB-03/04/10/11/12 20건 **22건 통과**. 실제 Chrome에서 `<video>` Range 요청이 409를 받으면 상태를 다시 읽어 무결성 원인으로 전환되는 것을 확인했다. 쓰기 요청 0건.

## 성능(합성 파일, warm cache, Intel Core Ultra 7 265KF·NVMe)

| 측정 | 결과 |
| --- | --- |
| 단일 검증 64/256/1024MiB | 약 0.036 / 0.143 / 0.58초(약 1.75GiB/s) |
| 256MiB 동시 검증 1/4/16 스레드(각 2회) | p50 0.153 / 0.183 / 0.365초, 16 스레드 32회 8GiB 읽기 wall 0.77초 |
| API: 256MiB 완료 해시 포함 registry 실행 | 0.43초 |
| API: `/rendering` 1회, Range 1KiB(앞·200MB 지점) | 각 약 0.14초 (거의 전부 해시) |
| API: 256MiB 전체 GET(사전 해시+스트리밍 해시) | 0.74초, 바이트 일치 |
| API: 동시 Range 64KiB 4/16건 | p50 0.177 / 0.428초 |

- 현재 `outputs/`의 기존 MP4·SRT 17개는 최대 0.33MiB라 현재 비용은 무시할 수준이다. 위험은 긴 vlog 결과다: Range 요청마다 전체 파일을 다시 해시하므로 1GiB 결과는 탐색 요청마다 약 0.6초(warm) 지연, 하드 자막 Range는 기본 MP4까지 검증해 약 2배다. cold cache·외장 HDD(약 150MB/s 가정 시 1GiB 약 7초)는 더 느리며 이번에 측정하지 않았다(Windows 캐시 비우기 권한 없음). 기록 목록 20개 × 1GiB는 warm 기준 약 12초 이상이다.
- **정책을 약화하지 않았다.** 크기·mtime 캐시, 요청 간 결과 재사용, 진행 중 해시 공유(singleflight)는 구현하지 않았다. 대안(승인 필요): ① 동시 진행 중인 동일 핸들 식별자 해시 공유(singleflight; Windows 쓰기 거부 핸들 하에서는 안전성 논증 가능), ② 목록 API에 `UNCHECKED` 상태를 두고 선택한 렌더만 검증, ③ 완료 시 청크별 해시(Merkle) 기록 후 Range 구간만 검증 — DB 변경 필요.

## 남은 한계·승인 필요

1. **현재 개발 DB 적용 미실행.** 읽기 전용 확인 결과 현재 DB는 `b8c01e2a4f60`, 렌더 기록 0건, 프로젝트 13건이다. 적용 시 순서: 새 백업·격리 복원 확인 → 새 렌더 접수 중지 → `alembic upgrade e3a1c9d27b45` → FastAPI를 새 코드로 재시작 → 상태·기록 API 확인. **새 코드로 먼저 재시작하면 영속 모드 시작이 거부된다**(의도된 fail-fast). 반대로 migration 후 이전 코드로 렌더하면 그 기록은 해시 NULL이라 새 코드에서 UNVERIFIED로 차단된다.
2. 실행 중 FastAPI(8000, `--reload` 없음)는 이전 코드로 동작 중이며 교체하지 않았다. **Vite(5173)는 HMR로 새 React 코드를 이미 제공**하지만 새 필드가 없는 이전 API 응답과 호환되도록 작성했다.
3. 하드 자막 MP4의 기본 MP4 종속 차단, 해시 없는 과거 기록 기본 차단, 409 코드·React 문구, 요청마다 전체 해시 비용은 QA-02 제안대로 구현했으며 운영 정책으로 확정하려면 승인이 필요하다.
4. 실제 렌더 MP4(FFmpeg 출력)의 완료 해시·변조 검출, 다중 worker/호스트, 실제 프로세스 강제 종료, POSIX 제자리 수정, cold cache·대용량 실측은 미검증이다. Streamlit(`frontend/app.py`)은 새 하드 자막 상태값(`CORRUPT`/`UNVERIFIED`/`BASE_UNAVAILABLE`)에 문구가 없어 아무것도 표시하지 않는다(범위 밖, 미수정).
5. 인증·소유권이 없어 공개 배포 경계로 해석하면 안 된다.

원본 영상·GT·Manifest·기존 렌더 파일, 현재 DB, FastAPI/Vite/Tailscale 실행 상태와 PostgreSQL localhost 게시는 변경하지 않았다.
