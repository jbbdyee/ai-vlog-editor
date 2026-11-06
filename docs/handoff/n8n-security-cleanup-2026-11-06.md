# n8n 실행 이력 토큰 노출 정리 (2026-11-06)

선행 기록: [n8n 1단계 실제 검증](n8n-live-stage1-2026-11-06.md). 범위: 격리 컨테이너 `cutory-n8n`(n8n 2.46.6, `127.0.0.1:5678`)의 설정 변경과 테스트 토큰 교체, 합성 이벤트 재검증. Cutory 8000·DB·Ollama·렌더 결과·실제 `.env`는 바꾸지 않았다. 볼륨 삭제·DB 직접 수정·운영 토큰 생성 없음.

## 문제

- **증상:** n8n 실행 이력(`execution_data`)에 Webhook 요청 헤더가 저장돼 `authorization: Bearer <토큰>`이 평문으로 남는다.
- **원인(2.46.6 소스 확인):**
  - 실행 데이터는 저장 설정과 관계없이 **실행 중에 먼저 DB에 기록된다.**
  - 실행이 끝나면 `execution-lifecycle-hooks.js`가 저장 여부를 판단한다. 저장하지 않는 경우 `deleteInFlightExecution`이 `deletedAt = 지금 − EXECUTIONS_DATA_HARD_DELETE_BUFFER`로 삭제 표시만 한다.
  - 실제 삭제는 정리 작업이 맡는다. 기본값은 15분 주기(`EXECUTIONS_DATA_PRUNE_HARD_DELETE_INTERVAL`)이고, 삭제 표시 후 1시간(`BUFFER`)이 지난 행이 대상이다.
  - 수동 실행에서 `manual=false`이면 `softDelete`(지금 시각으로 삭제 표시)한다.
  - 기존 워크플로우 설정은 `saveDataErrorExecution: "all"`이라 오류 실행이 14일(`EXECUTIONS_DATA_MAX_AGE` 336시간) 보존됐다.
- **결론:** 2.46.6에서는 "실행 데이터를 DB에 한 번도 쓰지 않는" 설정이 없다. 할 수 있는 최선은 실행이 끝난 뒤 데이터가 남는 시간을 줄이는 것이다.

## 적용한 설정

| 위치 | 설정 | 효과 |
| --- | --- | --- |
| 워크플로우 `settings`(`build_workflow.py` → JSON) | `saveDataSuccessExecution: "none"`, `saveDataErrorExecution: "none"`(기존 `"all"`), `saveManualExecutions: false`, `saveExecutionProgress: false` | 성공·실패·수동 실행 모두 저장 안 함, 노드별 중간 저장 안 함 |
| 인스턴스 기본값(`docker-compose.yml`) | `EXECUTIONS_DATA_SAVE_ON_SUCCESS=none`, `EXECUTIONS_DATA_SAVE_ON_ERROR=none`, `EXECUTIONS_DATA_SAVE_MANUAL_EXECUTIONS=false`, `EXECUTIONS_DATA_SAVE_ON_PROGRESS=false` | 워크플로우 설정이 빠지거나 다른 워크플로우가 생겨도 같은 기본값 |
| 정리 주기(`docker-compose.yml`) | `EXECUTIONS_DATA_HARD_DELETE_BUFFER=0`, `EXECUTIONS_DATA_PRUNE_HARD_DELETE_INTERVAL=1` | 삭제 표시된 실행을 1분 안에 실제 삭제(기본 1시간 + 15분 주기) |

- 환경 변수 이름은 컨테이너 안 `@n8n/config/dist/configs/executions.config.js`에서 확인했다.
- 수동 실행 데이터: 인스턴스 기본값은 원래 **저장(true)**이었다. 이번에 워크플로우·인스턴스 모두 false로 바꿨다. 실제 수동 실행은 UI(소유자 계정)가 필요해 하지 않았다(소스 확인만).
- `EXECUTIONS_DATA_MAX_AGE`(336시간)는 바꾸지 않았다. 따라서 과거 오류 실행 13건은 그대로다(아래 정리 방법 참고).
- `backend/tests/test_render_events.py`에 이 설정들과 `127.0.0.1` 포트 공개를 확인하는 계약 테스트 1건을 추가했다(28건 OK).
- compose 파일 앞의 UTF-8 BOM(이전 PowerShell 편집 흔적)을 제거했다.

## 테스트 토큰 교체

- 무작위 64자 새 테스트 토큰을 만들어 같은 자격증명 ID(`CutoryRenderHdr1`)에 CLI로 다시 등록했다. 값은 출력하지 않았다.
- 워크플로우를 다시 import·게시하고 컨테이너를 재생성했다(볼륨 유지).
- 두 토큰 모두 Git 밖 임시 폴더에만 있다. **운영 토큰은 만들지 않았다.**
- 옛 토큰으로 보내면 `403 Authorization data is wrong!`. 옛 토큰은 이제 인증에 쓸 수 없다.

## 재검증 (합성 이벤트, 2026-11-06 12:44 KST)

`deploy/n8n/check-live-n8n.py before` 17/17 통과.

| 항목 | 결과 |
| --- | --- |
| 인증 헤더 없음 / 틀린 토큰 / 옛 토큰 | 403, 기록 없음, 실행 이력 없음 |
| 정상 | 200 `recorded`. 응답 시점에 파일 존재, 바이트 일치 |
| 중복 | 200 `duplicate` |
| 같은 ID·다른 본문 | 409 `conflict`, 기존 파일 불변 |
| 그 외 | 400·422·500(기록 실패) 응답, 8건 동시 → 기록 1개, Cutory 전송기 `recorded`→`duplicate` |

