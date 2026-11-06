# n8n 렌더 이벤트 1단계 실제 검증 (2026-11-06)

범위: 격리 Docker Compose 프로젝트로 n8n을 띄우고 **합성 이벤트만** 보냈다. Cutory 8000과 연동하지 않았다(재시작·`.env` 변경·실제 이벤트 전송 없음). 실제 렌더·LLM·VLM 호출 없음. 설계·구현은 [n8n 설계와 구현](n8n-render-events-design-2026-11-06.md), 설치 방법은 [deploy/n8n/README](../../deploy/n8n/README.md).

## 환경

| 항목 | 값 |
| --- | --- |
| 이미지 | `n8nio/n8n:2.46.6@sha256:8602f5dfacbe2c931eeafd010de0e68182310e9f309921e780ab69182e92b3ae`. 2026-11-04 GitHub 최신 정식 릴리스 `n8n@2.46.6`, Docker Hub `stable` 태그와 같은 digest. 컨테이너 안 `n8n --version` 2.46.6, Node 26 |
| compose | `deploy/n8n/docker-compose.yml`, 프로젝트 `cutory-n8n`, 컨테이너 `cutory-n8n`, 네트워크 `cutory-n8n_default`(다른 컨테이너 없음), 볼륨 `cutory-n8n-home` → `/home/node`(ext4), `restart: "no"` |
| 포트 | `127.0.0.1:5678`만. task broker 5679는 컨테이너 내부 127.0.0.1 |
| 실행 모드 | task runner internal 모드(2.x 기본). 시작 로그에 internal 모드 deprecated 경고, Python runner 없음 경고(JS만 사용하므로 영향 없음) |
| 자격증명 | Header Auth `Cutory render webhook (test)`. 테스트용 64자 무작위 토큰(Git 밖 임시 파일, 출력 안 함). CLI `import:credentials`로 등록, n8n DB에는 암호화 저장 확인 |
| 워크플로우 | CLI `import:workflow` → 자격증명 연결 → `publish:workflow` → 재시작 후 활성. ID `UEFP5G8cPLVs26t7` |
| 소유자 계정 | **미생성.** CLI로 import·활성화가 가능해 필요하지 않았다. UI는 소유자 설정 화면 상태 |

작업 전후 기존 컨테이너 11개(Cutory postgres 2, ai-baby-care 9)의 기동 시각·재시작 횟수 동일. 8000(PID 55828, health 200)·8001(4052)·5173(41712)·5432 그대로. `temporary/render-events` 미생성.

## 발견·수정한 문제

첫 실행에서 유효한 이벤트가 모두 `500 Error in workflow`. 원인은 n8n 2.x task runner 샌드박스에 `process` 전역이 없는데 Code 노드 JS가 임시 파일 이름에 `process.pid`를 쓴 것(`ReferenceError: process is not defined`). `require('fs')`·`require('path')`는 정상 동작했다.

- `record-render-event.js`: 임시 파일 이름을 `Date.now()` + 난수 두 개로 바꿨다. 충돌해도 `wx` 플래그가 거부하므로(500 → Cutory 재시도) 덮어쓰지 않는다. 우회가 아니라 불필요한 전역 의존 제거.
- `check-record-render-event.mjs`: 샌드박스와 같게 `process`를 숨기고 `require`를 `fs`·`path`만 허용. 예전 코드로 돌리면 exit 1로 실패하는 것을 확인했다.
- 워크플로우 JSON 재생성(`build_workflow.py --check` 통과), 재import·재게시, 백엔드 `test_render_events` 27건 OK.

## 기능 확인 (실제 n8n, 합성 이벤트)

`deploy/n8n/check-live-n8n.py before` 17/17, `after` 4/4(재시작·재생성 각각). 수정 후 두 번 실행해 같은 결과.

| 항목 | 실제 HTTP | 저장 결과 |
| --- | --- | --- |
| 인증 헤더 없음 / 틀린 토큰 | 403 `Authorization data is wrong!` | 파일 없음, 실행 이력도 생기지 않음 |
| 정상 `COMPLETED` | 200 `recorded` | 응답을 받은 직후 컨테이너 안 파일이 이미 존재, 429바이트, 고정 키 순서 기록과 바이트 일치 |
| 같은 본문 재전송 | 200 `duplicate` | 파일 1개 유지 |
| 같은 ID·다른 본문(`file_size_bytes`) | 409 `conflict` `EVENT_CONTENT_MISMATCH` | 기존 파일 바이트 불변 |
| 필드 추가 / ID 불일치 | 400 `FIELDS` / 400 `EVENT_ID` | 기록 없음 |
| JSON 아님 | 422(n8n Webhook 노드가 응답) | 기록 없음. Cutory는 4xx라 재시도 안 함 |
| `FAILED` / `RECONCILIATION_REQUIRED` | 200 `recorded` | 각각 기록 일치 |
| 같은 이벤트 8건 동시 | 모두 200, `recorded` 1·`duplicate` 7 | 파일 1개, 임시 파일 0 → hard link(`linkSync`) 지원 확인 |
| 최종 경로를 막아 기록 실패 유도 | 500 `RECORD_WRITE_FAILED` | 200을 주지 않음. 막은 폴더는 확인 후 삭제 |
| Cutory `RenderEventDispatcher` 직접 사용(서버 아님) | `delivered`/200/`recorded` → `delivered`/200/`duplicate` | 전송 기록 2줄에 토큰·URL 없음 |
| `docker restart` 후 | 같은 본문 200 `duplicate`, 다른 본문 409, 인증 없음 403 | 기록 5개 유지 |
| `compose down` → `up`(컨테이너 재생성, 볼륨 유지) 후 | 같음 | 같음 |

