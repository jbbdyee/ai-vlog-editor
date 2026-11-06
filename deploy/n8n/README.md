# n8n 렌더 후속 처리 (MVP)

Cutory FastAPI/DB가 렌더 상태의 유일한 기준이다. n8n은 `COMPLETED`·`FAILED`·`RECONCILIATION_REQUIRED`가 DB에 커밋된 뒤 받은 이벤트를 **기록만** 한다. n8n이 Cutory를 호출하거나 상태를 바꾸지 않는다.

상태(2026-11-06): **n8n 2.46.6 격리 컨테이너에서 합성 이벤트로 검증 완료**(인증·기록·중복·충돌·기록 실패 500·재시작 후 유지). Cutory 8000 연동·실제 이벤트는 미검증. 실행 이력의 토큰 평문 저장은 저장 안 함·즉시 정리 설정으로 테이블에서 약 1분 안에 삭제되도록 줄였다. SQLite 바이트 잔존과 과거 실행 13건은 남아 있다(아래 보안). [1단계 기록](../../docs/handoff/n8n-live-stage1-2026-11-06.md), [보안 정리](../../docs/handoff/n8n-security-cleanup-2026-11-06.md)

## 파일

| 파일 | 내용 |
| --- | --- |
| `docker-compose.yml` | 격리 compose 프로젝트 `cutory-n8n`. 이미지 digest 고정, `127.0.0.1:5678`, 볼륨 `cutory-n8n-home` |
| `record-render-event.js` | Code 노드 로직의 원본. 검증 → 원자적 기록 → 디스크 재확인 → 응답 코드 결정 |
| `cutory-render-events.workflow.json` | import용 워크플로우. `build_workflow.py`로 생성(자격증명·ID·비밀값 없음, 비활성 상태) |
| `build_workflow.py` | JSON 재생성 / `--check`로 불일치 확인 |
| `check-record-render-event.mjs` | n8n 없이 로직 검증(Node 18+). n8n 샌드박스처럼 `process` 없음·`fs`/`path`만 허용. 인자로 Cutory 페이로드 배열 JSON을 주면 함께 검증 |
| `check-live-n8n.py` | 실행 중인 n8n에 합성 이벤트를 보내 검사(`before`, 재시작 후 `after`). `CUTORY_N8N_TEST_DIR`(Git 밖)의 `test-token.txt` 사용, 토큰 출력 없음 |

## 워크플로우

`Webhook(POST, Header Auth, 응답은 Respond 노드에서)` → `Code: Validate and record` → `Respond to Webhook(상태 코드 = $json.httpStatus)`

| 응답 | 조건 | Cutory 동작 |
| --- | --- | --- |
| 200 `recorded` | 처음 받은 이벤트를 기록하고 디스크에서 재확인 | 전달 완료 |
| 200 `duplicate` | 같은 ID, **같은 내용**이 이미 기록됨 | 전달 완료 |
| 409 `conflict` | 같은 ID인데 내용이 다름(덮어쓰지 않음) | 재시도 없음, 기록 |
| 400 `invalid` | 필드 누락·추가, ID·유형·상태 URL 불일치, 실패 이벤트에 출력 값 등 | 재시도 없음 |
| 403 | Header Auth 실패(n8n Webhook 노드가 `Authorization data is wrong!`로 응답, 실행 이력 없음) | 재시도 없음 |
| 422 | 본문이 JSON이 아님(Webhook 노드가 응답) | 재시도 없음 |
| 500 `error` | 저장 폴더 생성·쓰기·재확인 실패 | 최대 3회 재시도 |

- 중복 제거는 이벤트 ID만 믿지 않는다. 고정 키 순서의 기록 내용이 같아야 `duplicate`이고, 기록은 임시 파일 + `link`(있으면 실패)로 만들어 동시 중복에서도 하나만 `recorded`가 된다.
- 기록 위치: 컨테이너 안 `/home/node/.n8n-files/cutory-render-events/<event_id>.json`. 수신 시각 등 매번 달라지는 값은 넣지 않는다.

## 설치 (2.46.6에서 확인)

```
docker compose -f deploy/n8n/docker-compose.yml up -d
```