실행 이력 점검(`docker cp`로 복사본을 읽고 바로 삭제, 토큰은 개수만 출력):

| 시점 | n8n 테이블에서 새 토큰이 있는 행 | 원본 파일 바이트 |
| --- | --- | --- |
| 검사 직후 | `execution_data` 18행. 18건 모두 `success`이며 이미 삭제 표시됨 | WAL 18회 |
| 약 40초 후 | **0행**(18건 실제 삭제). 옛 토큰이 든 오류 실행 13건만 남음 | WAL 18회 그대로, 본 DB 파일 0회 |

- 컨테이너 로그, `n8nEventLog*.log`, `config`, 워크플로우 export, Cutory 전송 기록: 새 토큰과 옛 토큰 모두 0회.
- 오류 실행 삭제는 소스에서 같은 판단 경로(`shouldNotSave`)임을 확인했다. 이번 합성 이벤트에서는 오류 실행이 생기지 않아 실제로는 확인하지 못했다(미검증).

## 남은 위험

1. **SQLite 파일 바이트 잔존.** 행이 실제로 삭제돼도 WAL의 옛 프레임과 본 DB의 빈 페이지에 토큰 바이트가 남는다. 확인 시점에 옛 토큰은 본 DB 35회·WAL 64회, 새 토큰은 WAL 18회였다. 덮어써지거나 VACUUM할 때까지 남는다. 볼륨을 읽을 수 있으면 복원할 수 있다.
2. **실행 중 노출 구간.** 실행이 진행되는 동안과 끝난 뒤 최대 약 1분은 토큰이 n8n 테이블에 있다.
3. **과거 오류 실행 13건**(옛 토큰, 12:20 KST)이 `EXECUTIONS_DATA_MAX_AGE` 기본값에 따라 2026-11-20 무렵까지 남는다. 옛 토큰은 이미 403이라 인증에는 쓸 수 없다.
4. 볼륨 전체 백업에는 위 1·3이 함께 들어간다.

## 백업 가능한 항목

| 항목 | 위치 | 비밀값 | 권장 |
| --- | --- | --- | --- |
| 워크플로우 정의 | Git `deploy/n8n/*.json`·`*.js`, `n8n export:workflow` | 없음(자격증명 ID·이름만, 토큰 없음 확인) | Git으로 충분 |
| 자격증명 | n8n DB(암호화), `n8n export:credentials` | 암호화 문자열. `config`의 `encryptionKey`와 함께면 평문 복원 가능 | 백업하지 말고 새 토큰으로 다시 등록 |
| `encryptionKey` | 볼륨 `/home/node/.n8n/config` | 비밀 | DB 복원이 필요할 때만, 비밀로 취급 |
| 이벤트 기록 | 볼륨 `/home/node/.n8n-files/cutory-render-events/` 15개(모두 합성) | 없음 | 지금은 가치 없음. 실제 운영 후 `docker cp`로 백업 |
| n8n DB·볼륨 전체 | `cutory-n8n-home` | 옛 테스트 토큰(행·바이트), 새 테스트 토큰(바이트) | 현재 상태로는 백업하지 않음 |

## 과거 이력 정리 방법 (제안, 미실행)

볼륨 삭제나 DB 직접 수정 없이 n8n이 지원하는 기능만 쓰는 순서다.

1. **오류 실행 13건 삭제.** 둘 중 하나를 고른다.
   - **A(권장, 소유자 계정 필요):** 사용자가 `http://127.0.0.1:5678`에서 소유자 계정을 직접 만든 뒤 Executions 화면에서 전체 선택·삭제한다. 지금 설정으로 1분 안에 실제 삭제된다.
   - **B(계정 불필요):** compose에 `EXECUTIONS_DATA_MAX_AGE=1`을 추가하고 재생성한다. n8n의 나이 기반 정리(60분 주기)가 1시간 지난 실행을 삭제 표시하고, 1분 안에 실제 삭제된다. 저장되는 실행이 없으므로 이 값을 계속 둬도 된다.
2. **바이트 잔존 정리:** `DB_SQLITE_VACUUM_ON_STARTUP=true`로 한 번 재시작해 n8n이 시작할 때 VACUUM하게 한다. 그다음 다시 바이트를 검사한다. WAL 파일에 남은 옛 프레임까지 지워지는지는 미확인이다. 남으면 재시작을 한 번 더 하거나, 승인을 받아 볼륨을 다시 만드는 방법만 남는다.
3. 정리 후 `scan` 방식(복사본·개수만 출력)으로 옛·새 테스트 토큰 0회를 확인한다.

가장 확실한 방법은 볼륨 재생성이다. 다만 이번 범위에서 금지됐고, 기록 파일·자격증명·워크플로우를 다시 등록해야 해서 별도 승인이 필요하다.

## 구조적 대안 (향후 검토)

- Bearer 토큰 대신 HMAC 서명 헤더(타임스탬프 + 본문 서명)를 쓰면 비밀이 요청에 실리지 않는다. 실행 이력에는 서명만 남는다.
- 대신 Cutory 전송기를 바꿔야 하고, Code 노드에 `crypto` 허용이 필요하며, 재전송 공격도 막아야 한다. MVP 범위 밖이다.
