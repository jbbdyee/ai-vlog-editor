# 8000 계획 재시작 후 데이터 영속성 검증·실행 절차 — 2026-11-05 (P0-5)

승인 범위: FastAPI 8000 계획 재시작 **1회**. migration·신규 렌더·VLM 재분석·LLM 호출·데이터 삭제·커밋·Push 없음. 5173·PostgreSQL·Ollama·Docker·8001·Tailscale·격리 DB는 건드리지 않았다.

## 재시작 전 점검 (모두 통과)

- 백업 `Cutory-Backups/backup-20261104-171428-after-render-a0984ae2`: 덤프 SHA-256 `2d8f4194…92d0` 재계산 일치, `restore-check.json` identical. 현재 `storage/`·`outputs/`·`uploads/` 파일 40개가 백업 매니페스트와 경로·크기·SHA-256까지 동일.
- 기존 8000 PID 13384: 계정 `Pro`, 실행 파일 uv CPython 3.12.15, 명령 `temporary/qa07-recovery/start_server.py --code-root <repo> --data-root <repo> --port 8000 --subtitle-font evaluation/tmp/subtitle-font/NotoSansCJKkr-Regular.otf --edit-provider ollama --edit-model gemma3:4b --vlm-model gemma3:4b --ollama-base-url http://127.0.0.1:11434`, 작업 디렉터리 저장소 루트. Codex 세션에서 기동돼 부모 프로세스는 없고 전용 콘솔(conhost)만 연결.
- 환경 변수(이름만 기록, 비밀 값 미기록): `CUTORY_RENDER_PERSISTENCE_ENABLED=1`, `CUTORY_EDIT_LLM_PROVIDER/MODEL`, `CUTORY_VLM_MODEL`, `OLLAMA_BASE_URL`, `CUTORY_SUBTITLE_FONT_PATH`, `.env` 유래 `POSTGRES_HOST/PORT/DB/USER/PASSWORD`·`*_MODEL`, `LANG/LC_ALL/LC_CTYPE=C.UTF-8`. PATH 앞쪽에 번들 FFmpeg 9.0.2와 Docker Desktop CLI. 외부 API 키는 런처가 비운다.
- 의존성: 글꼴 SHA-256 `6bcb2a07…e992a` 일치, Docker 엔진 29.9.2(`Pro` 계정), 하드 자막 고정 이미지 digest 캐시 존재, Ollama `/api/tags` 200·`gemma3:4b` 존재, DB revision `e3a1c9d27b45`.
- 작업·요청: 14개 프로젝트의 처리·장면 분석·렌더 활성 0건, DB active 쿼리 0, 8000에 연결된 Established TCP 0. 백엔드 코드는 13384 기동(11-04 06:03) 뒤 변경 없음(HEAD `e96652f`와 작업 트리 동일).

## 재시작

- 2026-11-05 09:57:28 `stop_server.py --pid 13384`: 포트·명령줄·활성 작업·콘솔 단독 여부를 확인한 뒤 해당 콘솔에만 Ctrl+C → 정상 종료, 포트 해제(강제 종료 없음).
- 09:57:34 `run-8000.ps1`: 사전 점검 7항목 통과 후 기동 → **새 PID 45336**, 09:57:40 health ok. 중단 시간 약 12초, 재시도 없음.
- 새 프로세스: 계정 `Pro`, 동일 명령줄·작업 디렉터리, CUTORY/POSTGRES/OLLAMA 값 동일, PATH 앞쪽 FFmpeg·Docker 동일, `C.UTF-8`, TEMP 동일. 로그 `temporary/qa07-recovery/logs/8000-20261105-095734.*.log`(Git 제외).
- 확인된 차이: 새 프로세스가 기동한 셸의 에이전트 세션 변수(`CLAUDE_CODE_*`, 메시징 토큰 포함)를 상속했다. 서버는 이 값을 쓰지 않고 로그·문서에 값을 남기지 않았다. 이후 기동부터 제외하도록 스크립트를 고쳤다(아래, 실제 기동으로는 미검증).