- 포트는 `127.0.0.1:5678`에만 공개. Tailscale·LAN 공개 금지(Cutory에 인증이 없음). 별도 네트워크 `cutory-n8n_default`.
- 볼륨은 `/home/node` 전체에 붙인다. 이미지에 `/home/node/.n8n-files`가 없어서 그 경로에 이름 있는 볼륨을 따로 붙이면 root 소유로 만들어져 쓰기가 막힐 수 있다. 볼륨은 ext4이고 hard link가 동작한다.
- 2.46.6은 Code 노드를 task runner(internal 모드)에서 실행한다. 컨테이너의 `NODE_FUNCTION_ALLOW_BUILTIN=fs,path`가 runner에도 적용됐다. 샌드박스에 `process` 전역은 없다.
- 소유자 계정 없이 CLI로 import·활성화할 수 있다(UI를 쓰려면 사용자가 소유자 계정을 직접 만든다).
  1. `n8n import:credentials`로 Header Auth 자격증명(이름 `Authorization`, 값 `Bearer <토큰>`)을 등록한다. 입력 파일은 컨테이너 `/tmp`에 stdin으로 넣고 바로 지운다. n8n DB에는 암호화 저장된다.
  2. `n8n import:workflow`로 import한다. 같은 ID로 다시 import해 Webhook 노드에 자격증명 ID를 연결한다(Git의 JSON에는 연결 정보를 두지 않는다).
  3. `n8n publish:workflow --id=<ID>`를 실행하고 컨테이너를 재시작한다.
- 토큰은 n8n 자격증명과 Cutory `.env`에만 둔다.

## 보안 (2026-11-06 확인·정리)

- n8n 실행 데이터에는 Webhook 요청 헤더(토큰 포함)가 들어간다. 2.46.6은 저장 설정과 관계없이 **실행 중에 DB에 먼저 쓰고**, 끝나면 삭제 표시 → 정리 작업이 실제 삭제한다.
- 적용한 설정:
  - 워크플로우: 성공·실패 `none`, 수동 실행·진행 저장 false
  - 인스턴스: `EXECUTIONS_DATA_SAVE_*` 동일
  - `EXECUTIONS_DATA_HARD_DELETE_BUFFER=0`, `EXECUTIONS_DATA_PRUNE_HARD_DELETE_INTERVAL=1`
- 재검증 결과 새 테스트 토큰이 든 실행 18건이 약 40초 안에 테이블에서 사라졌다.
- **남는 것:**
  - SQLite WAL·빈 페이지의 바이트 잔존
  - 1차 검증 때 생긴 오류 실행 13건(옛 테스트 토큰, 이미 무효)
  - 정리 방법(소유자 UI 삭제 또는 `EXECUTIONS_DATA_MAX_AGE`, `DB_SQLITE_VACUUM_ON_STARTUP`)은 [보안 정리 기록](../../docs/handoff/n8n-security-cleanup-2026-11-06.md)
- 자격증명 테이블·컨테이너 로그·이벤트 로그·워크플로우 export·Cutory 전송 기록에는 토큰이 없다.
- 볼륨 전체를 백업하면 위 잔존 데이터가 함께 들어간다. 자격증명은 백업하지 말고 다시 등록한다.
- 근본 대안으로 Bearer 대신 HMAC 본문 서명을 설계했고 격리 검증까지 마쳤다(미적용). [HMAC 설계](../../docs/handoff/n8n-hmac-design-2026-11-06.md)
- `fs` 허용은 이 인스턴스의 모든 Code 노드에 적용된다. 이 인스턴스는 Cutory 이벤트 전용으로만 쓴다.

## Cutory 설정

`.env`(Git 제외)에만 둔다. 둘 다 비면 기능이 꺼진다.

```
CUTORY_N8N_WEBHOOK_URL=http://127.0.0.1:5678/webhook/cutory-render-events
CUTORY_N8N_WEBHOOK_TOKEN=<32자 이상, 공백 없음>
```

- 루프백이 아닌 주소, URL의 사용자 정보·쿼리, 짧은 토큰은 거부하고 오류 코드만 로그에 남긴 채 기능을 끈다(서버는 정상 기동).
- 렌더 영속화(`CUTORY_RENDER_PERSISTENCE_ENABLED=1`)일 때만 동작한다. 서버 재시작 후 적용된다.
- 전송 기록: `temporary/render-events/deliveries.jsonl`(Git 제외). 이벤트 ID·전송 ID·시도 번호·결과·HTTP 상태·오류 클래스만 남기고 URL·토큰·본문은 남기지 않는다.

## 누락 이벤트 재전송

```
python -m backend.app.render_event_replay --since 2026-11-06T00:00:00Z            # 목록만(기본)
python -m backend.app.render_event_replay --since 2026-11-06T00:00:00Z --send     # 실제 전송
```

DB는 읽기 전용 트랜잭션으로 조회한다. 실시간 전송과 같은 ID·본문이라 수신 측에서는 `duplicate`가 된다.
