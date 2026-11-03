# 개인 Tailscale 개발 접속

개인 접속 주소는 로컬 Tailscale 관리 화면에서 확인한다. 공개 문서에는 기기명·tailnet 도메인·IP를 기록하지 않는다.

이 구성은 Tailscale Serve의 HTTPS 443만 `http://127.0.0.1:5173`으로 프록시한다. FastAPI는 `127.0.0.1:8000`에서 실행하고 Vite의 `/api` 프록시를 통해 호출한다. Vite는 기본적으로 loopback 호스트를 허용하며, 개인 tailnet 호스트가 필요하면 `CUTORY_ALLOWED_HOSTS`에 호스트명만 지정한다. 로컬의 `web/.env.local`에 둘 수 있으며 이 파일은 Git에서 제외된다. 쉼표로 구분한 복수 호스트도 허용한다. `/api` 프록시는 Tailscale이 붙인 `X-Forwarded-For`와 `Forwarded`를 FastAPI에 전달하지 않는다. 그래야 FastAPI의 loopback 전용 원본 미디어 API가 이 개발용 프록시를 통해 Range 요청에 응답한다. 이는 사용자 인증을 추가하지 않는다. Tailnet의 다른 접근 가능 구성원도 API와 영상에 접근할 수 있으므로 개인용 tailnet에서만 사용한다. Funnel, 공유기 포트 포워딩, Windows 방화벽 전체 개방은 사용하지 않는다.

## 실행과 중단

FastAPI와 PostgreSQL을 별도로 유지하고, `web/`에서 `pnpm dev`로 Vite를 실행한다. 현재 Serve 설정은 Tailscale 백그라운드 설정이므로 Vite와 Tailscale 연결이 유지되면 본인의 tailnet 주소로 접속할 수 있다. Serve를 다시 등록할 때는 Windows PowerShell에서 다음을 실행한다.

```powershell
tailscale serve --bg --https=443 http://127.0.0.1:5173
```

접속만 중단할 때는 다음 명령을 사용한다. 다른 Serve 포트 11434·2222는 건드리지 않는다.

```powershell
tailscale serve --https=443 off
```

## 맥북·아이폰 확인 순서

1. 각각 같은 개인 tailnet에 Tailscale로 로그인·연결하고 본인 기기의 HTTPS 주소를 브라우저에서 연다.
2. 프로젝트 ID를 입력해 프로젝트와 소스 목록을 조회한다. API 요청은 브라우저 개발자 도구에서 같은 HTTPS 도메인의 `/api/...`로 보내져야 한다.
3. 원본 영상 미리보기를 열고 재생·일시정지·탐색을 확인한다. 지원 코덱은 기기별로 다를 수 있다. 개발자 도구에서 미디어 요청의 `Range` 헤더와 `206 Partial Content`, `Content-Range` 응답을 확인한다.
4. 완료 렌더가 현재 API에 등록된 프로젝트에서 기본 MP4와 자막 MP4를 재생·탐색하고 각각 다운로드한다. 파일 크기와 재생 가능 여부를 확인한다. 기존 QA 렌더가 현재 API에 등록되지 않은 경우 해당 다운로드는 404일 수 있다.
5. 맥북에서는 개발자 도구의 WebSocket에서 본인 tailnet 호스트로 HMR 연결되는지 확인한다. 아이폰은 페이지 로드와 새로고침 후 동작을 확인한다.

## 2026-10-27 Windows 확인 결과와 한계

- HTTPS 문서·React/Vite 리소스·`/api/openapi.json`은 200, HMR WebSocket은 `vite-hmr`로 연결됐다.
- P1-S01 QA 원본의 HTTPS Range `bytes=0-15`는 206, `Content-Range: bytes 0-15/141327567`이었다. 실제 맥북·아이폰 재생과 다운로드는 이 PC에서 검증하지 않았다.
- 기존 WEB-04 QA 렌더 ID의 다운로드는 현재 8000 API에서 404였다. 기존 개발 API가 WEB-08B 영속화 경로로 전환되지 않았으므로 현재 서버에서 사용 가능한 렌더로 확인해야 한다.
- **당시 2026-10-27 점검:** PostgreSQL 포트가 모든 인터페이스에 게시돼 이 PC의 Tailscale IP로 TCP 연결이 성립했다. 다른 tailnet 기기에서의 직접 연결은 검증하지 않았다. 이후 SEC-01에서 Compose 게시 주소를 `127.0.0.1:${POSTGRES_PORT:-5432}:5432`로 제한하고 로컬 DB·프록시 연결을 확인했다. [최신 적용 결과](../handoff/sec-01-postgres-network-hardening.md)를 따른다.
