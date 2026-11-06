# QA-06 — 실제 개발 DB 적용 준비 및 승인 게이트

- 일자: 2026-11-03
- 범위: QA-03 migration(`e3a1c9d27b45`)을 실제 개발 DB에 적용하기 전의 준비. **migration 적용과 8000 FastAPI 재시작은 승인 대기이며 실행하지 않았다.**
- 사용자 승인 운영 정책: Windows 단일 호스트 개발 환경에 한정한다.
  1. 해시 없는 과거 완료 기록은 차단한다.
  2. 기본 MP4가 손상되면 하드 자막 MP4도 차단한다.
  3. 기존 409 코드와 한국어 안내를 쓴다.
  4. 요청마다 파일 전체 SHA-256을 검증한다.
  5. 대용량 최적화는 범위에서 제외한다.
- 결과: **준비 게이트 PASS. 실제 적용을 권장한다(승인 시).**

## 1. 적용 전 확인 (읽기 전용)

| 항목 | 결과 |
| --- | --- |
| Git | HEAD `1a2d7d7`, 미커밋 66항목. QA-05 종료 상태에서 QA-05 handoff 추가만 다르다. 작업 중 `git status` 변화 없음(이 문서와 동기화 문서 제외) |
| 보호 대상 테스트 3개 | `test_clip_download_api.py` 6/1, `test_project_render_api.py` 6/1, `test_project_rendering.py` 1/1. SHA-256 동일 |
| 개발 DB | `postgres:17.11` healthy, `127.0.0.1:5432`만 게시, DB `cutory` |
| revision | **`b8c01e2a4f60`** |
| 데이터 | 16개 테이블, 353행. 프로젝트 13, 소스 10, **렌더 기록 0**, 처리 단계 40, 장면 후보 44, 편집 계획 4(항목 9) |
| 활성 작업 | 다른 active 쿼리 0. 처리 단계 비완료 6건(PENDING 5, FAILED 1)은 모두 10-23·10-25의 과거 기록이고 실행 중이 아니다 |
| FastAPI 8000 | PID 35472, `python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`, 2026-11-03 12:48 기동, `--reload` 없음, `/health` 200. QA-03 이전 코드를 메모리에 적재한 상태 |
| Vite 5173 | PID 41712(10-27 기동), 200. 재시작하지 않음 |
| Tailscale | 서비스 Running. Serve HTTPS 443 → `http://127.0.0.1:5173`(tailnet only). 재시작·설정 변경 없음 |
| 그 밖의 프로세스 | 8001 `web08b_isolated_server`(10-27, Codex 작업 잔존). 손대지 않음 |
| 파일 인벤토리 | 27개: 원본 10개 1,924,580,290 B, 렌더 17개 2,025,979 B. WEB-08C 목록 26개의 크기·SHA-256 전부 일치. 추가 1개는 이미 기록된 11-03 MOV(178,504,175 B, [기록](scene-preview-recovery-2026-11-03.md)). 작업 종료 시 재해시 결과 크기·SHA-256·mtime 전부 동일 |
| 절차 재확인 | QA-03(migration·시작 가드), QA-04(7단계 계획·중단 조건·롤백), QA-05(Streamlit 호환·회귀 0 실패) 확인. 아래 4장에서 QA-04 계획을 보완 |

### 8000 기동 환경 (PEB 읽기 전용 조회, 비밀값 미기록)

- `CUTORY_RENDER_PERSISTENCE_ENABLED=1`
- PATH 맨 앞: `.venv\ffmpeg\ffmpeg-9.0.2-essentials_build\bin`(번들 FFmpeg/FFprobe)
- `OPENAI_API_KEY`, `GEMINI_API_KEY`: **빈 값으로 설정**됨(로컬·오프라인 실행). `.env`가 키를 채우지 않도록 의도한 상태다.
- `POSTGRES_HOST=127.0.0.1`, `POSTGRES_PORT=5432`, `POSTGRES_DB=cutory`. 사용자명과 비밀번호는 `.env` 값이며 설정 여부만 확인했다.
- `CUTORY_SUBTITLE_FONT_PATH`: 미설정(현재와 동일하게 유지).
- 기록 위치: `temporary/qa06-rollout-20261103/env-8000-observed.json`(값은 마스킹).

**발견:** 8000은 Codex 앱의 가상화 경로(`사용자별 uv Python 경로`)에 있는 인터프리터로 실행 중이다. `.venv/pyvenv.cfg`의 `home`도 그 경로를 가리킨다. Codex 밖(Claude Code 셸)에서는 이 경로가 없어 `.venv\Scripts\python.exe`가 실행되지 않는다(`No Python at …`). 따라서 QA-04 5단계의 "같은 명령으로 재기동"은 그대로 할 수 없다. 대신 아래 런처를 준비하고 검증했다.

