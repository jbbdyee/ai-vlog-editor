# 정지 스크립트 `stop_server.py` WinError 6 수정 (2026-11-06)

상태: **구현·격리 검증 완료. 실제 8000 정지는 미검증**(운영 서버를 멈추지 않는 조건이라 실행하지 않음). 스크립트는 Git 제외 `temporary/qa07-recovery/`에 있다. 커밋 없음.

## 증상
2026-11-05 14:31 VLM 상태 복원 반영 때 `stop_server.py --pid 49648`이 Ctrl+Break를 보내 서버를 정상 종료시킨 뒤, 자체 포트 재확인 단계에서 `OSError: [WinError 6] 핸들이 잘못되었습니다`로 끝났다(exit 1). 서버 정지에는 영향이 없었다.

## 원인 (격리 재현으로 확인)
- 대상 콘솔에 신호를 보내려고 스크립트 **자기 프로세스**에서 `FreeConsole` → `AttachConsole(대상)` → 신호 → `FreeConsole`을 했다.
- `AttachConsole`은 호출 프로세스의 표준 핸들이 콘솔·NUL 같은 문자 장치일 때 세 표준 핸들을 대상 콘솔 핸들로 바꾼다. 마지막 `FreeConsole` 뒤 이 핸들은 무효가 된다.
- 이후 `subprocess.run(powershell …)`이 표준 입력 핸들을 복제하다 `DuplicateHandle` 실패 → WinError 6. Python `print`는 시작 때 잡은 파일 기술자를 써서 이번에는 출력됐다.
- 호출한 셸에 따라 달라진다: stdin이 **파이프**(이전 Bash 실행)면 핸들이 바뀌지 않아 재현되지 않는다. stdin이 **NUL/콘솔**(14:31의 PowerShell 실행, 실제 터미널 창)이면 발생한다. 핸들 진단 결과: `attach` 뒤 in/out/err가 문자 장치로 바뀌고 `FreeConsole` 뒤 모두 invalid, 기본 `subprocess`는 `OSError 6`, `stdin=DEVNULL`은 성공.
- 실제 터미널 창에서 실행하면 출력 핸들도 무효가 되어 종료 시 출력 flush 실패(exit 120)도 생긴다(격리 재현).

## 수정 (최소 범위, `temporary/qa07-recovery/stop_server.py`)
- 콘솔 연결·신호·분리를 **짧게 실행되는 도우미 자식 프로세스**(같은 파일, 내부 인자 `--send-event`, `DETACHED_PROCESS`로 콘솔 없이 시작, 표준 입출력은 DEVNULL·파이프)로 옮겼다. 본 프로세스는 자기 콘솔을 분리하지 않는다.
- 순서는 그대로: 포트 소유자·명령줄·활성 작업 확인 → Ctrl+C 무시 여부 판단 → 도우미가 콘솔 단독 여부 확인 후 신호 1회 → 본 프로세스가 최대 60초 종료 대기 → 포트 재확인.
- 도우미가 거부(콘솔 공유 등, exit 2)하거나 신호 호출이 실패(exit 4)하면 대상은 그대로 두고 같은 코드로 끝낸다. 재시도·강제 종료 없음.
- `ps()`도 `stdin=DEVNULL`로 호출(표준 핸들 상태와 무관).
- 수정 전 사본: `stop_server.py.bak-20261105`(SHA-256 `16384840…11b9`). 수정 후 SHA-256 `0c5bc4e3…0a3d`.

## 검증 (격리, 포트 8099 더미 서버만 — Cutory 아님)
더미는 별도 숨김 콘솔의 FastAPI(`/health`, 빈 `/projects`)이고, 종료 시 lifespan 종료 로그를 남긴다.

| 경우 | 수정 전 사본 | 수정 후 |
| --- | --- | --- |
| PowerShell 직접 실행(14:31과 같은 방식) | WinError 6, exit 1 | exit 0, 정상 종료 로그, 포트 비움 |
| stdin = 파이프(Bash 방식) | exit 0 | exit 0 |
| 새 콘솔, stdin = 콘솔(출력은 파일) | WinError 6, exit 1 | exit 0 |
| 새 실제 콘솔(모든 입출력 콘솔) | exit 120(출력 flush 실패) | exit 0 |
| 대상이 Ctrl+C 무시 → auto | Ctrl+Break, exit 0 | Ctrl+Break, exit 0 |
| 대상이 Ctrl+C 무시 + `--signal ctrl-c` | 거부 exit 2, 대상 유지 | 거부 exit 2, 대상 유지 |
| 대상 콘솔을 다른 프로세스와 공유 | 거부 exit 2 | 도우미 거부 exit 2, 대상 유지 |
| PID가 포트 소유자와 다름 | 거부 exit 2 | 거부 exit 2 |

- 모든 경우 수정 후 WinError 6 0건. 검사 전후 8000(55828)·5173(41712)·8001(4052) PID 동일, 8099 비어 있음. 거부 경우에 남은 더미는 테스트 도구가 정리했다(더미만).
- 정적 확인: `py_compile` 통과, diff는 위 범위만.

## 미검증·남은 위험
- **실제 8000 정지에는 아직 쓰지 않았다**(운영 중단 금지 조건). 다음 승인된 재시작 때 처음 실사용된다. 그때 출력의 `helper: event 1 sent=True`·`exited=True`·`listener after stop: none`을 확인한다.
- 내부 인자 `--send-event`를 사람이 직접 주면 포트·명령줄·활성 작업 검사를 건너뛰고 콘솔 단독 검사만 한다. 도움말에 숨겼지만 직접 사용하지 말 것.
- 활성 작업 검사는 처리·장면 분석·렌더만 본다. **VLM 분석(`/scene-vision` QUEUED·RUNNING)은 검사하지 않는다**(14:31에는 별도 GET으로 확인). 이번 범위 밖, 후속 보완 후보.
- 스크립트는 이 PC 경로·Git 제외 위치에 있어 다른 PC 재현성은 없다.
