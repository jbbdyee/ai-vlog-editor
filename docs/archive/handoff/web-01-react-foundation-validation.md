# WEB-01 — React 프론트엔드 기반 구축 및 검증

## 범위와 기준

- 기준 checkout: `main`, 작업 시작 HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`.
- 기존 `backend/tests/test_clip_download_api.py`, `backend/tests/test_project_render_api.py`, `backend/tests/test_project_rendering.py`의 미커밋 변경과 `docs/handoff/mvp-07b-multi-clip-validation.md`의 미추적 보고서는 보존했다.
- 기존 `backend/` FastAPI와 `frontend/` Streamlit, 렌더링, 원본 영상, 평가 계약·GT·Manifest는 변경하지 않았다.
- 루트 `SPEC.md`와 `IMP-PLAN.md`는 없으며 제품 목표는 `docs/product/full-development-plan.md`, 현재 v2 범위는 `docs/roadmap/v2-plan.md`가 관리한다. 이 작업의 구현 상태는 `TODO.md`와 이 기록에서 관리한다.

## 실제 API 계약과 구현

`backend/app/routers/projects.py`의 현재 계약에 맞춰 `web/`을 별도로 구성했다.

| 화면 동작 | API | 성공 의미 | 오류·제한 |
| --- | --- | --- | --- |
| 프로젝트 생성 | `POST /projects` | 201, 생성된 프로젝트 ID로 이동 | 이름 필수, `SINGLE` 정책만 이 화면에서 선택; 전체 목록 API 없음 |
| ID로 기존 프로젝트 열기 | `GET /projects/{id}` | 200, 서버가 확인한 프로젝트로 이동 | UUID 형식 확인, 404 등 오류 표시 |
| 원본 등록 | `POST /projects/{id}/sources` | 201, 서버의 소스 ID 확인 후 목록 재조회 | MOV/MP4·4 GiB 이하 UI 사전 확인; 서버가 최종 검사, 415 등 표시 |
| 처리 요청 | `POST /projects/{id}/process` | 202·`accepted: true`는 접수이며 완료가 아님 | 409 등 표시, 서버 상태 조회 |
| 상태 확인 | `GET /projects/{id}/processing` | 서버의 프로젝트·소스 상태와 완료/실패/차단 건수 표시 | 활성 처리 중 2초 간격 조회, 그 외 중지; 새로고침 시 다시 조회 |

React Router가 프로젝트 ID를 `/projects/{id}`에 넣고, TanStack Query가 조회 상태를 관리한다. XHR 업로드는 전송 바이트의 진행률 또는 측정 불가 상태를 표시한다. 100% 전송 후에도 서버 등록 응답을 기다리며, 이 수치를 영상 분석 진행률로 취급하지 않는다. 취소 뒤에는 서버 등록 여부가 불확실할 수 있어 목록 재조회 후 확인하도록 안내한다. 처리 요청 뒤에도 서버의 실제 `PROCESSING`/종료 상태를 기다린다. 서버가 제공하지 않는 실제 처리 퍼센트는 생성하지 않는다.

UI는 어두운 영상 작업 공간 형태이며 프로젝트 진입, 파일 카드, 처리 상태를 제공한다. 장면 후보, AI 추천 점수, 타임라인, 미리보기, 편집 계획, 최종 다운로드 화면은 WEB-01에 구현하지 않았다. 장면 단계 표시는 후속 단계라고 명시한다. shadcn CLI 실행은 로컬 `pnpm dlx`의 `zod-to-json-schema` 해석 오류로 완료되지 않아, 실제 사용한 Button/Card/Input/Label/Alert/Progress만 Radix·CVA 기반의 shadcn 방식 소스 컴포넌트로 작성했다. 이 CLI 문제는 앱 빌드 실패와 구분한다.

## 환경과 검증

- Windows, Node.js 24.19.0, pnpm 11.25.0. 직접 의존성 버전은 `web/package.json`과 `web/pnpm-lock.yaml`에 고정했다.
- `pnpm build`: TypeScript 검사 및 Vite 프로덕션 빌드 성공.
- `pnpm test`: Vitest/React Testing Library 9건 통과. 생성 성공·실패, ID 검증·404, MOV/MP4·크기·형식, XHR 등록·바이트 진행률·취소·415, 새로고침 뒤 저장 상태 조회, 처리 접수·상태 전환·409를 검증했다.
- `pnpm test:e2e`: 로컬 Chrome을 실제 실행하여 API 모의 응답을 사용하는 2개 브라우저 시나리오가 통과했다. 생성→등록→처리→새로고침 상태 복구 및 생성·조회 오류 표시를 확인했다. Windows에서 Playwright의 자동 기동 테스트 서버 종료가 지연되어 Vite를 별도 터미널에서 먼저 실행하고 테스트 명령을 재실행했으며, 이때 종료 코드 0과 `2 passed`를 확인했다. 자동 서버 종료 문제는 남는다.
- 실제 FastAPI/PostgreSQL에 연결한 브라우저 통합 테스트, 실제 MOV/MP4 파일 업로드·분석, 다른 브라우저·운영체제, 배포 환경은 이번 검증에서 실행하지 않았다. 모의 파일과 API 응답을 실제 영상 처리 결과로 해석하지 않는다.

## 보안·운영 한계와 다음 단계

현재 백엔드에는 사용자 인증, 프로젝트 소유권 검증, 프로젝트 전체 목록 API가 없다. ID 검증은 인증이 아니며 이 화면은 `127.0.0.1` 로컬 개발 범위로 제한한다. 공개 배포하지 않는다. FastAPI를 변경하지 않고 Vite 개발 프록시로 연결한다. 브라우저 파일 크기·MIME 검사는 편의 기능이며 서버 검증을 대체하지 않는다.

WEB-02에서는 기존 장면 후보·편집 계획·렌더링/다운로드 API 계약을 재확인하고 화면을 단계적으로 연결한다. 그 전에 로컬 FastAPI/PostgreSQL을 이용한 브라우저 통합 검증과 업로드 취소 뒤 실제 서버 등록 여부, 큰 파일·네트워크 실패, Windows 이외 환경을 검증해야 한다. 현재 Streamlit 제거 시점은 정하지 않았다.

후속 실제 백엔드 통합 결과와 WEB-01 오류 문구 수정은 [WEB-01B 기록](web-01b-real-backend-e2e-validation.md)에 별도로 남긴다. 위 검증 수치는 WEB-01 당시의 기준선이다.