## 2. 백업과 복구 검증

| 단계 | 결과 |
| --- | --- |
| 백업 | 컨테이너 안에서 `pg_dump -U cutory -d cutory -Fc`를 실행해 `temporary/qa06-rollout-20261103/db.dump`로 복사했다(Git 제외). 컨테이너 임시 파일은 삭제했다 |
| 크기·해시 | **95,372 B**, SHA-256 `0f6121c16a3eb9a79d18c22c36eb9eca03ed76946ec5489637875c0279e208bb`. 컨테이너 안 해시와 복사본 해시가 같다. `db.dump.sha256`에 저장 |
| 유효성 | 격리 컨테이너 `pg_restore -l` 성공. 목록의 TABLE DATA 17항목(16개 테이블 + `alembic_version`). `pg_restore-list.txt`에 저장 |
| 격리 복원 | `cutory-web08b-isolated`(127.0.0.1:55432)의 새 DB `cutory_qa06_restore_20261103203240`에 `pg_restore --exit-on-error --no-owner` 성공. revision `b8c01e2a4f60` |
| 원본과 비교 | 개발 DB는 `default_transaction_read_only=on` 세션으로 조회했다. 16개 테이블의 행 수와 행 내용 md5가 **모두 일치**했다(353행, 프로젝트 13, 렌더 0) |
| migration | 격리 DB에서 `upgrade e3a1c9d27b45` → `downgrade b8c01e2a4f60` → `upgrade e3a1c9d27b45`. 각 단계 뒤 데이터(해시 컬럼 제외)가 개발 DB와 **일치**했다. e3에서 `base_sha256`/`srt_sha256`/`hard_sha256` 3개는 nullable, CHECK `ck_project_render_runs_{base,srt,hard}_sha256` 3개, 해시 값이 채워진 행 0 |
| 새 코드 기동 (in-process) | 영속 모드 앱을 격리 DB에 연결했다(연결 대상 55432 단언). `/health` 200, `/projects` 200. 프로젝트 13개마다 `/`, `/rendering`, `/renders`, `/scene-edit-plan` 52건 모두 200. `/rendering`은 `NOT_STARTED`와 `integrity_status` 필드를 반환했다. 기동 후에도 데이터가 개발 DB와 같았다 |
| 런처 시험 기동 | `temporary/qa06-rollout-20261103/start_fastapi.py --port 8009`를 격리 DB 환경으로 실제 프로세스로 띄웠다. 실제 STT 모델을 로드하고 시작했으며 `/health` 200, 프로젝트 13건, `/rendering`에 `integrity_status`가 나왔다. 프로세스 환경도 영속 플래그 1, FFmpeg PATH, 격리 DB를 확인했다. 확인 후 **8009 프로세스만 종료**했다 |
| 판정 | `isolated-restore-check.json`의 RESULT **PASS** |

격리 복원 DB `cutory_qa06_restore_20261103203240`은 적용 후 비교와 장애 분석을 위해 남겨 두었다. 개발 DB 사본이 들어 있으므로 QA-06 종료 후 삭제를 승인받아 처리한다. 다른 `cutory_qa%` DB는 없다.

### 런처 (`temporary/qa06-rollout-20261103/start_fastapi.py`, Git 제외)

- 실제 base 인터프리터(`…\Packages\OpenAI.Codex_…\LocalCache\Roaming\uv\python\cpython-3.12.15…\python.exe`)에 `.venv` site-packages를 추가해 `uvicorn.run("backend.app.main:app", host="127.0.0.1", port=…)`을 실행한다. QA-04 실제 렌더 때 쓴 방식과 같다.
- 런처가 설정하는 값:
  - `CUTORY_RENDER_PERSISTENCE_ENABLED=1`
  - PATH 앞에 번들 FFmpeg bin(ffmpeg.exe·ffprobe.exe 존재를 단언)
  - `OPENAI_API_KEY=""`, `GEMINI_API_KEY=""`
- `POSTGRES_*`는 설정하지 않는다. 프로세스 환경에 없으면 `.env`(override=False)에서 읽으므로 5432의 `cutory`가 된다.
- 차이점이 하나 있다. Python에서 빈 값을 넣으면 Windows OS 환경 블록에서는 변수가 지워진다. 앱 안의 `os.environ` 값은 빈 문자열로 남고 `.env`가 다시 채우지 않는다(직접 확인). 자식 프로세스는 FFmpeg·FFprobe·Docker뿐이며 Python 자식이 없으므로, 빈 값과 미설정은 동작상 같다.

