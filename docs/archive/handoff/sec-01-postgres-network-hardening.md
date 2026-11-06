# SEC-01 — PostgreSQL 네트워크 접근 제한

상태: **로컬 Compose 변경 적용·기술 검증 완료**, 다른 tailnet 기기에서의 직접 접속은 미검증. 시작 브랜치 `main`, HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. 기존 WEB·EVAL 미커밋 변경과 보호 대상 백엔드 테스트 3개를 보존했다. Git 커밋·Push 없음.

## 적용 전 게이트

| 확인 | 결과 |
| --- | --- |
| 작업·DB | 기존 FastAPI 8000의 프로젝트 12개에 대해 소스 처리·장면 분석·렌더 상태를 읽어 활성 작업 0개. 적용 직전 `pg_stat_activity`의 비유휴 다른 쿼리 0개. 이 조회 시점 이후 다른 사용자의 신규 작업을 막는 운영 잠금은 설정하지 않았음 |
| 기존 게시 | `compose.yaml`의 `${POSTGRES_PORT:-5432}:5432`로 Docker가 IPv4 `0.0.0.0:5432`, IPv6 `[::]:5432`에 게시. FastAPI의 `.env`와 실제 TCP 연결은 `127.0.0.1:5432` |
| 백업 | Git 제외 `temporary/sec01-backup-20261028/db.dump`, `pg_dump -Fc` 81,692바이트, SHA-256 `4134787ba1342fad916408d549595004fa4c1aba7d8aeffddbd865be12e946e2`. `pg_restore -l` 성공 |
| 격리 복원 | 별도 `cutory-web08b-isolated` PostgreSQL의 신규 DB `cutory_sec01_restore_20261028`에 `pg_restore --exit-on-error` 성공. 원본/복원본 revision `ca3e4f5a6b7c`, 공개 테이블 16개와 이름, 프로젝트 12·소스 9·SceneCandidate 44·편집 계획 4개가 일치 |
| 볼륨 | 적용 전후 Compose 볼륨 `ai-vlog-editor-https-github-com_postgres_data`가 같은 `/var/lib/postgresql/data`에 연결됨. DB·영상/렌더 볼륨을 삭제·초기화하지 않음 |

## 변경·서비스 영향

`compose.yaml`의 `postgres.ports` **한 줄만** `"127.0.0.1:${POSTGRES_PORT:-5432}:5432"`로 변경했다. `docker compose config`에서 `host_ip=127.0.0.1`, 게시/대상 포트 5432임을 확인한 뒤 `docker compose up -d --no-deps postgres`로 PostgreSQL 서비스만 재생성했다. FastAPI·Vite·Tailscale Serve는 종료하거나 재시작하지 않았다. 기존 `.env`, DB revision, 다른 Compose 서비스 설정은 변경하지 않았다.

첫 시작은 이전 Docker 포트 프록시 연결의 `FIN_WAIT_2`가 남은 시점에 Windows `127.0.0.1:5432` bind 충돌로 실패했다. 이때 새 컨테이너는 `Created` 상태였고 원래 볼륨이 연결된 것을 확인했다. 동일 명령을 재시도해 정상 시작했으며 데이터 삭제나 포트 변경 우회는 하지 않았다. 이 과정에서 PostgreSQL 연결은 일시 중단됐으므로 진행 중 작업이 없는지 확인하는 선행 게이트가 필요했다.

## 적용 후 검증

| 항목 | 실제 결과 |
| --- | --- |
| PostgreSQL | 컨테이너 `running`, health `healthy`; `docker port`와 Compose 상태는 **`127.0.0.1:5432->5432/tcp`만** 표시. `[::]` 게시 없음. Windows LISTEN 주소도 `127.0.0.1:5432` |
| DB 무결성 | 기존 revision `ca3e4f5a6b7c` 그대로. 16개 테이블, 프로젝트 12·소스 9·SceneCandidate 44·편집 계획 4개가 백업 복원본과 일치. WEB-08B migration 미적용 |
| Windows TCP | `Test-NetConnection 127.0.0.1 -Port 5432`: 성공. 이 PC의 Tailscale IP `<이 PC의 Tailscale IP>:5432`: 실패 |
| 애플리케이션 | 기존 프로젝트의 `GET /projects/{id}`가 FastAPI `127.0.0.1:8000`, Vite `127.0.0.1:5173/api`, Tailscale HTTPS `/api`에서 모두 200과 같은 프로젝트 ID 반환. Vite 홈·Tailscale HTTPS 홈도 200 |
| Tailscale Serve | HTTPS 443 → `http://127.0.0.1:5173`, TCP 11434·2222는 변경 전후 동일. Serve 설정 변경 없음 |

다른 tailnet 기기에서 `5432` 직접 연결은 이 PC에서 실행하지 못했다. Docker 호스트 포트가 IPv4 loopback에만 게시됐고 IPv6 게시가 사라진 점은 확인했지만, 원격 기기 관측으로 대체하지 않는다. Windows 방화벽의 기존 광범위한 Tailscale/Docker 규칙은 변경하지 않았으며 다른 서비스의 노출 범위는 이번 DB 한 줄 변경으로 해결되지 않는다. React HTTPS는 인증·사용자 소유권이 없는 로컬 개발용이며 Tailnet 접근자가 API에 접근할 수 있는 위험도 유지된다.

백업과 격리 복원 DB에는 민감한 프로젝트 데이터가 포함될 수 있으므로 Git에 추가하지 않는다. 원본 영상·GT·Manifest·기존 렌더 파일에는 쓰기 작업을 수행하지 않았다.
