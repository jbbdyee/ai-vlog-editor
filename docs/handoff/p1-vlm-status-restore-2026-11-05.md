# P1 VLM 실행 상태 재시작 후 복원 (2026-11-05)

상태: **완료.** 2026-11-05 14:31 승인된 8000 교체 1회로 반영(PID 49648→55828). migration·VLM/LLM 호출·재렌더·DB 쓰기·커밋 없음.

## 원인
- `backend/app/services/project_scene_vision.py`의 실행 상태는 프로세스 메모리 딕셔너리 `_runs`에만 저장된다.
- `vision_status()`는 메모리에 항목이 없으면 기본값 `VisionRun()`(`NOT_STARTED`, `total 0`)을 반환하고, DB를 조회하지 않았다.
- 화면 분석 결과는 `scene_evidence`에 `evidence_type='VLM_SCENE_CAPTION'`, `source_reference='vlm:<모델>:v0.2'`로 영속 저장된다. 실패 건수·오류 코드는 저장되지 않는다.
- 재현(실제 8000, GET만): 실사 데모 `4e096f2d…`의 활성 후보 8개 모두 `visual_caption`이 있으나 `/scene-vision`은 `NOT_STARTED`·`total 0`.

## 수정 (최소 범위)
- `vision_status(project_id, session_factory=None)`: 메모리 기록 우선(`state_source=PROCESS`). 없고 세션이 주어지면 `stored_vision_state()`로 DB 읽기 전용 복원(`state_source=DATABASE`).
- `stored_vision_state()`: 활성 후보(`active_candidate_ids`) 중 현재 모델(`CUTORY_VLM_MODEL`, 기본 `gemma3:4b`)의 결과가 있는 후보 수를 센다. POST 시작이 기존 결과를 건너뛰는 기준과 같다.
  - 전부 → `COMPLETED`, 일부 → `PARTIAL`(새 상태 값, 실패 기록이 없어 경고 완료로 단정하지 않음), 없음 → `NOT_STARTED`.
  - `failed=0`, `error_codes=[]`, `skipped=0`(복원 시 의미 없음).
- 라우터 GET이 세션 팩토리를 넘기고 스레드풀에서 실행. 응답에 `state_source` 필드 추가(기본값 `PROCESS`, 하위 호환). POST·React 코드는 변경 없음. React는 `NOT_STARTED`가 아니면 `모델 · 분석 captioned+skipped/total`을 표시하므로 복원 상태도 그대로 보인다.
- `vlm_scene_captioner.caption_reference` 공개 별칭 추가.

## 테스트
- `backend/tests/test_scene_vision.py::SceneVisionRestartRestoreTests` 7건: 저장 결과로 `COMPLETED` 복원(VLM 미호출·DB 행 수 불변), 결과 없음 `NOT_STARTED`, 일부 `PARTIAL`, 다른 모델·비활성 후보 결과 미집계, 재시작 후 POST 시작 시 기존 결과 건너뜀·VLM 0회·`PROCESS` 우선, 메모리 `FAILED`가 DB 상태로 덮이지 않음, 없는 프로젝트 404·DB 오류 비은폐.
- 수정 전 코드로 같은 7건 실행 시 5건 실패(나머지 2건은 기존에도 맞던 동작).
- 백엔드 전체 643건 OK, skip 36(skip은 통과 아님). 보호 테스트 3개 미변경.

## 실제 데이터 검증 (읽기 전용)
- 개발 DB에 `default_transaction_read_only=on` 연결로 `stored_vision_state()`를 직접 호출(앱 기동 없음).
- 결과: 14개 프로젝트 중 실사 데모 `COMPLETED` 8/8(`gemma3:4b`), 나머지 13개 `NOT_STARTED`. 실행 중 8000의 후보 API(GET)로 센 화면 설명 수와 일치(데모 8/8, 그 외 0).
- 전후 동일: revision `e3a1c9d27b45`, 행 수 프로젝트 14·후보 58·근거 201·편집 계획 6, 데모 렌더 디렉터리 파일 9개 SHA-256.

## 8000 반영 (2026-11-05 14:31, 승인 1회)
- 사전: 프로젝트 14개 처리·장면 분석·렌더·VLM 상태 GET 결과 활성 0, 8000 연결 0, DB 활성 쿼리 0, `run-8000.ps1 -CheckOnly` 통과(계정·allowlist·FFmpeg·Docker·글꼴·revision·Ollama).
- 정지: `stop_server.py --pid 49648`(Ctrl+C 무시 프로세스 → Ctrl+Break 1회) → 정상 종료(`Application shutdown complete`). 이후 스크립트의 포트 재확인 단계가 `OSError [WinError 6] 핸들이 잘못되었습니다`로 끝났다. 원인: 콘솔을 분리·재부착한 뒤 표준 핸들이 무효라 `subprocess.run(powershell…)`이 핸들을 복제하지 못함. 서버 정지 자체는 성공했으므로 재시도하지 않고 포트·PID를 직접 확인했다. 수정안: 재확인 단계를 콘솔 분리 전에 핸들을 고정하거나 `stdin=DEVNULL` 등으로 실행(미수정).
- 기동: `run-8000.ps1` 1회 → PID 55828, health OK. 중단 약 20초.
- 실제 API: 데모 `{"status":"COMPLETED","model":"gemma3:4b","total":8,"captioned":8,"skipped":0,"failed":0,"error_codes":[],"state_source":"DATABASE"}`. 나머지 13개 `NOT_STARTED`·`DATABASE`.
- 5173 Chrome `web/e2e-real/vlm-status.spec.ts` 2건 통과(비GET 0건): 데모 ‘gemma3:4b · 분석 8/8’, 캡션 없는 프로젝트는 기존 안내 문구. 캡처(데모만): `temporary/vlm-status-20261105/`.
- 보존: 재시작 전·후·브라우저 확인 후 DB 17개 테이블 491행 md5·revision·파일 40개 SHA-256·VLM 근거 8건·계획·렌더 VERIFIED·두 MP4 다운로드 해시·ETag 동일. 5173·8001·PostgreSQL·Ollama 미변경.

## 미완료·한계
- `stop_server.py` 종료 후 확인 단계 오류: 2026-11-06 수정·격리 검증, 실제 8000 정지 미검증 → [기록](stop-server-winerror6-2026-11-06.md).
- 재시작 전 실행의 실패 건수·오류 코드·지연 시간은 복원되지 않는다(DB에 없음).
- 서버가 VLM 실행 도중 종료되면 일부만 저장된 결과는 `PARTIAL`로 보인다. 다시 시작하면 남은 후보만 분석한다.