## 3. 승인 게이트 보고

| 항목 | 내용 |
| --- | --- |
| 백업 경로 | `temporary/qa06-rollout-20261103/db.dump`(95,372 B, SHA-256 `0f6121c1…e208bb`), 파일 인벤토리 `file-inventory-before.json`(27개) |
| 백업 검증 | `pg_restore -l` 통과. 격리 복원 시 16개 테이블 행 수·md5가 개발 DB와 일치. upgrade/downgrade/재upgrade 무손실 |
| 적용 전 revision | `b8c01e2a4f60` |
| 적용 대상 | `e3a1c9d27b45`(add SHA-256 content digests to Project render outputs). `project_render_runs`에 nullable `String(64)` 3개 + CHECK 3개, 백필 없음. 대상 테이블은 0행이며 짧은 `ACCESS EXCLUSIVE` 잠금 1회 |
| 재시작 대상 | **8000 FastAPI만**. PID 35472(uv `python.exe`)와 부모 PID 18296(`.venv\Scripts\python.exe` 런처)을 명령줄 `backend.app.main:app --port 8000`으로 재확인한 뒤 종료한다. 이어서 `<base python> temporary/qa06-rollout-20261103/start_fastapi.py --port 8000`로 기동한다. Vite 5173, PostgreSQL, Tailscale, 8001은 그대로 둔다 |
| 필요 환경 변수 | `CUTORY_RENDER_PERSISTENCE_ENABLED=1`, 번들 FFmpeg PATH, `OPENAI_API_KEY`·`GEMINI_API_KEY` 빈 값(런처가 설정). `POSTGRES_*`는 `.env`에서 읽는다(5432/`cutory`). `CUTORY_SUBTITLE_FONT_PATH`는 미설정 유지 |
| 서비스 영향 | migration 자체는 0행 테이블 DDL이라 즉시 끝난다. 8000이 내려가 있는 동안(STT 모델 로드 포함, 수 초~수십 초 예상, 정확히 측정하지 않음) React(5173 프록시)와 tailnet 사용자의 API 요청은 실패한다. 처리·장면 분석 실행 상태는 메모리 기록이라 재시작 후 `NOT_STARTED`로 보인다(현재 활성 작업 0). 렌더 기록은 0건이므로 차단될 과거 기록이 없다. Vite는 이미 QA-03 React를 제공 중이고, Streamlit은 실행 중이 아니다 |
| 금지 구간 | migration 후 재시작 전까지 렌더 금지. 이전 코드가 해시 없는 COMPLETED를 만들면 새 코드에서 `UNVERIFIED`로 차단된다. 작업 창 동안 React·Streamlit 조작 중지를 공지한다 |

### 실행 단계 (QA-04 계획을 보완; 1·2단계는 QA-06에서 완료)

| 단계 | 내용 | 중단 조건 | 롤백 |
| --- | --- | --- | --- |
| 0. 직전 재확인 | revision `b8c01e2a4f60`, 렌더 0행, active 쿼리 0, 8000 PID·명령줄, 보호 테스트 해시. 직전에 백업을 다시 만들지 판단(데이터가 바뀌었으면 다시 만듦) | 하나라도 다름 | 없음 |
| 3. 조작 중지 | React·Streamlit 렌더·처리 조작 중지를 공지하고 활성 작업 0을 확인 | 활성 작업 존재 | 중지 해제 |
| 4. migration | `POSTGRES_PORT=5432` 등을 명시해 `alembic upgrade e3a1c9d27b45`. revision, 컬럼 3개 nullable, CHECK 3개, 16개 테이블 행 수가 0단계와 같은지 확인 | 오류, 행 수 변화 | 렌더 0행이면 `alembic downgrade b8c01e2a4f60`. 그 밖의 경우 `db.dump`로 복원(별도 승인) |
| 5. 8000 재시작 | 대상 PID 확인 → 종료 → 런처로 기동 → `/health` 200, `/projects` 13건, `/rendering`에 `integrity_status` | 시작 가드 오류, health 실패, 포트 점유 | 아래 "실패 시 복구" |
| 6. 실제 검증 | 승인한 QA 프로젝트 1건만 실제 렌더 → DB 해시 3개와 파일 SHA-256 일치 → 두 MP4 다운로드·Range·Chrome 미리보기 → 8000 재시작 후 같은 검사 | 해시 불일치, 비완료, 다운로드 오류, 다른 프로젝트 변화 | QA 렌더 행·파일은 보존(삭제 금지), 조작 중지 유지, 원인 조사 |
| 7. 사후 확인 | 인벤토리 27개 동일, PG localhost 게시, 보호 테스트 해시, 격리 복원 DB 삭제 승인, 문서 갱신 | 불일치 | 원인 조사, 백업 기준 복구(승인) |