기록 위치: 볼륨 안 `/home/node/.n8n-files/cutory-render-events/<event_id>.json`(소유자 `node`, `-rw-r--r--`). 합성 이벤트 기록 10개(검증 2회 × 기록된 이벤트 5개), 임시 파일 0개가 남아 있다. Cutory 실제 렌더 ID가 아니다.

## 비밀값 점검

| 위치 | 결과 |
| --- | --- |
| n8n 자격증명(`credentials_entity`) | 암호화 저장, 평문 토큰 없음 |
| 컨테이너 로그, `n8nEventLog*.log`, `config` | 토큰·`Bearer` 없음 |
| Cutory 전송 기록(JSONL) | 토큰·URL 없음 |
| Git·문서 | 토큰 없음(compose·워크플로우 JSON에 비밀값 없음) |
| **n8n 실행 이력(`execution_data`)** | **평문 토큰 있음.** Webhook 노드 출력에 요청 헤더 전체가 들어가 `authorization: Bearer <토큰>`이 그대로 저장된다. 확인 시점 37건 전부 |

실행 이력 보존 동작(2.46.6 기본값과 워크플로우 설정 확인):
- 워크플로우 설정 `saveDataSuccessExecution: "none"`은 동작한다. 성공 실행은 끝나자마자 삭제 표시(`deletedAt`)되지만, 실제 삭제는 `EXECUTIONS_DATA_HARD_DELETE_BUFFER` 1시간 뒤 15분 주기로 일어난다. 그 전까지 토큰이 DB에 남는다. 실제 삭제는 확인하지 않았다(미검증). SQLite 빈 페이지·WAL에 남는 바이트도 확인하지 않았다.
- `saveDataErrorExecution: "all"`이라 오류 실행은 기본 336시간(14일) 보존된다. 이번 오류 13건(`process` 버그, 12:20 KST)에 테스트 토큰이 남아 있다.
- 인증 실패 요청은 실행 이력을 만들지 않았다.

후속(같은 날): 저장 안 함·즉시 정리 설정을 적용하고 테스트 토큰을 교체했다. 이 1단계 토큰은 이제 403이다. → [보안 정리 기록](n8n-security-cleanup-2026-11-06.md)

결론: 테스트 토큰은 이 컨테이너 밖에서 쓰지 않는다. 실제 연동 때는 새 토큰을 만들고, 실행 이력 보존 방식을 먼저 정해야 한다(아래 승인 항목).

## 남은 위험·미검증

- 실행 이력의 토큰 평문 저장(위). 볼륨 접근 권한이 있으면 읽을 수 있다.
- n8n 소유자 계정이 없다. 이 PC에서 `127.0.0.1:5678`에 접속하는 누구나 소유자를 만들 수 있다. 단일 사용자 PC라 위험은 낮지만, 계속 둘 거라면 사용자가 직접 만들어야 한다.
- `NODE_FUNCTION_ALLOW_BUILTIN=fs,path`는 이 인스턴스의 모든 Code 노드에 적용된다. 컨테이너 안에서는 `/home/node` 전체(n8n DB 포함)를 Code 노드가 읽을 수 있다.
- task runner internal 모드는 n8n이 deprecated로 표시했다. 다음 메이저에서 external runner로 바꿔야 할 수 있다.
- Cutory 8000 연동(실시간 전송), 실제 렌더 E2E, 기존 완료 렌더 재전송(`--send`)은 미실행.

## 다음 단계 승인 필요

1. 실행 이력 정책 결정 — 예: 오류 실행도 `saveDataErrorExecution: "none"`(디버깅 정보 감소, 추적은 Cutory 전송 기록·n8n 컨테이너 로그로), 또는 `EXECUTIONS_DATA_MAX_AGE`를 짧게. 이번 테스트 실행 이력 정리 방법(볼륨 재생성 등)도 함께.
2. 실제 토큰 생성 → 실제 `.env`와 n8n 자격증명 교체(테스트 토큰 폐기).
3. n8n 소유자 계정 생성(사용자 직접, 선택).
4. 8000 재시작 1회와 실제 이벤트 전송 방식(기존 완료 렌더 4건 `--send` 또는 실제 렌더 1회).
5. 커밋.

현재 `cutory-n8n` 컨테이너는 실행 중이다. 정리하려면 `docker compose -f deploy/n8n/docker-compose.yml down`(볼륨 유지) 또는 `down -v`(볼륨 삭제, 기록·실행 이력 모두 삭제).