## 재시작 후 검증 (모두 재시작 전과 동일)

- health 200, 5173 `/api/health` 프록시 200(Vite PID 41712 유지), 8001 PID 4052 유지, 격리 DB 8개 유지.
- 렌더 `a0984ae2-6675-417b-8866-4283179cca04`: COMPLETED, 기본·SRT·하드 자막 무결성 VERIFIED, 하드 자막 AVAILABLE. 렌더 이력 동일.
- 다운로드: 기본 MP4 200 `video/mp4` 944,150 B `7cff1dae…5d80`, 하드 자막 MP4 200 982,536 B `5ab71461…731a`. 둘 다 ETag `"sha256-…"` 일치, 재시작 전 응답과 동일.
- VLM 근거: DB `VLM_SCENE_CAPTION` 8건(행 md5 동일), API 후보 8건의 화면 설명·분류 동일. 편집 계획 2장면(`f65a4a11…` → `4bc16945…`) 동일, 무효 후보 0.
- DB 전체: 17개 테이블 491행의 전 컬럼 md5가 재시작 전 스냅숏과 동일, revision `e3a1c9d27b45`. 파일 40개 SHA-256 동일. 즉 재시작은 데이터를 추가·변경하지 않았다.
- 한계: `/scene-vision` 실행 상태는 메모리 보관이라 `NOT_STARTED`로 초기화된다(저장 근거는 유지). 재시작 뒤 신규 렌더·분석은 하지 않았다.

## 실행·복구 절차 (Git 제외 `temporary/qa07-recovery/`)

| 파일 | SHA-256 | 상태 |
| --- | --- | --- |
| `run-8000.ps1` | `6178f1e3…7d47` | 기동 검증 완료(PID 45336). 세션 변수 제외 패치 후에는 `-CheckOnly`만 확인 |
| `stop_server.py` | `7e9df2db…6f93` | 정상 종료 검증 완료(PID 13384) |
| `start_server.py` | `269fdbb9…bbc` | 기존 런처, 변경 없음 |

1. 상태 확인(아무것도 바꾸지 않음): `powershell -NoProfile -ExecutionPolicy Bypass -File temporary\qa07-recovery\run-8000.ps1 -CheckOnly`
2. 정지(필요할 때만): `<uv python> -I temporary\qa07-recovery\stop_server.py --pid <8000 PID>`. 활성 작업·다른 프로세스와 콘솔 공유·포트 불일치 시 거부(exit 2), 60초 안에 종료하지 않으면 강제 종료 없이 보고(exit 3).
3. 기동: `powershell -NoProfile -ExecutionPolicy Bypass -File temporary\qa07-recovery\run-8000.ps1`. `Pro` 계정·포트 비어 있음·파일·글꼴 해시·Docker 엔진·이미지·DB revision·Ollama 모델 중 하나라도 실패하면 기동하지 않는다. 기존 서버를 대신 끄지 않으며 자동 재시도도 없다.
4. 기동 후: 위 재시작 후 검증 항목(health, 렌더 상태, 두 다운로드 해시·ETag, VLM·계획)을 확인한다.

- 실패 시 복구: stderr 로그로 원인을 확인한다. 같은 스크립트로 1회만 재기동하고 다른 설정으로 바꾸지 않는다. DB·파일은 재시작과 무관하며, 손상 시 위 증분 백업과 `backup-20261104-165721`의 `RESTORE.md` 순서로 격리 복원부터 한다.
- 자동 시작 서비스·작업 스케줄러·시스템 설정은 등록하지 않았다. 재부팅 후에는 Docker Desktop·DB 컨테이너·Ollama가 먼저 떠 있어야 하며 이 조건은 `-CheckOnly`가 확인한다. 재부팅 직후 실제 기동은 미검증이다.
- 스크립트는 이 PC의 절대 경로(`Pro` 계정, Codex 패키지의 uv Python)에 묶여 있고 Git 밖에 있다. 저장소로 옮기려면 경로 매개변수화가 먼저 필요하다.