### 실패 시 복구

- **migration 실패:** Alembic은 PostgreSQL에서 트랜잭션 DDL로 실행되므로 revision이 `b8c01e2a4f60`에 남는다. 그대로 두고 8000(이전 코드)을 계속 운영한다. 재시작 전이므로 서비스 영향이 없다.
- **migration 성공 후 이상(행 수 변화 등):** 렌더 0행이 유지되면 `downgrade b8c01e2a4f60`을 실행한다. 이 경로는 격리 DB에서 무손실로 검증했다. 그렇지 않으면 백업 해시를 확인하고 승인을 받아 `db.dump`로 복원한다.
- **새 코드 기동 실패:**
  - 이전 코드는 실행 중인 8000 프로세스의 메모리에만 있다. 작업 트리에는 이미 QA-03 코드가 있고 커밋도 되어 있지 않다. 따라서 8000을 종료하면 "이전 코드로 재기동"은 불가능하다.
  - 시작 가드 오류라면 4단계 결과(컬럼)를 다시 확인한다.
  - 원인이 바로 해결되지 않으면, 영속 모드를 끄고(`CUTORY_RENDER_PERSISTENCE_ENABLED` 미설정, 메모리 렌더 레지스트리) 같은 런처 방식으로 임시 기동하는 축소 운영을 고려한다. 이 경우 렌더 기록이 재시작 후 사라지는 WEB-08B 이전 동작이 되므로 승인 사항이다.
- **공통:** 렌더 기록과 파일을 삭제하지 않고, 해시를 수동으로 등록하지 않는다. 격리 복원 DB는 비교용으로 보존한다.

## 4. 판정: 준비 게이트 PASS → 실제 적용 권장(승인 필요)

근거:

- 백업이 유효하고 실제로 복원돼 개발 DB와 같았다.
- 실제 데이터 사본에서 migration이 무손실이고, 되돌리기도 검증했다.
- 새 코드가 실제 데이터 사본으로 기동했고 기존 조회 API가 모두 200이었다.
- 재시작 런처를 실제 프로세스로 시험 기동했다.
- 렌더 기록이 0건이라 승인 정책 1(과거 기록 차단)에 해당하는 기록이 없다.
- QA-05까지 회귀 0 실패다.

주의:

1. 8000을 끄면 이전 코드로 돌아갈 수 없다. 5단계 실패 시 대안은 축소 운영 또는 원인 수정이다.
2. 재시작 중 tailnet·React 사용자 요청이 실패한다.
3. 6단계 실제 렌더에 쓸 QA 프로젝트를 승인 때 지정해야 한다.

## 보호 조건 준수

- 개발 DB는 읽기만 했다(`pg_dump`, `SELECT`, 읽기 전용 세션). revision·행 수가 작업 전후 같다.
- 8000·Vite·Tailscale 재시작 없음. 8009 시험 프로세스는 내가 띄운 것만 종료했다.
- 원본·렌더 27개 파일의 크기·SHA-256·mtime이 작업 전후 같다.
- 보호 테스트 3개와 미커밋 변경을 보존했다. Git commit·Push 없음.
- 격리 데이터 분리: 복원과 migration은 55432의 `cutory_qa06_` DB에서만 했다. 시험 앱은 연결 대상을 단언해 55432에만 연결했고, 런처 시험 기동도 격리 DB 환경으로만 했다.

## 산출물 (Git 제외 `temporary/qa06-rollout-20261103/`)

- `db.dump`, `db.dump.sha256`, `pg_restore-list.txt`
- `file-inventory-before.json`
- `env-8000-observed.json`
- `isolated-restore-check.json`
- `restore_check.py`, `inventory.py`
- `start_fastapi.py`

---

# 보강 (2026-11-03): 8000 종료 전 서버 복구 경로 확보

사용자는 위 준비 결과를 확인했으나, 8000을 끄면 기존 서버를 같은 방식으로 되살리기 어렵다는 위험 때문에 실제 적용을 보류했다. 이 보강은 그 위험을 해소하기 위한 검증이다. 실제 개발 DB migration, 8000·5173·Tailscale 재시작, 사용자 파일 변경, 커밋·Push는 하지 않았다.

## A. 현재 8000의 코드와 실행 환경

**코드 버전: "HEAD + 세션 시작 시점의 미커밋 변경"이며, HEAD만으로는 재현할 수 없다.**

| 근거 | 결과 |
| --- | --- |
| 기동 시각 | PID 35472, 2026-11-03 12:48:47, `--reload` 없음 |
| 이후 코드 변경 | 12:48:47 이후 수정된 `backend/`·`frontend/` 파일은 18개이며, 모두 이 세션(QA-03~05)에서 16:45 이후에 바꾼 것이다. 12:48~16:40에 바뀐 파일은 문서·평가 캡처뿐이다. 세션 시작(16:40)에 저장한 기준 스냅샷(`git diff` 및 상태 목록)이 곧 8000 기동 시점의 코드다 |
| HEAD만으로 재현 | 불가. HEAD `1a2d7d7`에는 WEB-08B(`project_render_runs`, 영속 레지스트리, b8 migration)와 DEV-01·장면 복구 변경이 없다. 이것들은 미커밋 상태다 |
| 지문 대조 | 실행 중인 8000의 `GET /openapi.json`(읽기 전용)이 재구성한 기존 코드 트리의 스키마와 **완전히 같다**(`1dd5f203…`). 현재 작업 트리(`5cef3864…`)와는 다르며, 차이는 `ProjectRenderingStatusResponse`의 무결성 필드 3개뿐이다 |
| 실행 환경 | QA-06 1장과 같다. 영속 모드 1, 번들 FFmpeg PATH, LLM 키 빈 값, `.env`의 5432/`cutory`. **`CUTORY_SUBTITLE_FONT_PATH`는 없다.** 그래서 현재 8000은 하드 자막 MP4를 만들지 않는다(`NOT_CONFIGURED`). 10-24~10-26 렌더 5건에는 `final-subtitled.mp4`가 있어, 이전 기동에는 글꼴이 설정돼 있었다. 12:48 재기동 때 빠진, 기존부터 있던 설정 차이다 |

한계: 지문 대조는 API 표면이 같다는 것까지만 보장한다. 함수 내부까지 같다는 근거는 수정 시각과 스냅샷 대조다. 8000이 16:45 이후 처음 지연 import한 모듈이 있었다면 그 모듈만 새 코드일 수 있다. 다만 OpenAPI가 기존과 같아 라우터 계층에서는 그런 흔적이 없다.

## B. 기존 코드 상태의 재구성과 보존

재구성 방법(저장소 밖 scratchpad에서 실행):

1. `git archive HEAD`로 HEAD를 꺼낸다.
2. 기준 diff(추적 파일 13개)를 적용한다.
3. 세션 시작 때의 미추적 백엔드 파일을 복사한다.
4. 그중 이 세션이 고친 3개(`models/render.py`, `persistent_render_execution.py`, `test_qa01_render_recovery.py`)는 원래 내용으로 복원한다. 복원은 두 가지 독립 방법으로 했다.
   - (가) 대화 기록에서 성공한 Edit만 골라 역순으로 되돌렸다(Edit 2·4·3개가 모두 정확히 1회 일치).
   - (나) 수정 전에 읽어 둔 원문(Read·cat 출력)과 비교했다. 3개 모두 **일치**했다.

검증: 재구성 트리와 현재 트리의 차이는 **이 세션이 바꾼 12개 파일 + 새로 만든 7개 파일**과 정확히 같다. 나머지 161개는 동일하다.

중간 실수와 정정: 처음에는 저장소 하위 폴더(`temporary/`)에서 `git apply`를 실행했다. 이 경우 Git이 범위 밖 경로의 패치를 **조용히 건너뛰어** 미커밋 변경이 빠진 트리가 만들어졌다. 실제 저장소는 바뀌지 않았다(보호 해시와 수정 시각 확인). 그래서 저장소 밖에서 다시 만들었다.

보존 자산(Git 제외 `temporary/qa07-recovery/`):

| 자산 | 내용 |
| --- | --- |
| `old-tree/` + `old-tree.sha256` | 8000과 같은 기존 코드 트리(280개 파일). 정리 후 다시 해시해도 매니페스트와 일치 |
| `current-worktree-20261103.tar` (+`.sha256`, `.HEAD`) | 현재 작업 트리 전체(Git 무시 규칙 적용, `.env`·원본·출력·`temporary` 제외, 379개 파일). SHA-256 `6477af57…`. 저장소 밖에 풀어 379개 모두 바이트 일치 확인 |
| `current-tracked-20261103.diff` | 추적 파일의 현재 `git diff --binary HEAD` |
| `start_server.py` | 복구·적용 겸용 런처 |
| `openapi-8000-observed.json` | 8000 지문 |
| `probe.py`, `render_scenario.py`, `reverse_edits.py`, `method_b.py` | 검증 스크립트 |

Git stash·브랜치·커밋은 쓰지 않았다. `.git`과 작업 트리에는 아무것도 쓰지 않는다.

## C. 복구 런처 `temporary/qa07-recovery/start_server.py`

```
<base python> temporary/qa07-recovery/start_server.py --code-root <트리> --data-root <데이터> --port <n> [--subtitle-font <otf>] [--isolated]
```

- `--code-root`
  - 기존 코드: `temporary/qa07-recovery/old-tree`
  - 새 코드: 저장소 루트
- `--data-root`: `.env`, `storage/originals`, `temporary`, `outputs/projects`, `uploads`, `outputs/api`의 기준 위치. 실제 복구 때는 저장소 루트를 쓴다.
  - `PROJECT_ROOT`가 코드 위치에서 계산되므로, 런처가 기동 전에 `config.DOTENV_PATH`, `main.PRODUCT_*`/`PROJECT_RENDER_OUTPUT_DIRECTORY`, `videos.UPLOAD_DIRECTORY`/`PROCESS_OUTPUT_DIRECTORY`를 데이터 루트로 바꾼다. 이 값들은 모두 실행 시점에 읽히는 전역 변수다(코드 확인).
- 환경: 영속 모드 1, 번들 FFmpeg PATH, LLM 키 빈 값. 글꼴은 `--subtitle-font`를 줄 때만 설정한다(기본은 현재 8000처럼 미설정).
- `--isolated`(리허설 전용): 55432의 `cutory_qa07_*` DB와 `temporary/` 아래 데이터 루트가 아니면 기동을 거부한다.
- `.venv` 런처가 Codex 밖에서 동작하지 않으므로 base 인터프리터와 `.venv` site-packages를 쓴다.

## D. 격리 복구 리허설 (실제 개발 DB·사용자 파일 접근 없음)

모든 리허설은 격리 컨테이너 55432의 일회용 DB와 `temporary/` 아래 빈 폴더에서만 했다. 실데이터 사본 DB에는 합성 데이터를 넣지 않았다(렌더 시나리오는 합성 전용 DB 사용).

| # | 시나리오 | DB | 결과 |
| --- | --- | --- | --- |
| R1 | 기존 코드 + b8 (현재 8000 재현) | QA-06 덤프 복원본 | 기동 2.4~2.6초(STT 모델 포함). 프로젝트 13, 조회 65건 200. OpenAPI가 8000과 **같음** |
| R2 | migration 실패 | 같은 복원본, 기존 서버 가동 중 | 다른 세션이 `project_render_runs`에 ACCESS SHARE 잠금을 건 상태에서 `PGOPTIONS=-c lock_timeout=3s`로 upgrade → `LockNotAvailable`. revision b8 유지, 해시 컬럼·CHECK 0개(부분 적용 없음). 기존 서버는 계속 응답 |
| R3 | migration 성공 후 새 서버 기동 실패 | 같은 복원본(e3) | 새 코드가 포트 점유로 기동 실패(exit 3). **경로 A:** DB를 e3로 둔 채 기존 코드 기동 → 정상, OpenAPI 8000과 같음. **경로 B:** 렌더 행 0·해시 0 확인 → downgrade b8 → 기존 코드 기동 → 정상. 이 과정을 거친 뒤에도 16개 테이블 353행의 행 수·md5가 QA-06 개발 DB 사본과 같음 |
| R3' | 새 코드 + b8 | 같은 복원본 | 시작 가드가 거부: `RuntimeError: …render digest migration (e3a1c9d27b45)` |
| R3'' | 새 코드 + e3, 같은 런처 | 새 복원본 | 기동 2.6초, 조회 65건 200, `integrity_status` 포함, OpenAPI가 현재 코드와 같음 |
| S0~S1 | 기존 코드 렌더 (b8) | 합성 전용 | COMPLETED, 다운로드 200 |
| S2~S3 | migration 후 새 코드 | 합성 전용 | 기존 코드가 만든 렌더는 `UNVERIFIED`·409 (승인 정책 1과 일치) |
| S4~S5 | 새 코드 렌더 성공·실패 | 합성 전용 | 성공: `VERIFIED`, 200. 실패: FAILED 기록, 이전 성공 렌더는 계속 제공(롤백 불필요) |
| S6~S8 | 회귀 시 기존 코드로 운영 (e3) | 합성 전용 | 기존 코드가 e3에서 정상 동작하며, 모든 COMPLETED를 무결성 검사 없이 제공한다. 이 기간의 렌더는 해시가 NULL이라 새 코드로 돌아오면 `UNVERIFIED` 차단 |
| S9~S10 | 해시가 있는 상태에서 downgrade | 합성 전용 | 해시 컬럼이 삭제돼 **해시가 영구 소실**된다. 재upgrade 후 정상이던 `VERIFIED` 렌더도 `UNVERIFIED`로 차단 → **데이터 손실** |
| RR | 기존 코드 실제 FFmpeg 렌더 (복구 런처) | 합성 전용(b8) + 합성 원본 | 처음에는 `SEGMENT_RENDER_FAILED`였다. 원인은 리허설 폴더가 깊어 세그먼트 경로가 261~265자로 Windows 260자 한도를 넘은 것이다. 실제 운영 경로는 같은 계산으로 226자다. 짧은 폴더로 다시 실행하니 COMPLETED(2.1초), MP4·SRT, 다운로드 200 해시 일치, Range 206 일치. 글꼴 미설정이면 하드 자막 `NOT_CONFIGURED`(현재 8000과 같음). `--subtitle-font`(SHA-256 `6bcb2a07…`)를 주면 하드 자막 MP4 2,209,523 B 다운로드 200. 서버 재시작 후에도 이력 3건 유지, 두 MP4 다운로드 바이트 일치 |

리허설 DB 5개는 모두 삭제했고, 합성 데이터 폴더도 삭제했다. 남은 격리 DB는 QA-06 복원본 1개다.

### DB revision 호환성 행렬

| | b8 DB | e3 DB |
| --- | --- | --- |
| 기존 코드(8000) | 정상 (현재 운영) | 정상 동작. 단 새 렌더의 해시가 NULL이고, 해시가 있는 렌더도 검증 없이 제공 |
| 새 코드 | **기동 거부**(시작 가드) | 정상 (적용 목표) |

따라서 migration은 8000을 끄지 않은 채 먼저 적용할 수 있다(기존 코드가 e3에서 동작). 8000 교체가 실패해도 DB를 되돌리지 않고 기존 코드로 복구할 수 있다.

## E. 확정한 적용 절차와 상황별 복구

전제:
- 작업 창 동안 React·Streamlit 렌더 조작을 중지한다.
- 모든 alembic 명령에 `PGOPTIONS=-c lock_timeout=5s`를 붙여 잠금 대기로 서비스가 멈추지 않게 한다.
- 8000 종료와 기동은 명령줄을 확인한 대상만 한다.

적용 순서:

1. 직전 확인(revision b8, 렌더 0, active 0, 8000 PID와 OpenAPI 지문 = `1dd5f203…`).
2. 새 백업을 만든다(`pg_dump -Fc`, 해시, `pg_restore -l`).
3. **8000을 켜 둔 채** `alembic upgrade e3a1c9d27b45`를 실행한다.
4. 8000을 종료한다.
5. `start_server.py --code-root <repo> --data-root <repo> --port 8000`(+글꼴 결정에 따라 `--subtitle-font`)로 새 코드를 기동한다.
6. 승인한 QA 프로젝트 1건으로 실제 렌더를 검증한다.
7. 사후 확인을 한다.

### 상황 1. migration 실패

- **증상:** alembic 오류(잠금 시간 초과 등).
- **자동 조치:** 없음. 트랜잭션 DDL이 롤백된다(R2). 8000은 아직 기존 코드로 실행 중이라 서비스 영향이 없다.
- **확인:** revision이 `b8c01e2a4f60`이고 해시 컬럼·CHECK가 0개인지 확인한다.
- **중단·보고:** revision이 b8도 e3도 아니거나 일부 컬럼만 남은 경우. 이때는 손으로 고치지 않는다.
- **재시도:** 잠금 원인(장기 쿼리)을 확인한 뒤 승인을 받아 재시도한다.

### 상황 2. migration 성공 후 새 FastAPI 기동 실패

- **즉시 복구(경로 A, 데이터 손실 없음):** 실패한 프로세스를 정리한 뒤, 같은 런처로 `--code-root temporary/qa07-recovery/old-tree --data-root <repo> --port 8000`을 실행한다. DB는 e3 그대로 둔다. 리허설에서 2~3초 만에 복구됐다(R3 경로 A).
- **기존 서버로 운영하는 동안:** 렌더 조작 중지를 유지한다. 이 기간에 렌더하면 해시가 NULL이라 새 코드로 돌아온 뒤 차단된다.
- **선택 조치(경로 B):** 렌더 행 수와 해시 값이 채워진 행이 모두 0이면 `downgrade b8c01e2a4f60`로 원래 상태로 되돌릴 수 있다(손실 없음, R3 경로 B). 0이 아니면 하지 않는다.
- **원인 조사:** 로그, 시작 가드, 포트, 의존성을 조사한 뒤 재시도를 승인받는다.

### 상황 3. 새 FastAPI는 기동했으나 실제 렌더 실패

- **롤백하지 않는다.** 실패는 FAILED로 기록되고, 이전 기록과 파일은 그대로 남는다(S5). 다른 기능은 새 코드로 계속 운영한다.
- **보존:** QA 렌더 행과 파일을 삭제하지 않는다. 렌더 조작 중지를 유지한다.
- **원인 분류:** 환경(FFmpeg PATH, 글꼴, Docker, 경로 길이) 또는 코드. 이번 리허설에서 경로 길이 한도도 실제 원인이 될 수 있음을 확인했다. 운영 경로는 226자로 여유가 34자뿐이다.
- **코드 결함이 확인되면:** 상황 4를 따른다.

### 상황 4. 적용 후 기존 기능 회귀 발견

- **기존 코드로 전환(DB 유지):** 8000을 기존 코드로 다시 띄운다(상황 2 경로 A와 같음). e3에서 정상 동작한다(S6). 단 무결성 차단이 꺼지고, 이 기간의 새 렌더는 해시 없이 기록된다.
- **downgrade 자동 실행 조건:** 해시 값이 채워진 행이 0일 때만 한다.
  - 1행 이상이면 downgrade가 해시를 영구 삭제한다(S9~S10에서 확인). 그 렌더들이 이후 `UNVERIFIED`로 차단되므로 **실행하지 않고 중단 후 보고한다.**
- **백업(`db.dump`) 복원:** 백업 이후 생긴 모든 기록(새 렌더, 처리 결과)이 사라지므로 **자동 실행하지 않는다.** 사용자 승인과 손실 범위 보고가 먼저다.
- **파일:** 렌더·원본 파일은 어떤 경우에도 삭제하거나 옮기지 않는다.

## F. 판정: 실제 적용 승인 가능 (조건부)

8000을 꺼도 복구할 수 있다는 근거:

1. 8000의 코드를 재구성해 보존했고, OpenAPI 지문이 일치한다.
2. 같은 런처로 기존 코드를 기동했고, 실데이터 사본에서 조회 API가 모두 200이었다.
3. 영속 모드에서 실제 FFmpeg 렌더, 재시작 후 이력 유지, 다운로드·Range가 동작했다.
4. migration 실패, 새 서버 기동 실패, 렌더 실패, 회귀 각 상황의 복구를 격리 환경에서 시험했다.
5. 기존 코드는 e3 DB에서도 동작하므로 복구에 DB 되돌리기가 필요 없다.
6. 현재 작업 트리 전체 스냅샷을 바이트 단위로 복원 검증했다.

남은 조건:

1. **글꼴 결정:** 현재 8000은 글꼴 없이 실행 중이라 하드 자막 MP4를 만들지 않는다. 적용 후 6단계에서 하드 자막까지 검증하려면 `--subtitle-font evaluation/tmp/subtitle-font/NotoSansCJKkr-Regular.otf`(10-26 이전 동작 복원)가 필요하다. 현재 8000과 동작이 달라지므로 사용자 결정 사항이다.
2. 실제 데이터 루트(저장소)와 개발 DB로 런처를 실행하는 조합은 8000을 끄지 않고는 시험할 수 없다. 리허설과 다른 점은 데이터 루트와 DB 주소뿐이고, 운영 경로 길이는 226자로 한도 안이다.
3. 작업 창 동안 렌더 조작 중지, `lock_timeout` 사용, 상황별 "중단 후 보고" 규칙을 지킨다.
4. 6단계용 QA 프로젝트를 지정해야 한다.

## 보호 조건 (보강 작업)

- 개발 DB: 이번 보강에서는 접속하지 않았다. 마지막 확인만 읽기 전용으로 했고 revision b8, 프로젝트 13, 렌더 0, 5432 localhost 게시 유지.
- 8000(PID 35472)·5173(PID 41712)·Tailscale(Running): 그대로. 내가 띄운 8009·8010·8011 프로세스만 명령줄을 확인한 뒤 종료했다.
- 사용자 파일: 리허설에서 접근하지 않았다. 최종 보호 확인으로만 27개를 읽어 해시했고, 크기·SHA-256·수정 시각이 QA-06 인벤토리와 같다.
- 보호 테스트 3개, 미커밋 변경: 동일(git status 차이는 QA-06 handoff 추가뿐). 커밋·Push 없음.
