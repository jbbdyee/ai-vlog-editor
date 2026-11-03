# Cutory — AI 브이로그 편집기

> 사용자의 편집 의도는 남기고, 반복적인 영상 편집 노동은 AI에게 맡깁니다.

> **현재 상태 (2026-11-04 작업 트리):** React·FastAPI·PostgreSQL 기반 편집 흐름과 로컬 Ollama LLM/VLM 제안을 구현했습니다. 이 기능들은 아직 모두 GitHub `main`에 커밋된 상태가 아닙니다. 실제 영상의 제한된 시연과 격리 합성 영상의 하드 자막 생성은 확인했지만, 동결 GT 기반 추천 품질 평가는 미실행입니다.

## 한눈에 보는 실제 흐름

1. 프로젝트를 만들거나 목록에서 열고 MOV/MP4를 등록합니다.
2. 서버가 영상 메타데이터·오디오·전사를 처리하고 장면 Evidence와 SceneCandidate를 생성합니다. 후보가 없으면 근거 부족 상태를 보여 주며 편집 완료로 취급하지 않습니다.
3. 원본·후보 구간을 미리 보고 장면을 직접 선택·정렬합니다. 자연어 요청은 **저장 전 제안**이며, 로컬 Ollama LLM이 의도를 해석하고 VLM이 저장한 화면 설명·태그·분류를 활용합니다. Python은 STT 대사 근거와 화면 근거를 구분하고, 지원하는 명시적 화면 조건(예: 음식·동물·풍경)을 최종 검증합니다. 근거가 부족하면 전체 장면을 임의로 선택하지 않습니다. LLM 실패 시 규칙 기반 제안으로 돌아갑니다.
4. 사용자가 편집 계획을 저장·검토한 뒤 렌더를 실행합니다. 로컬 FFmpeg가 기본 MP4와 SRT를 만들고, 글꼴이 설정되면 Docker의 고정 FFmpeg/libass 이미지가 **별도** 한국어 하드 자막 MP4를 만듭니다. 자막 생성 실패 시 기본 MP4는 유지됩니다.
5. 완료된 두 영상을 React에서 재생·다운로드합니다. 렌더 기록은 PostgreSQL에 저장하고 결과 파일은 경로·크기·SHA-256으로 검증합니다.

**사용 기술:** React 19·TypeScript·Vite·Tailwind CSS·React Router·TanStack Query, FastAPI·SQLAlchemy·Alembic·PostgreSQL, faster-whisper, 로컬 Ollama `gemma3:4b`, FFmpeg/FFprobe, Docker/libass. 기존 Streamlit 화면도 유지합니다. Redis는 현재 확인된 처리 경로에 사용하지 않습니다.

## 로컬 실행 요약

인증·사용자 소유권 검증이 없어 **개인 로컬 개발 환경용**입니다. 원본 영상, `.env`, DB 백업, 렌더 파일을 Git에 추가하거나 앱을 공개 배포하지 마세요.

1. Python 3.12, Node.js 24·pnpm 11, Docker Desktop, FFmpeg/FFprobe, PostgreSQL을 준비합니다. `.env.example`을 `.env`로 복사하고 로컬 DB 암호를 설정합니다. Compose는 PostgreSQL을 `127.0.0.1:5432`에만 게시합니다.
2. Python 가상환경을 새로 만들고 `pip install -r requirements.txt`로 설치합니다. 새 빈 DB에서만 `alembic upgrade head`를 실행합니다. 기존 DB에 무심코 migration을 다시 적용하지 마세요.
3. 자연어·화면 분석 시 로컬 Ollama에 `gemma3:4b`를 준비하고 `CUTORY_EDIT_LLM_PROVIDER=ollama`, `CUTORY_EDIT_LLM_MODEL=gemma3:4b`, `CUTORY_VLM_MODEL=gemma3:4b`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`를 설정합니다. 외부 Provider 키는 필요하지 않습니다. 하드 자막을 만들려면 [검증된 글꼴·Docker 조건](docs/handoff/mvp-06c-2b-windows-validation.md)에 맞는 `CUTORY_SUBTITLE_FONT_PATH`가 필요합니다.
4. 최신 렌더 기록·해시 검증 스키마가 준비된 DB에서는 `CUTORY_RENDER_PERSISTENCE_ENABLED=1`로 FastAPI를 `127.0.0.1:8000`에서 실행합니다. 별도 터미널에서 `cd web`, `pnpm install --frozen-lockfile`, `pnpm dev`를 실행하면 `http://127.0.0.1:5173`에서 `/api` 프록시로 연결됩니다. 실행 상세는 아래 [React 개발 화면 실행](#react-개발-화면-실행-web-01)과 [현재 API 실행](#run-the-current-api)을 참고하세요.

Windows PowerShell 예시(가상환경·`.env`·**새 빈 DB의** migration 준비 후, 각 서버는 별도 터미널에서 실행):

```powershell
docker compose up -d postgres
$env:CUTORY_RENDER_PERSISTENCE_ENABLED = '1'
$env:CUTORY_EDIT_LLM_PROVIDER = 'ollama'
$env:CUTORY_EDIT_LLM_MODEL = 'gemma3:4b'
$env:CUTORY_VLM_MODEL = 'gemma3:4b'
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
# 다른 터미널: cd web; pnpm install --frozen-lockfile; pnpm dev
```

하드 자막 생성 시에는 위 FastAPI 프로세스가 Docker CLI·엔진과 검증된 글꼴에 접근할 수 있어야 합니다. 로컬 Ollama를 쓰지 않으면 LLM 제안은 규칙 기반 fallback으로 제한되며, VLM 화면 분석은 로컬 모델을 요구합니다.

## 시연 증거와 검증 범위

- [포트폴리오 편집 흐름 기록](docs/handoff/demo-01-portfolio-edit-flow.md), [실제 영상 두 소스 E2E](docs/handoff/web-04-react-e2e-validation.md), [렌더 결과 미리보기](docs/handoff/web-07-render-preview-validation.md)에 실행 조건과 범위를 남겼습니다. 현재 화면 캡처 스크립트는 [portfolio-capture.spec.ts](web/e2e-real/portfolio-capture.spec.ts)입니다. **원본 프레임이 포함된 로컬 캡처·영상은 공개 저장소에 포함하지 않습니다.** 공개용 이미지는 별도 검토 후 비식별 자료만 사용합니다.
- 현재 8000에는 최신 P0 제안 수정이 적용됐고 실사 데모의 “음식이 보이는 장면만” 요청에서 케이크 화면 근거 2건을 반환했습니다. 기존 MP4 다운로드·SHA-256과 5173 프록시를 확인했습니다. 별도 2초 합성 영상에서 Docker 하드 자막 생성·한글 프레임·H.264/AAC·해시 일치를 확인했습니다. [현재 인수인계](Doc/HANDOFF.md)에 세부 증거가 있습니다.
- **한계:** 신규 실사 영상의 전체 렌더·자막 품질을 이번 8000 교체 후 재검증하지 않았습니다. 실제 iPhone Safari 검증, 다양한 시각 조건의 품질, 동결 GT 기반 정량 평가도 미완료입니다. GT freeze-ready는 `PENDING` 28건이며 SceneCandidate를 정량 품질 합격으로 소개하지 않습니다.

Cutory는 여러 촬영 영상에서 장면과 사건을 찾고, 사용자 의도·취향·현재 요청을 반영해 한 편의 브이로그를 만드는 **멀티 에이전트 AI 편집기**를 목표로 합니다. 사용자는 창작 방향과 결과를 확인하고, AI는 반복적인 탐색·구성·편집 작업을 돕습니다.

## 제품 목표

- 음성 메모가 없어도 영상에서 의미 있는 장면을 찾고, 메모가 있으면 편집 의도의 단서로 활용합니다.
- 장면을 이야기 흐름에 맞게 구성하고 자막·음악·색감 등의 편집안을 계획합니다.
- 미리보기와 사용자 검토를 거쳐 완성 영상을 만드는 흐름을 지향합니다.

이는 [최종 제품 기획](docs/product/full-development-plan.md)의 방향이며, 아래의 현재 구현 범위와 구분됩니다.

## 구현·검증 이력

아래 항목은 **각 단계가 끝났을 당시**의 결과와 당시 미완료 상태를 보존한 이력입니다. 현재 적용 상태는 위의 ‘한눈에 보는 실제 흐름’·‘시연 증거와 검증 범위’ 및 [HANDOFF](Doc/HANDOFF.md)를 우선합니다.

- **v1 완료:** 여러 원본 영상의 등록·처리 상태 저장, 재개와 부분 실패 처리를 위한 기반을 만들었습니다.
- **v2 진행 중:** 장면 후보 분석과 편집 계획, 선택한 장면을 MP4로 결합하는 백엔드 기능을 단계적으로 구현했습니다. 실제 영상 평가와 사용자 화면 연결 등은 계속 진행 중입니다.
- **WEB-01 기반:** 기존 Streamlit을 유지하면서 `web/`에 React + TypeScript 개발용 화면을 추가했습니다. 프로젝트 생성·ID 조회, MOV/MP4 등록, 서버 소스 처리 상태를 연결했습니다.
- **WEB-02 구현·제한된 실제 영상 검증:** 같은 React 프로젝트 화면에서 장면 분석 실행·상태 조회, 관측된 SceneCandidate와 Evidence 진단을 확인할 수 있습니다. P1-S01 QA 프로젝트 한 건의 실제 Chrome·FastAPI·PostgreSQL 경로에서 후보 5개를 확인했습니다. 이는 추천 순위나 정량 품질 평가가 아닙니다.
- **WEB-03 구현·제한된 실제 영상 검증:** React 화면에서 후보를 선택·정렬해 편집 계획을 저장하고 렌더 실행·상태 확인·기본 MP4와 한국어 하드 자막 MP4 다운로드를 수행합니다. P1-S01 격리 QA 프로젝트에서 실제 Chrome·FastAPI·PostgreSQL·FFmpeg·Docker 경로로 두 파일 생성과 다운로드를 확인했습니다. 편집 품질의 정량 평가, 다른 영상·운영체제 검증은 미완료입니다.
- **WEB-04 실제 전체 흐름 검증:** 새 격리 프로젝트에서 P1-S01·S02 두 영상을 Chrome으로 업로드해 분석·계획 저장·렌더·두 MP4 다운로드까지 확인했습니다. 두 소스 연결과 일부 자막 경계 프레임을 확인했으며, 전체 프레임·추천 품질·다른 운영체제 평가는 미완료입니다.
- **EVAL-01 평가 준비 진단:** 기존 Manifest와 P1 GT 초안의 구조 검사는 통과했지만 freeze-ready는 미비 28건으로 `PENDING`입니다. 두 실제 소스에 저장된 후보 17개의 수·길이·Evidence 연결만 읽기 전용으로 확인했습니다. 동결 GT 대비 검출률·IoU·Precision 및 시나리오별 품질 평가는 미실행입니다.
- **EVAL-02 GT 동결 준비:** P1 원본 7개의 해시·길이와 초안 대응을 재확인하고, freeze-ready 미비 28건을 사람이 수행할 작업으로 분류했습니다. P2·P3 원본과 독립 주석·인간 승인 기록이 없어 GT 동결 및 정량 평가는 여전히 미완료입니다.
- **WEB-05 편집기 사용성 분석:** 분석 당시 React는 프로젝트 기반 업로드부터 두 MP4 다운로드까지 연결됐습니다. 기존 Streamlit에는 별도의 단일 영상 fixed Window·Transcript/EditMemo 확인·클립 재생 기능이 남아 있습니다. 분석 당시 프로젝트 원본·장면 후보 구간·최종 렌더의 화면 재생은 두 UI 모두 제공하지 않았습니다.
- **WEB-06 로컬 원본·후보 미리보기:** React 프로젝트 화면에서 등록된 MOV/MP4를 선택해 재생하고 후보 시작·종료 구간을 확인할 수 있습니다. P1-S01·S02 HEVC Main 10 MOV는 이 Windows Chrome에서 원본 그대로 재생·탐색돼 프록시는 생성하지 않았습니다. 이 결과를 다른 브라우저·기기에 일반화하지 않습니다. 후보 재생은 프레임 정확도를 보장하지 않습니다.
- **WEB-07 최종 결과 미리보기:** 당시 완료·파일 사용 가능으로 확인한 기본 MP4와 한국어 하드 자막 MP4를 React에서 전환해 재생·탐색했습니다. 기존 다운로드는 유지합니다. 기존 WEB-04 QA 영상 두 파일은 실제 Windows Chrome에서 재생·seek와 자막 프레임을 확인했으나, 시험용 서버 메모리 상태를 사용했습니다. 당시 남은 재시작 복구는 WEB-08B/08C에서 구현·적용했습니다.
- **WEB-08A 설계 완료:** 당시 프로세스 메모리 전용 렌더 상태와 재시작 복구 정책을 [별도 문서](docs/handoff/web-08a-render-persistence-design.md)에 정리했습니다.
- **WEB-08B 격리 검증 완료:** 새 렌더의 DB 기록, 계획 스냅샷, 중단·파일 누락 구분, 과거 성공 결과 선택을 구현했습니다. 복원한 별도 PostgreSQL과 출력 경로에서 실제 P1-S01·S02 프로젝트 렌더 후 API 재시작·Chrome 재생/seek·두 MP4 다운로드를 확인했습니다. 당시 기존 DB에는 미적용이었으며 이후 WEB-08C에서 적용했습니다. 기존 QA 파일은 자동 등록하지 않습니다. [WEB-08B 기록](docs/handoff/web-08b-render-persistence-validation.md)을 참고하세요.
- **WEB-08C 기존 로컬 환경 적용 완료:** 새 백업·격리 복원 확인 후 승인받아 기존 DB를 `b8c01e2a4f60`으로 업그레이드하고 FastAPI만 영속화 모드로 교체했습니다. 새 기록 API와 실제 Chrome의 빈 기록 화면은 확인했습니다. 새 영상 렌더는 실행하지 않았으므로 기존 환경에서 완료 기록의 재시작 복구는 미검증입니다. 기존 QA 파일은 자동 등록하지 않았습니다. [WEB-08C 기록](docs/handoff/web-08c-production-local-rollout.md)을 참고하세요.
- **WEB-10 프로젝트 목록:** React 홈에서 기존 로컬 DB의 프로젝트를 생성일 최신순으로 보고 선택할 수 있습니다. 영상 수·편집 계획 존재·최신 렌더 기록 상태는 DB에 저장된 값만 표시하며, 렌더 기록이 없으면 ‘없음’으로 표시합니다. 기존 ID 직접 열기와 프로젝트 생성은 유지합니다. 실제 Chrome+FastAPI+PostgreSQL에서 12개 목록·상세 진입을 확인했습니다. 인증이 없어 로컬 개발 전용입니다. [WEB-10 기록](docs/handoff/web-10-project-list.md)을 참고하세요.
- **WEB-11 장면 선택·순서 UX:** React 편집 계획에서 선택 수·선택 표시, 모바일용 위·아래 이동, 선택 목록의 해제, 빈 계획 저장, 저장 중·완료·실패 상태를 명확히 했습니다. 기존 EditPlan API를 재사용하며 요청과 다른 저장 응답은 성공으로 취급하지 않습니다. 격리 PostgreSQL에서 실제 후보의 순서 저장·재조회 후 원래 계획을 복원했고, 기존 DB를 읽는 Chrome에서는 저장 없이 임시 순서 변경만 확인했습니다. 실제 영상 렌더는 실행하지 않았습니다. [WEB-11 기록](docs/handoff/web-11-edit-plan-ux.md)을 참고하세요.
- **WEB-12 렌더 전 계획 검토:** 렌더 버튼 위에서 서버에 저장된 장면의 순서·원본 파일명·시작/종료·개별 길이와 구간 길이 합계인 예상 영상 길이를 확인할 수 있습니다. 미저장·저장 중·실패·빈 계획·무효 구간이면 렌더를 막고 기존 선택 영역으로 돌아갈 수 있습니다. [DEV-01](docs/handoff/dev-01-server-and-web12-validation.md)에서 기존 FastAPI·PostgreSQL 데이터를 실제 Chrome 375px·1440px으로 읽기 전용 검증했습니다. 예상 길이는 실제 MP4 길이를 보장하지 않으며 이번에는 렌더를 실행하지 않았습니다. [WEB-12 구현 기록](docs/handoff/web-12-render-review.md)을 참고하세요.
- **QA-01 렌더 복구 점검:** 일회용 격리 PostgreSQL과 Mock 렌더로 동시 접수·stale 중단·실패 후 재시도·파일 누락을 검증했습니다. 완료 파일을 같은 크기의 다른 내용으로 바꾸면 현재 API가 감지하지 못하는 결함을 재현했습니다. 이를 막는 콘텐츠 해시 기록은 DB 스키마 변경 검토가 필요해 제품 코드는 수정하지 않았습니다. 현재 DB 쓰기와 실제 영상 렌더는 하지 않았습니다. [QA-01 기록](docs/handoff/qa-01-render-recovery.md)을 참고하세요.
- **QA-02 결과 무결성 설계:** 완료 시 기본·SRT·하드 자막 파일별 SHA-256을 기록하고 제공 시 다시 대조하는 정책을 제안했습니다. 해시가 없는 과거 완료 기록은 자동으로 신뢰하거나 재등록하지 않는 방안이며, 후속 DB migration과 오류 계약은 승인 전입니다. 격리 DB에서 nullable 컬럼 SQL만 시험했고 제품 코드와 현재 DB는 변경하지 않았습니다. [QA-02 설계](docs/handoff/qa-02-render-integrity-design.md)를 참고하세요.
- **QA-03 결과 무결성 구현(당시 DB 미적용):** 렌더 완료 시 기본 MP4·SRT·하드 자막 MP4의 SHA-256을 기록하고, 상태·기록·미리보기·다운로드·Range 요청마다 검증한 같은 파일 핸들로만 제공합니다. 같은 크기 변조는 409 `RENDER_FILE_CORRUPT`, 해시 없는 과거 완료 기록은 409 `RENDER_FILE_UNVERIFIED`로 차단하고 기록은 삭제하지 않으며, React가 누락·변형·무결성 기록 없음을 구분해 안내합니다. 후속 Alembic revision `e3a1c9d27b45`는 격리 PostgreSQL에서 upgrade/downgrade/reupgrade와 기존 데이터 보존을 확인했지만 **당시 개발 DB 적용과 FastAPI 교체는 승인 전**입니다. 합성 파일·Mock 검증이며 실제 렌더 MP4는 검증하지 않았습니다. [QA-03 기록](docs/handoff/qa-03-render-integrity-implementation.md)을 참고하세요.
- **QA-04 적용 전 최종 검증(CONDITIONAL PASS):** 격리 DB·합성 원본으로 실제 FFmpeg 렌더와 Docker 하드 자막을 실행해 세 파일의 SHA-256 저장, API 재초기화 후 유지, 다운로드·Range·실제 Chrome 재생, 동일 크기 변조 등의 차단과 복원을 확인했습니다. Windows에서는 스트리밍 중 파일 쓰기·교체·삭제가 거부됨을 실측했고, POSIX 보장은 더 약합니다. 적용 순서·중단 조건·롤백 계획을 정리했으며 **현재 개발 DB 적용과 FastAPI 재시작은 승인 전**입니다. Streamlit은 안전하지만 새 무결성 안내가 누락돼 최소 변경안만 제시했습니다. [QA-04 기록](docs/handoff/qa-04-pre-rollout-verification.md)을 참고하세요.
- **QA-05 적용 전 호환성 정리(CONDITIONAL PASS):** Streamlit은 QA-03 서버의 하드 자막 `CORRUPT`/`UNVERIFIED`/`BASE_UNAVAILABLE`을 형식 오류로 거부해 상태 조회 전체가 실패하던 문제를 고쳤습니다. 이제 상태를 받아들이고 409 `RENDER_FILE_CORRUPT`/`RENDER_FILE_UNVERIFIED`와 하드 자막 상태를 한국어로 구분해 안내하며, 다운로드 가능 조건은 그대로입니다. 기존 백엔드 실패 3건은 WEB-08B의 `project_render_runs` 테이블이 기대 집합에 없어서 생긴 것으로 확인했습니다. 기대값만 갱신해(완화 없음) 백엔드 593건 중 557 통과·36 건너뜀·0 실패, Streamlit 72건 통과입니다. **당시 개발 DB 적용은 승인 전**입니다. [QA-05 기록](docs/handoff/qa-05-pre-rollout-compatibility.md)을 참고하세요.
- **QA-06 실제 개발 DB 적용 준비(준비 게이트 PASS, 복구 경로 확보, 적용 승인 대기):** 개발 DB(revision `b8c01e2a4f60`, 프로젝트 13, 렌더 기록 0)를 백업했고, 격리 복원본에서 upgrade·downgrade·새 코드 기동이 무손실임을 확인했습니다. 실행 중인 8000은 커밋되지 않은 코드로 떠 있어 HEAD만으로는 재현되지 않습니다. 그래서 그 코드 트리를 재구성해 보존했고, 8000과 OpenAPI 지문이 일치함을 확인했습니다. 복구 런처로 기존 코드의 영속 모드 기동, 실제 FFmpeg 렌더, 재시작 후 이력 유지, 그리고 migration 실패·새 서버 기동 실패·렌더 실패·회귀 상황의 복구를 격리 환경에서 리허설했습니다. 해시가 있는 상태의 downgrade와 백업 복원은 데이터 손실이 있어 자동 실행하지 않습니다. **당시 실제 migration과 FastAPI 재시작은 사용자 승인 전이라 실행하지 않았습니다.** [QA-06 기록](docs/handoff/qa-06-dev-db-rollout-preparation.md)을 참고하세요.
- **DEMO-01 포트폴리오 편집 흐름(제한된 실제 검증):** 업로드 → AI 장면 추천 → 미리보기·선택 또는 자연어 요청 → 저장 → MP4 다운로드 흐름을 실제 영상 1개로 처음부터 끝까지 확인했습니다. 실제 Chrome, 격리 환경, 1.1분 소요. 장면 추천 v0.4는 짧은 근거 구간을 3~15초 장면으로 묶고 겹침을 없앱니다. 오디오 근거가 없으면 말과 화면 움직임이 겹치는 구간을 대안으로 써서, 후보가 0개이던 실제 MOV에서도 6개를 추천합니다. 추천 이유는 한국어 근거와 실제 대사로 표시합니다. 자연어 요청(길이·개수·포함/제외 단어·리액션/움직임/대화·역순)은 규칙 기반이며, 제안만 하고 저장은 사용자가 확정합니다. 시연 당시 8000에는 새 백엔드가 아직 반영되지 않았습니다(QA-06 승인 대기). 현재 8000에는 이후 P0 코드가 반영됐습니다. 추천 품질의 정량 평가는 미실행입니다. [DEMO-01 기록](docs/handoff/demo-01-portfolio-edit-flow.md)을 참고하세요.
- **WEB-09 모바일 반응형 UI:** 프로젝트 제목·ID·파일명의 좁은 화면 줄바꿈, 카드·글자 크기·간격, 스크롤 중 접근 가능한 작업 단계 이동을 개선했습니다. 320·375·390·430px 및 1440px의 모의 API Chrome 레이아웃 검사는 통과했으며, 변경 후 실제 iPhone Safari 조작·코덱 재생은 아직 확인하지 않았습니다. [WEB-09 기록](docs/handoff/web-09-responsive-ui-validation.md)을 참고하세요.
- **WEB-09B 실기기 잘림 대응:** iPhone 13 mini에서 보고된 화면 밀림을 조사했습니다. 모바일 표시 너비가 320px보다 좁아질 때 `body`의 고정 최소 너비로 문서가 넓어지는 현상을 재현해 제거하고, 단계 바의 음수 여백과 입력의 모바일 글자 크기를 조정했습니다. 모바일 Chrome 에뮬레이션에서는 300·375px 및 기존 뷰포트 회귀가 통과했지만, 수정 후 실제 iPhone Safari 재확인은 필요합니다. [WEB-09B 기록](docs/handoff/web-09b-iphone-layout-validation.md)을 참고하세요.
- **포트폴리오 화면 정리:** 좁은 화면의 단계 메뉴와 긴 상태값·버튼 줄바꿈을 보완하고, 서버에서 받은 장면 후보·진단 건수와 렌더 기록 조회 상태를 명확히 표시합니다. 기존 API와 처리·렌더 동작은 그대로이며, 이번 회귀 검증은 모의 API Chrome 기준입니다. 실제 영상·Safari 재검증은 별도입니다. [화면 점검 기록](docs/handoff/ui-portfolio-demo-validation.md)을 참고하세요.
- **새 실제 영상 처리 점검:** 한 로컬 MOV의 소스 처리는 FFprobe 실행 경로를 FastAPI 프로세스에 전달하고 명시적 재시도로 완료했다. 장면 분석의 긴 전사 근거 저장 오류는 기존 1,024자 DB 필드 안의 호환 인코딩으로 수정했다. 분석은 `ABSTAINED`로 끝나 후보가 0개라 이 영상의 편집 계획·렌더·자막 영상은 생성되지 않았다. [실행 기록](docs/handoff/scene-preview-recovery-2026-11-03.md)을 참고한다.
- **SEC-01 PostgreSQL localhost 제한:** Compose의 DB 게시 주소를 `127.0.0.1:5432`로 한정했습니다. 별도 백업·격리 복원 후 기존 볼륨과 DB 행 수, FastAPI·Vite·Tailscale HTTPS 경로를 확인했습니다. 이 PC의 Tailscale IP에서 5432 연결은 실패했으며 다른 tailnet 기기에서의 직접 접속 테스트는 미실행입니다. [SEC-01 기록](docs/handoff/sec-01-postgres-network-hardening.md)을 참고하세요.
- **아직 개발 중:** AI가 스토리·스타일을 계획하는 멀티 에이전트 편집과 최종 사용자 경험은 완성되지 않았습니다.

자세한 완료 범위와 한계는 아래 [Current Repository Status](#current-repository-status) 및 [Version Roadmap](docs/roadmap/version-roadmap.md)을 참고해 주세요.

## 초기 실험: 음성 편집 메모

초기 Baseline에서는 촬영 중 남긴 “AI야 방금 장면 꼭 살려줘” 같은 말을 찾고, 해당 시점 주변의 장면을 후보로 골라 MP4 클립으로 추출했습니다. 음성 메모는 최종 제품의 **선택 기능**이며, 이 실험이 제품 전체를 뜻하지는 않습니다.

```text
Video → Audio → STT → Timestamp → Edit Memo → Candidate Interval → Evaluation → FFmpeg → MP4
```

기능은 `Baseline → Evaluation → Failure Analysis → Improvement` 순서로 검증하며 확장합니다.

## Documentation

- [현재 서비스 명세](Doc/SPEC.md) · [제출 전 구현 계획](Doc/IMP-PLAN.md) · [현재 작업](Doc/TODO.md) · [최신 인수인계](Doc/HANDOFF.md)
- [v2 계획과 완료 기준](docs/roadmap/v2-plan.md) · [시점별 실행 보고서](docs/handoff/)
- [Cutory Full Product Design Source of Truth](docs/product/full-development-plan.md)
- [Version Roadmap](docs/roadmap/version-roadmap.md)
- [Completed v1 Detailed Plan](docs/roadmap/v1-plan.md)
- [Cutory v1 Completion](docs/roadmap/v1-completion.md)
- [Cutory v1 Foundation Evaluation](evaluation/results/cutory-v1-foundation-eval-v0.1.md)
- [Full Product Architecture](docs/architecture/full-architecture.md)
- [Full Product User Journey](docs/product/user-journey.md)
- [Product Specification](docs/product-spec.md)
- [MVP v1 Specification](docs/mvp-v1-spec.md)
- [Architecture](docs/architecture.md)
- [eval_01 End-to-End Integration Verification](docs/integration-eval01-v0.1.md)
- [Browser End-to-End Integration Verification](docs/browser-e2e-v0.1.md)
- [Project Plan](docs/project-plan.md)
- [UI / UX Design](docs/ui-design.md)
- [Evaluation Dataset v0.1](evaluation/README.md)
- [Codex Project Instructions](AGENTS.md)
- [Current Work Index](TODO.md)
- [WEB-01 구현·검증 기록](docs/handoff/web-01-react-foundation-validation.md)
- [WEB-01B 실제 백엔드 브라우저 검증](docs/handoff/web-01b-real-backend-e2e-validation.md)
- [WEB-02 장면 분석 UI 검증](docs/handoff/web-02-scene-analysis-validation.md)
- [WEB-03 편집·렌더링 UI 검증](docs/handoff/web-03-edit-render-validation.md)
- [WEB-04 두 영상 React 실제 E2E 검증](docs/handoff/web-04-react-e2e-validation.md)
- [EVAL-01 SceneCandidate 품질 평가 준비 진단](docs/handoff/eval-01-scene-candidate-quality.md)
- [EVAL-02 GT 동결 준비 및 주석 작업표](docs/handoff/eval-02-gt-freeze-preparation.md)
- [WEB-05 React·Streamlit 사용성 및 기능 공백 분석](docs/handoff/web-05-ux-gap-analysis.md)
- [WEB-06 원본·SceneCandidate 미리보기 검증](docs/handoff/web-06-source-preview-validation.md)
- [WEB-07 최종 렌더 결과 미리보기 검증](docs/handoff/web-07-render-preview-validation.md)
- [WEB-09 모바일 반응형 UI 검증](docs/handoff/web-09-responsive-ui-validation.md)
- [WEB-09B iPhone 화면 잘림 조사·수정](docs/handoff/web-09b-iphone-layout-validation.md)
- [SEC-01 PostgreSQL 포트 제한 검증](docs/handoff/sec-01-postgres-network-hardening.md)

## React 개발 화면 실행 (WEB-01)

`web/`은 React 19, TypeScript, Vite, Tailwind CSS, 필요한 shadcn/ui 방식의 컴포넌트, React Router와 TanStack Query를 사용합니다. 기존 FastAPI와 `frontend/`의 Streamlit은 그대로 유지합니다. 프로젝트 목록 API는 구현됐지만 인증·사용자 소유권 검증은 없으므로 **로컬 개발용**이며 외부에 공개 배포하지 않습니다.

Node.js 24와 pnpm 11을 준비하고, FastAPI를 `127.0.0.1:8000`에서 실행한 뒤 별도 터미널에서 다음을 실행합니다. Vite는 `127.0.0.1:5173`에 바인딩하고 `/api` 요청을 FastAPI로 프록시합니다.

개인 Tailscale 네트워크에서는 React만 Tailscale Serve의 HTTPS 443으로 전달하고 FastAPI는 localhost에 둔 적이 있습니다. 공개용 접속 절차는 [Tailscale Serve 개발 기록](docs/development/tailscale-serve.md)에 비식별화해 정리했습니다. 실제 기기 주소와 로컬 설정 파일은 공개 커밋에서 제외합니다. 현재 API에는 사용자 인증이 없어 접근 가능한 tailnet 구성원에게 프로젝트 데이터가 보일 수 있습니다.

SEC-01 이후 Compose PostgreSQL 포트는 호스트의 `127.0.0.1:${POSTGRES_PORT:-5432}`에만 게시합니다. 이전 노출 상태를 기록한 Tailscale 문서는 당시 점검 기록이며, 현재 적용·검증 결과는 [SEC-01 기록](docs/handoff/sec-01-postgres-network-hardening.md)을 따릅니다. DB의 로컬 게시 제한은 React HTTPS 접근 권한이나 API 인증을 추가하지 않습니다.

```sh
cd web
pnpm install --frozen-lockfile
pnpm dev
```

`pnpm build`, `pnpm test`, `pnpm test:e2e`로 각각 타입 검사·빌드, Vitest/React Testing Library, Chrome Playwright 브라우저 테스트를 실행합니다. 브라우저 테스트는 API 응답을 가로채 화면 동작을 검사하므로 실제 백엔드·영상 처리 통합 검증과 구분합니다. 업로드 화면은 4 GiB 이하 MOV/MP4를 먼저 확인하지만 서버의 최종 미디어 검증이 우선입니다. 처리 상태의 숫자는 서버가 반환한 건수이며 실제 처리 퍼센트로 표시하지 않습니다. 개발 환경과 검증 범위는 [WEB-01 기록](docs/handoff/web-01-react-foundation-validation.md)을 참고하세요.

좁은 화면에서는 프로젝트 상단의 5단계 링크로 영상 등록·소스 처리·장면 분석·편집/렌더 섹션으로 바로 이동할 수 있습니다. 모바일에서 링크는 스크롤 중 상단에 유지됩니다. 영상 재생은 `playsInline`과 브라우저 기본 컨트롤을 사용하지만 iPhone Safari의 자동 재생 정책과 MOV/HEVC 코덱 지원은 기기에서 별도로 확인해야 합니다.

WEB-06에서는 프로젝트 화면의 **원본 영상 미리보기**에서 등록 소스를 선택하고, 장면 후보의 **이 구간 미리보기**로 해당 원본 시각으로 이동합니다. `GET /projects/{project_id}/sources/{source_id}/media`는 로컬 접속에서만 DB 등록·프로젝트 소속·저장 경로를 검사한 뒤 MOV는 `video/quicktime`, MP4는 `video/mp4`로 Range 스트리밍합니다. 서버와 Vite를 모두 `127.0.0.1`에 바인딩하세요. 이 검사는 인증·사용자 소유권 검증이 아니며 리버스 프록시를 통한 외부 노출을 허용하지 않습니다. 기존 등록 프로젝트를 이용한 실제 재생 테스트는 `WEB06_PROJECT_ID`를 설정한 뒤 `pnpm exec playwright test --config=playwright.real.config.ts web06.spec.ts`로 실행합니다. Chrome에서 원본 코덱이 지원되지 않으면 재생 오류가 표시되며 해당 환경의 프록시 대응은 후속 검토입니다.

WEB-07 최종 결과 플레이어는 현재 프로세스의 `GET /projects/{id}/rendering`이 제공하는 **완료된 해당 렌더의 검증된 다운로드 URL**만 `<video>`에 연결합니다. 기본·자막 버전 전환과 다운로드는 별개입니다. 자막 파일이 없으면 기본 MP4만 재생합니다. 서버를 재시작해 실행 기록이 사라지면 기존 파일이 남아도 이 화면에서 다시 열리지 않습니다. 읽기 전용 기존 QA 렌더 재생을 재현하는 `backend.tests.web07_preview_fixture_server`는 테스트 프로세스의 메모리에만 완료 상태를 넣는 **검증용 도구**이며 제품의 복구 기능이 아닙니다. 해당 QA 프로젝트·렌더 ID를 `WEB07_QA_PROJECT_ID`·`WEB07_QA_RENDER_ID`로 지정하고 이 도구와 Vite를 로컬에서 실행한 뒤 `pnpm exec playwright test --config=playwright.real.config.ts web07.spec.ts web07-compat.spec.ts`로 테스트합니다. 자세한 조건과 한계는 [WEB-07 기록](docs/handoff/web-07-render-preview-validation.md)을 따릅니다.

WEB-08B의 새 영속화 경로는 기존 DB에 `b8c01e2a4f60` 마이그레이션을 적용하고, 해당 API 프로세스에 `CUTORY_RENDER_PERSISTENCE_ENABLED=1`을 지정해야 활성화됩니다. WEB-08C에서 이 로컬 개발 환경에 둘 다 적용했습니다. 테이블이 없으면 활성화된 API는 시작을 거부합니다. 활성화된 서버의 `GET /projects/{id}/renders?limit=20&before=<render_id>`는 프로젝트별 기록을 돌려줍니다. 새 완료 기록의 재시작 복구는 이 환경에서 아직 확인하지 않았습니다. 기존 QA 파일은 등록되지 않으며 작업 중단은 자동 재렌더하지 않습니다. 인증·소유권이 없어 여전히 로컬 전용입니다.

[WEB-01B 검증](docs/handoff/web-01b-real-backend-e2e-validation.md)에서는 실제 Chrome→Vite 프록시→FastAPI→PostgreSQL을 연결해 P1-S01 원본의 프로젝트 생성·업로드·소스 처리 완료와 새로고침 복구를 확인했습니다. 별도 실제 환경 테스트는 실행 중인 로컬 API·Vite가 필요하며 `cd web; pnpm test:e2e:real`로 실행합니다. 이 명령은 QA 프로젝트와 원본 사본을 새로 생성하므로 검증 기록의 범위를 먼저 확인하세요. 당시 프론트엔드 단위 테스트 10건과 모의 API 브라우저 테스트 2건이 통과했습니다.

[WEB-02](docs/handoff/web-02-scene-analysis-validation.md)에서는 장면 분석 실행·상태 조회와 후보·진단 화면을 추가했습니다. 실제 장면 분석은 처리 완료된 격리 QA 프로젝트의 ID를 `WEB02_QA_PROJECT_ID`로 지정한 뒤 `pnpm exec playwright test --config=playwright.real.config.ts web02.spec.ts`로 별도 실행합니다. ID를 지정하지 않으면 실제 분석 테스트는 건너뜁니다. 같은 분석을 불필요하게 반복하지 않도록 보고서의 준비 조건을 먼저 확인하세요. 장면 실행 상태는 서버 프로세스 메모리에서 관리되므로 재시작 후 `NOT_STARTED`로 보일 수 있지만 저장된 후보·진단은 별도로 조회합니다. 위 WEB-01B 단위·브라우저 수치는 당시 기준선이며 최신 결과는 WEB-02 보고서를 따릅니다.

[WEB-03](docs/handoff/web-03-edit-render-validation.md)에서는 순서가 있는 후보 ID의 편집 계획 저장·재조회, 렌더 접수·상태, 두 MP4 다운로드를 연결했습니다. 무효 후보와 미저장 변경사항이 있으면 저장 또는 렌더를 제한합니다. 서버 재시작 뒤 렌더 실행 기록과 다운로드 권한은 복구되지 않으므로 기존 파일 존재만으로 다운로드 가능하다고 표시하지 않습니다. 실제 브라우저 재검증은 처리·분석이 끝난 격리 QA 프로젝트에 `WEB03_QA_PROJECT_ID`를 지정하고 `pnpm exec playwright test --config=playwright.real.config.ts web03.spec.ts`로 실행합니다. 계획 저장·렌더가 DB와 출력 경로에 새 기록을 남기므로 이미 사용한 프로젝트에 임의로 다시 실행하지 마세요. 실제 API에는 SRT 다운로드가 없어 React에도 버튼이 없습니다.

[WEB-04](docs/handoff/web-04-react-e2e-validation.md)에서는 두 실제 원본의 신규 프로젝트 생성부터 두 MP4 다운로드까지 전용 Chrome·FastAPI·PostgreSQL 환경에서 검증했습니다. `web/e2e-real/web04.spec.ts`는 새 QA 프로젝트를 만들고 원본 복사본·DB 기록·렌더 파일을 남기므로 일상 회귀 명령에 포함하지 않습니다. 재실행 전 기존 프로젝트·출력 공간을 확인하세요. Windows에서 하드 자막을 켜려면 API를 **이미 Docker Desktop CLI와 엔진에 접근 가능한 로컬 사용자 세션**에서 실행하고, 같은 세션에서 `docker version`과 코드에 고정된 이미지의 로컬 존재 여부를 확인한 뒤 글꼴 해시가 일치하는 파일만 `CUTORY_SUBTITLE_FONT_PATH`에 지정합니다. FFmpeg·FFprobe와 Docker CLI 실행 경로는 해당 API 프로세스의 `PATH`에만 추가하며 `.env`, 시스템 PATH, Docker 권한이나 소켓 설정을 임의로 바꾸지 않습니다. 접근이 거부되면 기본 MP4만 성공할 수 있으므로 상태 API의 `hard_subtitle_status`를 확인하세요. 인증·사용자 소유권 검증이 없어 외부 공개 배포는 금지합니다.

## Current Repository Status

MVP-06C-2B의 Windows 합성 미디어 하드 자막 렌더 경로는 [검증 기록](docs/handoff/mvp-06c-2b-windows-validation.md)에 정리했다. 로컬 `CUTORY_SUBTITLE_FONT_PATH`에 검증된 NotoSansCJKkr-Regular.otf 경로를 설정하면 기존 `final.mp4`와 `final.srt` 옆에 별도의 `final-subtitled.mp4`를 만든다. MVP-06D에서는 기존 기본 MP4 다운로드를 유지하고, 하드 자막 MP4의 상태 조회·다운로드 및 Streamlit 선택 UI를 추가했다. [검증 범위](docs/handoff/mvp-06d-subtitle-download-validation.md)를 참고한다. MVP-07A에서는 [P1-S01 실제 영상 한 건의 API 수준 통합 검증](docs/handoff/mvp-07a-real-video-validation.md)으로 MP4·SRT·한국어 하드 자막 MP4 생성과 두 MP4의 다운로드를 확인했다. 선택 후보는 자동 추천이 아니라 촬영자 확인 구간과의 겹침을 기준으로 검증 스크립트가 고른 것이다. Streamlit 실제 클릭 조작과 추천 품질의 정량 평가는 미완료이며 GT도 동결되지 않았다. [MVP-07B 원인 분석](docs/handoff/mvp-07b-root-cause-analysis.md) 이후 [MVP-07C 검증](docs/handoff/mvp-07c-stt-dependency-validation.md)에서 `av==18.1.0`을 명시하고 깨끗한 Windows 환경의 실제 WAV·P1-S01 소스 처리로 STT를 확인했다. 제품 STT 코드는 변경하지 않았다. [MVP-07D 검증](docs/handoff/mvp-07d-subtitle-spacing-validation.md)에서는 저장된 문장 원문을 이용해 SRT 단어 사이 공백을 복원하고, P1-S01의 새 격리 자막 프레임에서 `아 뭐야` 표시를 확인했다. 기존 렌더와 다운로드 API 계약은 유지했다.

아래는 구현 단계별 기록입니다. 각 기능의 검증 범위와 남은 한계는 해당 설명을 기준으로 확인해 주세요.

> Previous: **v1 — Project & Large Video Foundation: Completed**
>
> Current: **v2 Structural/Foundation Implementation Complete — Gap Closure in progress; G5-B5 media-free Validator implemented**
>
> 아래 목록은 Historical Baseline과 완료된 v1 구현 상태를 함께 구분해 기록한다. [Full Product Design](docs/product/full-development-plan.md) 전체가 구현됐다는 의미는 아니다.

- [x] 프로젝트 문제와 제품 원칙 정의
- [x] MVP v1 범위 및 평가 전략 정의
- [x] Evaluation Dataset v0.1 시나리오 설계
- [x] Test 01 촬영 및 Ground Truth 기록
- [x] FastAPI 기본 환경과 `GET /health`
- [x] `POST /videos/upload` — 업로드 파일명과 Content-Type 확인
- [x] `POST /videos/process` — 필수 fixed Window와 multipart 영상을 받아 공유 STT 모델로 End-to-End Pipeline 실행
- [x] `GET /videos/clips/{run_id}/{clip_id}` — 생성된 MP4를 검증된 UUID 경로와 `video/mp4` 응답으로 제공
- [x] Streamlit MVP — FastAPI만 호출해 영상 업로드, 수동 Window 선택, Transcript·EditMemo·Candidate·MP4 확인
- [x] MOV/MP4 업로드 검증 및 UUID 파일명 기반 로컬 저장
- [x] ffprobe 기반 기본 미디어 정보 조회
- [x] FFmpeg 오디오 추출 — 로컬 영상의 첫 오디오 스트림을 16 kHz mono PCM WAV로 안전하게 생성
- [x] faster-whisper `small` 기반 한국어 STT Baseline — 실제 `eval_01.wav`에서 segment 및 word timestamp 검증
- [x] 규칙 기반 편집 메모 탐지 — trigger 음가 정규화·제한적 유사도와 reference/action 순서 조건 사용
- [x] EditMemo 시점 기반 5·10·15·30초 고정 구간 Scene Candidate 생성
- [x] 2.0초 초과 침묵 기반 Transcript Block 생성 및 최신 block Scene Candidate 선택
- [x] Provider 독립적 의미 기반 Block Selector Schema와 deterministic 검증 계층
- [x] OpenAI `gpt-6-luna` Responses API용 Semantic Block Selector 구현 — 실제 eval_01~05 API 평가는 미실행
- [x] Gemini `gemini-3.5-flash` Structured Outputs용 Semantic Block Selector 구현 — 실제 eval_01~05 API 평가는 미실행
- [x] Ground Truth 대비 IoU·Coverage·구간 경계 오차 계산
- [x] FFmpeg 기반 MP4 클립 생성 — H.264/AAC 재인코딩 및 실제 `eval_01.MOV` 5초 Candidate 검증
- [x] MVP End-to-End application service — probe, 오디오 추출, STT, 메모 탐지, 명시적으로 주입된 Scene Selector와 클립 렌더링을 순차 실행
- [x] Cutory v1 PostgreSQL 개발 기반 — PostgreSQL 17.11 Compose, SQLAlchemy 2.x Engine/Session과 분리된 DB 테스트
- [x] Cutory v1 Product Data Model — Project, SourceVideo, ProcessingStage, Transcript, EditMemo와 최초 Alembic revision
- [x] Cutory v1 Source Ingestion — Project별 로컬 Original Storage, SourceVideo persistence, SHA-256 fingerprint와 PENDING stage 초기화
- [x] Cutory v1 Source Processing — 기존 Probe·Audio·STT·Memo 서비스를 SourceVideo/ProcessingStage와 연결하고 결과를 PostgreSQL에 단계별 영속화
- [x] Cutory v1 Source Resume — 결과 유효성 기반 Resume, 명시적 Retry/Reprocess, stale RUNNING 복구와 downstream invalidation
- [x] Cutory v1 Project Processing — 다중 Source 선택·순차/제한 동시 처리, 완료 결과 재사용과 부분 실패 집계
- [x] Cutory v1 Project API — Project/Source 등록, 202 processing 시작과 PostgreSQL 기반 진행 상태 조회
- [x] Cutory v1 Foundation Evaluation — 120 synthetic Source와 480 Stage의 scale/state/failure 검증
- [x] Cutory v1 Completion — Completion Gate, 한계와 v2 handoff 문서화
- [x] Cutory v2 Scene Data Foundation — SceneCandidate/Evidence/Relation, EventGroup membership와 Scene 전용 WorkItem/Attempt schema
- [x] Cutory v2 Internal Tool Layer — resource ID 기반 Probe·Audio·STT·Memo adapter, safe `ToolResult`와 opaque temporary audio reference
- [x] Cutory v2 Video Editing MCP Server — stdio transport와 `probe_video` 단일 공개 capability
- [x] Cutory v2 Memo-guided Scene Discovery deterministic baseline — persisted EditMemo에서 bounded proposal, 선택/abstain, 검증, Candidate/Evidence 영속화
- [x] Cutory v2 Autonomous Scene Discovery deterministic baseline — transcript/audio/visual/quality cheap signal, cross-modal promotion, partial failure와 Evidence 영속화
- [x] Cutory v2 Selective Text LLM — deterministic selector가 해결하지 못한 bounded Memo Proposal만 OpenAI Structured Outputs로 선택하거나 abstain하고 Python manifest validator와 별도 semantic WorkItem/Attempt로 검증·영속화
- [x] Cutory v2 deterministic Event Grouping baseline — explicit cheap blocking으로 Candidate pair를 축소하고 exact duplicate Relation, conservative accepted-relation grouping, unassigned와 incremental processing을 영속화
- [x] Cutory v2 Scene Resume / Reprocess — Work result contract, Candidate result-link, modality별 fingerprint, targeted invalidation, explicit retry/stale recovery와 incremental Event update
- [x] Cutory v2 Shot Structure deterministic baseline — FFmpeg `scdet` 기반 hard-cut 구조, bounded Shot manifest, 독립 `SHOT_EVIDENCE` Work와 Candidate 보조 Evidence 구현. actual synthetic 4-fixture와 PostgreSQL 17.11/Alembic 검증 완료
- [x] Cutory v2 G4-C SceneRole scope amendment — v2는 observed Evidence를 소유하고, v3 Scene Agent hint는 optional/non-authoritative이며, v3 Edit Planner가 SceneEditPlan의 final editorial/narrative role을 결정하도록 Source of Truth 정리
- [x] Cutory v2 G5-A focused evaluation GT design review 및 G5-B1 [dataset schema/annotation guide](evaluation/datasets/cutory-v2-focused-eval-v0.1/README.md) — Memo, Autonomous, VLM, Event의 평가 규칙과 privacy/freeze 정책을 고정. 이후 P1-S01 실제 영상 API 통합 검증은 수행했으나 동결 GT와 semantic 품질 평가 결과는 아직 없음
- [x] Cutory v2 G5-B2 [controlled recording scenarios](evaluation/datasets/cutory-v2-focused-eval-v0.1/manifests/README.md) — 3 Project/18 Source 등록(촬영 계획 17개, 1개 byte copy), 촬영 지시·Event intent·coverage·privacy를 모델 실행 전에 사전 등록. 이 단계에서는 촬영·GT 주석·평가를 실행하지 않음
- [x] Cutory v2 G5-B5 [GT Validator](evaluation/validate_focused_gt.py) — Draft 2020-12 Schema와 구간·ID·관계·그룹 참조를 영상 없이 검증. 현재 P1 미동결 초안 8개는 draft PASS, 전체 freeze-ready는 GT·Proposal 참조 미완료로 PENDING

Scene Data Foundation은 discovery 결과를 저장하기 위한 persistence 기반을 제공한다. 일반 `SceneUnit`, 별도 `QualityFlag`, `SceneRole`, CandidatePriority와 Final Scene table은 만들지 않았다. 이는 SceneRole capability 삭제가 아니다. v2는 observed Evidence를 제공하고, v3 Scene Agent는 필요할 때 optional role/usage hint를 제공하며, v3 Edit Planner가 Project/EditPlan context에서 final role을 결정한다. Scene 전용 실행 상태는 완료 결과의 input/config/producer와 Work별 result contract를 검사하고, result-link가 가리키는 최신 유효 Candidate만 Event snapshot에 포함한다.

현재 v2 전체는 아직 Completed가 아니다. Gap Closure 상태는 G1 actual Text LLM evaluation 미실행(기존 `BLOCKED_NO_API_KEY` 기록의 현재 실행 조건은 재확인 필요), G2/G3 pending, G4-A/B/C 완료, G5-A review와 G5-B1 schema/guide·G5-B2 recording manifest·G5-B5 Validator 완료다. G5-B3 촬영·G5-B4 GT 주석은 일부 P1 초안이 있으나 GT는 freeze되지 않았다. 이 Windows checkout에는 실제 촬영 영상이 있으며 P1-S01 한 건의 제한된 API 통합 검증을 수행했다.

Internal Tool Layer는 기존 `probe_media`, `extract_audio`, `transcribe_audio`, `detect_edit_memos`를 다시 구현하지 않고 안전한 resource resolution과 구조화 결과 경계로 감싼다. Source Tool 입력은 UUID이며 raw path나 storage reference를 받지 않는다. 추출 WAV는 실제 workspace registry가 opaque artifact ID로 관리하고 Tool 결과에 경로를 노출하지 않는다. `ToolResult`는 한 번의 in-process 호출 결과이며 durable `SceneAnalysisWorkItem`/`SceneAnalysisAttempt`와 별개다. Tool 내부 business retry는 구현하지 않았다.

Video Editing MCP Server는 `python -m backend.app.mcp.server`로 실행하는 local-first stdio process다. 현재 공개 Tool은 `probe_video` 하나뿐이며 MCP adapter가 Internal Tool을 정확히 한 번 호출한다. MCP 응답은 allowlist media metadata, safe error와 실행 metadata만 포함하고 raw path·storage reference·stderr·credential을 제외한다. Resources/Prompts, extract_audio/STT/Memo 공개, Streamable HTTP와 Scene/Agent 기능은 아직 구현하지 않았다.

Memo-guided Scene Discovery는 persisted `EditMemo` 하나를 `MemoIntent → TemporalSearchRegion → SceneProposal[] → deterministic selection/abstain → validator`로 처리한다. production 지원은 `KEEP`과 `JUST_NOW`/`EARLIER`, same-source search로 제한한다. 선택 성공 시 기존 `SceneCandidate(MEMO_GUIDED)`와 `USER_MEMO`, `TEMPORAL_REFERENCE`, `TRANSCRIPT_MATCH`, `SEMANTIC_SELECTION` Evidence를 저장하며, 의미가 불명확하면 WorkItem/Attempt를 정상 완료하고 Candidate를 만들지 않는다. 이 경로 자체에는 LLM/VLM이나 audio/visual refinement가 없고 새 MCP Tool도 추가하지 않았다. 로컬 eval 5개가 없어 실제 historical 평가는 실행하지 않았고 synthetic focused 결과는 `evaluation/results/memo-guided-baseline-v0.1.md`에 기록한다.

Autonomous Scene Discovery는 EditMemo와 독립적으로 persisted Transcript 구조, PCM RMS activity/silence, FFmpeg grayscale frame difference/static interval을 분석한다. 단일 speech·audio·motion·quality signal은 Candidate로 승격하지 않고 reaction+audio, transcript structure+audio 또는 audio+visual이 같은 구간에서 겹치는 명시적 rule만 사용한다. Candidate confidence는 null이며 exact interval만 재사용한다. Memo Candidate와 정확히 겹치면 기존 Candidate의 provenance를 유지한 채 Autonomous Evidence를 추가하고, high-overlap 구간은 병합하지 않는다. modality partial failure는 별도 WorkItem/Attempt에 남기고 가능한 signal로 정상 completion할 수 있다. LLM/VLM 호출은 0이다. 과거 합성 Baseline 결과는 `evaluation/results/autonomous-baseline-v0.1.md`, 이후 P1-S01 실제 영상 한 건의 후보 생성 결과는 [MVP-07A 검증](docs/handoff/mvp-07a-real-video-validation.md)에 기록했다. GT가 동결되지 않아 semantic accuracy의 정량 평가는 미완료다.

Shot Structure baseline은 위 grayscale frame-difference activity와 별도다. FFmpeg `scdet`가 보고한 hard/jump-cut timestamp를 0.001초 단위로 정규화하여 `ShotBoundary`와 source 전체를 덮는 `ShotInterval` manifest를 만든다. 결과는 독립 `SHOT_EVIDENCE` WorkItem의 bounded result reference/fingerprint로 보존하고, 실제 경계가 active Candidate interval과 겹칠 때만 `SHOT_CHANGE` 보조 Evidence를 저장한다. Shot만으로 Candidate를 생성하거나 Candidate interval을 snap하지 않으며 Promotion, SceneRole, Event 판단에도 사용하지 않는다. 같은 source/config는 재사용하고 detector 설정 변경은 Shot work만 재처리한다. 4개 actual synthetic fixture에서 GT boundary 4개를 모두 검출하고 false positive 0을 기록했지만 production vlog accuracy로 일반화하지 않는다. 상세 결과는 `evaluation/results/shot-structure-baseline-v0.1.md`에 기록한다.

Selective Text LLM 경로는 기존 Memo-guided deterministic selector가 유일한 Proposal을 선택한 경우 Provider를 호출하지 않는다. Transcript Proposal이 의미적으로 경쟁하거나 `EARLIER` 의미 참조가 해결되지 않은 경우에만 bounded Memo와 Proposal snippet을 `TranscriptProposalSelector`로 전달한다. OpenAI adapter의 기본 모델은 config로 교체 가능한 `gpt-6-luna`이고, Responses API Structured Outputs 결과는 기존 Proposal ID 또는 `AMBIGUOUS`/`NO_MATCH`/`INSUFFICIENT_EVIDENCE`만 허용한다. Python validator가 ID allowlist, schema/capability와 manifest를 다시 검증하며 timestamp는 로컬 Proposal이 계속 소유한다. Provider 실패는 별도 semantic WorkItem/Attempt에만 기록되고 기존 deterministic 결과를 삭제하지 않는다. 실제 Provider 평가는 미실행이며, 과거 키 미설정 상태에서 수행한 synthetic contract와 PostgreSQL persistence 결과는 `evaluation/results/selective-text-llm-v0.1.md`에 기록한다. 현재 키의 유효성이나 평가 실행 가능 여부는 확인하지 않았다. VLM과 새 MCP Tool은 추가하지 않았다.

Deterministic Event Grouping baseline은 Project Candidate snapshot에서 bounded transcript token, Evidence type, source ordering과 exact source identity를 explicit blocking reason으로 사용해 likely pair만 만든다. 이 신호는 relation decision이 아니며 production에서 자동 생성하는 Relation은 같은 source fingerprint와 0.001초 정규화 interval이 모두 일치하는 canonical `DUPLICATE`뿐이다. EventGroup engine은 이미 accepted된 `SAME_EVENT`만 입력으로 받고, singleton·single bridge merge·multiple current membership을 금지한다. 근거가 부족한 Candidate는 정상 unassigned로 유지한다. 600 synthetic Candidate scale은 pair reduction 구조만 검증하며 실제 semantic grouping accuracy를 의미하지 않는다. LLM/VLM 호출과 새 MCP Tool은 없다.

Scene Resume/Reprocess 통합은 `scene_analysis_work_result_candidates`로 WorkItem의 현재 Candidate 결과를 명시한다. Transcript/Audio/Visual Work는 독립 fingerprint를 사용하고 Promotion은 modality result fingerprint에 의존하므로 변경되지 않은 modality와 동일한 downstream 결과를 재사용한다. FAILED retry와 stale RUNNING recovery는 명시적 호출만 허용하고, Source/Project parent row lock과 commit 전 input revalidation을 위한 경계를 제공한다. Event grouping validity에는 accepted Relation set이 포함되며 Candidate 변화가 있을 때만 caller가 incremental Event update를 요청한다. 이는 distributed queue, scheduler 또는 immutable history가 아니다.

MVP-01의 `GET /projects/{project_id}/scene-candidates`는 기존 active-result 계약으로 현재 유효한 후보만 조회한다. 후보 ID·Source ID·구간과 Evidence 유형별 개수만 반환하며 payload·원본 경로·fingerprint는 공개하지 않는다. 후보가 없으면 빈 목록이다. 이 API는 후보를 생성하거나 사용자 선택·순서 조정·최종 MP4를 제공하지 않는다. 현재 Project API 전체에는 인증과 사용자별 소유권 검증이 없으므로, 프로젝트 ID를 아는 다른 사용자로부터의 접근을 막는 제품 수준 권한 경계는 별도 구현이 필요하다.

MVP-02 Streamlit 화면은 프로젝트 ID를 입력받아 이 읽기 전용 API의 후보 순서·구간 길이·Evidence 유형/개수를 표시한다. 후보 0개는 정상 빈 상태이며 원본 미리보기, 후보 선택/정렬, 중요도 점수 또는 최종 MP4는 제공하지 않는다. 인증이 없으므로 로컬 개발용 화면이다.

MVP-03A는 v1 분석을 완료한 SourceVideo 한 건에 대해 Autonomous Discovery를 실행하는 별도 application adapter를 추가했다. 저장된 Transcript/길이를 재사용하고 원본은 SourceStorage 경유로만 열며, Scene 전용 임시 WAV를 정리한다. 결과는 기존 Scene Work/Candidate/Evidence에 저장되어 MVP-01 조회 계약을 따른다. Scene 성공·기권·실패는 v1 완료 상태와 별개다. 실제 촬영 영상에 대한 동작·정확도 검증은 아직 하지 않았다.

MVP-05M은 반응 단서 Evidence를 확인된 STT 단어 구간에만 배치해 긴 segment의 다른 Audio Activity와 잘못 결합하는 경우를 차단한다. 단어 시점이 없으면 반응 단서는 보류하며, 기존 STT/VAD 설정과 다른 후보 규칙은 유지한다. 기존 Scene 결과는 자동 삭제하지 않으며 새 분석은 별도 버전·fingerprint로 구분된다.

MVP-03B는 v1 전용 `POST /projects/{project_id}/process`를 변경하지 않고, `POST /projects/{project_id}/scene-process`로 별도 Scene 분석을 접수한다. 반환된 `status_url` (`GET /projects/{project_id}/scene-processing`)에서 접수·진행·Source별 성공/기권/실패/차단/건너뜀을 확인한 뒤, 기존 `GET /projects/{project_id}/scene-candidates`에서 유효 후보를 조회할 수 있다. v1 미완료 Source는 Scene 분석을 건너뛰며, 한 Source의 실패가 다른 Source의 결과나 v1 완료 상태를 변경하지 않는다. Scene Work/Candidate/Evidence는 DB에 남지만 프로젝트 Scene 실행 진행률·마지막 실행 결과는 **단일 프로세스 메모리에만** 있으므로 서버 재시작 뒤 `NOT_STARTED`는 이 프로세스에서 추적 중인 실행이 없다는 뜻이다. v1과 Scene 실행은 같은 단일-worker executor를 사용하며 영속 큐·분산 잠금·자동 재시도는 없다. 인증/사용자별 권한 검증과 실제 촬영 영상 정확도 검증은 아직 없다.

MVP-05F는 읽기 전용 `GET /projects/{project_id}/scene-diagnostics`와 Streamlit의 진단 보기를 추가한다. 저장된 Scene modality Work 결과에서 Source별 Evidence 개수·유형·구간, 후보 수, 안전한 경고 코드와 관측 가능한 기권 이유를 보여준다. 근거 기록이 없거나 실행 간 대응이 불명확하면 `UNKNOWN`으로 표시한다. 이 진단은 DB에 남은 분석 사실이며, 메모리 전용 실시간 실행 상태(`scene-processing`)를 대체하지 않는다. 추천 규칙·후보 조회 계약·인증 한계는 그대로다.

MVP-03C Streamlit 프로젝트 화면은 Scene 분석 접수 버튼과 수동 상태 새로고침을 제공한다. 실행 중 중복 클릭을 막고 Source별 완료·정상 기권·실패·차단·건너뜀을 구분하며, terminal 상태 조회 후 기존 유효 후보 목록을 다시 읽는다. 서버 재시작 뒤 `NOT_STARTED`를 성공/실패로 해석하지 않는다. 이 UI는 로컬 개발용이며 Scene 선택·편집·MP4 결합이나 인증은 제공하지 않는다.

MVP-04는 현재 유효한 후보 중 사용자가 사용할 장면을 선택·제외하고 순서를 정해 프로젝트별 편집 계획으로 DB에 저장한다. `GET/PUT /projects/{project_id}/scene-edit-plan`이 순서가 있는 후보 ID 목록을 조회·교체하며, 저장 시 기존 active-result 계약으로 프로젝트 소속과 유효성을 검증한다. 재분석으로 무효화된 ID는 조회 응답의 `invalid_candidate_ids`와 Streamlit 경고에 남고, 사용자가 명시적으로 해결할 때까지 다른 후보로 대체하지 않는다. 이는 사용자 선택 목록이지 v3 Edit Planner의 완성된 EditPlan이 아니다. SceneCandidate/Evidence, v1 `/process`, Scene 분석 API는 그대로이며 실제 자르기·결합·자막·최종 MP4는 아직 없다. 기존 DB에는 새 Alembic migration 적용이 필요하다. 인증/사용자별 권한 검증과 실제 영상 End-to-End 검증도 아직 없다.

MVP-05A는 저장된 장면 순서를 다시 검증한 뒤 `SourceStorage.resolve()`로 원본을 읽어 기존 개별 `render_clip()`을 재사용하고, 해상도·프레임레이트·오디오 유무를 정규화해 하나의 H.264/AAC MP4로 결합하는 백엔드 엔진이다. 임시 구간 파일은 정리하고 성공한 최종 MP4만 별도 출력 경로에 남긴다. 재분석으로 무효화된 후보, 비어 있는 계획, 원본 누락 또는 FFmpeg 실패는 명시적 오류이며 다른 후보로 대체하지 않는다. 합성 미디어로 결합을 검증했지만 실제 촬영 영상의 장시간 렌더링·품질은 아직 검증하지 않았다. 사용자용 렌더 API·Streamlit 연결·자막·인증은 MVP-05A에 없다.

MVP-05B는 `POST /projects/{project_id}/render` (202 접수), `GET /projects/{project_id}/rendering` (상태), `GET /projects/{project_id}/renders/{render_id}/download` (완료 MP4)를 추가했다. 당시 실행 상태·완료 ID 목록은 프로세스 메모리 전용이었다. WEB-08B가 구현한 DB 영속화 경로는 WEB-08C에서 현재 로컬 개발 DB/서버에 적용됐다. 기존 QA 파일은 자동 등록하지 않았고, 이 환경의 새 완료 렌더 재시작 복구는 아직 미검증이다. 실제 진행률 퍼센트와 사용자 인증·소유권 검증은 없다.

MVP-05C는 Streamlit 프로젝트 화면에서 **저장된** 편집 계획으로 렌더링을 접수하고, 수동으로 상태를 새로고침해 완료 MP4를 다운로드할 수 있게 한다. 미저장 선택·순서, 빈 계획, 무효 후보는 화면에서 실행을 막으며 백엔드도 다시 검증한다. 진행률 퍼센트나 재시작 후 상태 복구는 없고, 자동 자막·BGM·인증과 실제 촬영 영상 E2E 검증은 아직 구현·확인하지 않았다.

MVP-06B는 저장된 Transcript의 segment/word 시각과 순서가 있는 SceneCandidate 구간에서 한국어 SRT 문자열을 생성하는 **순수 로직**을 추가했다. 선택 구간만 포함하고 클립 길이를 누적한 계획상 시간축을 사용한다. 렌더링된 MP4의 실제 PTS/길이와 동기화하거나 자막을 영상에 삽입하는 기능은 아직 없다. 현재 저장형 편집 계획은 동일 Candidate의 중복 선택을 허용하지 않지만 자막 매핑 함수는 반복 입력을 처리할 수 있다.

MVP-06C-1은 자막이 있는 렌더에서 병합 영상 필터와 동일한 30fps 정규화 조건으로 클립별 영상 시간축을 측정하고, 그 실제 길이를 반영한 `final.srt`를 MP4 옆에 보관한다. 요청 구간과 출력 길이의 차이는 클립 안에서 비례 매핑하며, 최종 영상 길이와 측정값이 맞지 않거나 SRT 생성이 실패하면 **MP4는 유지하고 SRT는 생략**한다. 기존 MP4 다운로드 API는 변경하지 않았으며 SRT 다운로드·영상 내 자막 삽입은 아직 없다.

End-to-End Pipeline은 선택 Window를 자동 판단하지 않는다. 호출자가 `FixedWindowSceneSelector(window_seconds=...)`처럼 선택 전략과 값을 명시해야 하며, Ground Truth와 Evaluator는 사용자 실행 경로에 포함하지 않는다.

### MVP Backend Integration

실제 `eval_01.MOV`를 `VideoProcessingPipeline.process()` 한 번으로 처리해 STT, EditMemo 탐지, 명시적 5초 Candidate 선택과 H.264/AAC MP4 생성을 완료했다. 상세 결과는 [End-to-End Integration Verification](docs/integration-eval01-v0.1.md)에 기록한다.

FastAPI는 lifespan에서 faster-whisper 모델을 한 번 로드해 재사용하고, `/videos/process`의 blocking Pipeline을 단일 동시 실행 semaphore와 threadpool에서 처리한다. 처리 응답은 로컬 절대 경로 대신 안전한 clip ID·파일명·상대 `download_url`을 제공하며, 다운로드 endpoint는 `outputs/api/<run-id>/clips/` 아래 MP4만 반환한다.

Streamlit MVP는 backend service를 직접 import하지 않는 HTTP client다. 사용자가 5·10·15·30초 Window를 직접 선택하며 AI가 최적 길이를 자동 선택하지 않는다. 실시간 progress/SSE는 아직 구현하지 않았다.

실제 브라우저에서 Streamlit → FastAPI → VideoProcessingPipeline → MP4 재생 흐름을 검증했다. 실행 결과와 검증 범위는 [Browser End-to-End Integration Verification](docs/browser-e2e-v0.1.md)에 기록한다.

원본 테스트 영상은 개인정보와 용량 문제로 Git에 포함하지 않습니다.

## Local PostgreSQL Foundation

Cutory v1은 Product table을 추가하기 전에 PostgreSQL 17.11, SQLAlchemy 2.x와 Alembic을 사용하는 개발 기반을 먼저 구성한다. 현재 DB 연결은 기존 Baseline API startup과 분리되어 있으므로 PostgreSQL을 실행하지 않아도 기존 `/health`와 영상 처리 기능을 사용할 수 있다.

PowerShell에서 로컬 DB를 준비하고 연결을 확인한다.

```powershell
Copy-Item .env.example .env
# .env의 POSTGRES_PASSWORD를 로컬 전용 값으로 변경한다.
docker compose up -d postgres
$env:RUN_DATABASE_INTEGRATION_TESTS = "1"
.\.venv\Scripts\python.exe -m unittest backend.tests.integration.test_postgresql_connection -v
.\.venv\Scripts\python.exe -m alembic current
```

`.env`는 Git에서 제외된다. `compose.yaml`은 Docker named volume을 사용하므로 PostgreSQL data directory가 저장소에 생성되지 않는다. 최초 Product revision은 `projects`, `source_videos`, `processing_stages`, `transcripts`, `edit_memos`를 생성한다. 로컬 PostgreSQL에서 upgrade, schema inspection, downgrade와 re-upgrade를 검증했다. 기존 단일 영상 Baseline은 DB startup을 강제하지 않으며, v1 Product application/API 경로가 별도로 PostgreSQL을 사용한다.

## Product Original Source Storage

Product source ingestion은 원본 MOV/MP4 binary를 저장소 루트의 `storage/originals/projects/<project-id>/sources/` 아래 UUID 파일명으로 저장하고, PostgreSQL `source_videos`에는 원본 파일명, machine-independent 상대 resource reference와 SHA-256 fingerprint만 기록한다. 파일 저장과 동시에 fingerprint를 계산하며, 같은 Project의 동일 fingerprint는 식별 정보로 반환하되 자동 거부하지 않는다. 등록된 SourceVideo는 `READY`, PROBE·AUDIO_EXTRACTION·STT·MEMO_DETECTION stage는 `PENDING`으로 시작한다.

이 경로는 기존 단일 영상 Baseline의 `uploads/`와 분리되어 있고 Git에서 제외된다. ingestion은 Project API와 Product processing 경로에서 사용되며, Resume/Retry/Reprocess까지 연결됐다. Object Storage는 아직 구현하지 않았다.

## Product Source Processing

`process_source()` application service는 등록된 SourceVideo 하나를 Original Storage reference로 해석한 뒤 기존 Media Probe → Audio Extraction → faster-whisper STT(`word_timestamps=True`) → Memo Detection 서비스를 순서대로 호출한다. 각 ProcessingStage는 `PENDING → RUNNING → COMPLETED` 또는 `FAILED`를 별도 commit하고, media metadata는 SourceVideo에, timestamp가 포함된 STT 결과는 Transcript에, 탐지 결과는 EditMemo에 저장한다. 오류 필드에는 stage별 안전한 code/message만 기록한다.

추출 WAV는 `temporary/projects/<project-id>/sources/<source-id>/audio/` 아래에만 생성하고 성공·실패 후 source workspace를 정리한다. Original source는 삭제하지 않는다. 기존 `VideoProcessingPipeline`과 HTTP API는 Baseline regression 경로로 그대로 공존하며, Product 경로는 명시적 Resume/Retry/Reprocess, multi-source Project runner와 Project API를 제공한다.

## Source Resume, Retry and Reprocess

Product Source processing은 Stage의 `COMPLETED`만 신뢰하지 않고 source fingerprint, 필수 Product 결과, 선택적으로 지정된 config/tool/result version을 함께 검사한다. `resume_source()`는 유효한 완료 Stage를 재사용하고 필요한 downstream만 실행한다. WAV는 temporary-by-default이므로 STT를 다시 실행해야 할 때 AUDIO를 dependency recreation attempt로 다시 기록하며 장기 보존하지 않는다. 원본 전체 SHA-256 재검사는 매 resume에 강제하지 않고 명시적인 integrity verification에서만 수행한다.

`retry_source_stage()`는 FAILED Stage를 한 번 명시적으로 재실행하고 선택적 `max_attempts`로 호출자가 retry 한도를 제공할 수 있다. 자동 retry loop와 기본 횟수는 아직 없다. `reprocess_source_from()`은 지정 Stage부터 현재 Transcript/EditMemo를 교체하고 downstream을 다시 실행한다. RUNNING은 일반 resume에서 중복 실행하지 않으며, heartbeat가 없는 현재 구조에서는 `started_at`과 호출자 cutoff를 사용하는 explicit stale recovery 뒤에만 retry할 수 있다. Stage 시작은 DB row lock과 상태 재확인으로 보호하지만 distributed lock을 보장하지 않는다.

## Product Project Processing

`process_project()`는 Project의 SourceVideo를 `created_at + id` 순서로 조회하고 Step 6의 `resume_source()`를 재사용한다. 유효한 완료 Source는 다시 실행하지 않고 `REUSED`, FAILED Source는 자동 retry 없이 보존하며, RUNNING Stage가 있는 Source는 명시적 stale recovery 전까지 `BLOCKED`로 남긴다. 한 Source 실패는 뒤 Source 처리를 중단하지 않으며 최종 Project 상태와 완료·실패·차단·잔여 수를 PostgreSQL 상태에서 집계한다.

동시성은 `max_concurrency`로 제한하고 기본값은 1이다. 병렬 실행을 명시하면 Source마다 독립 SQLAlchemy Session을 사용하지만, faster-whisper 공유 모델의 동시 호출 안전성과 자원 사용량은 아직 평가하지 않았으므로 기본값을 높이지 않았다. Project runner 자체는 동기 application service이며 자동 retry/stale recovery와 queue/worker는 포함하지 않는다.

## Product Project API

Project 기반 제품 흐름은 다음 HTTP API로 노출된다.

- `POST /projects` — Project 생성
- `GET /projects/{project_id}` — Project 정보와 처리 집계 조회
- `POST /projects/{project_id}/sources` — MOV/MP4 Source 하나 등록
- `POST /projects/{project_id}/process` — 처리를 in-process executor에 요청하고 `202 Accepted` 반환
- `GET /projects/{project_id}/processing` — PostgreSQL 기반 Project/Source/Stage 진행 상태 조회

처리 시작 요청은 전체 영상 처리가 끝날 때까지 HTTP 연결을 유지하지 않는다. lifespan이 소유하는 단일-worker executor가 기존 `process_project()`를 실행하며 shared faster-whisper 모델을 재사용한다. 같은 프로세스 안에서 동일 Project의 중복 실행 요청은 `409 Conflict`로 거부한다. 이 registry는 distributed lock이 아니며 executor 작업도 durable queue가 아니다. 프로세스가 종료돼도 PostgreSQL의 Project/Source/Stage 상태는 유지되므로 상태 조회와 사용자 재요청의 기반은 남지만, startup 자동 resume는 아직 없다.

응답은 allowlist DTO만 사용하며 storage reference, fingerprint 원문, 로컬 경로와 Transcript 본문을 포함하지 않는다. Project DB 환경변수가 없는 경우 Product API는 안전한 `503`을 반환하지만 기존 단일 영상 Baseline API startup과 실행은 계속 가능하다.

## Run the Current API

```powershell
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload
```

실행 후 `/health`에서 현재 API 상태를 확인할 수 있습니다.

별도 터미널에서 Frontend를 실행합니다.

```powershell
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py
```

Backend 주소를 바꾸려면 `BACKEND_URL` 환경변수를 설정합니다. 기본값은 `http://127.0.0.1:8000`입니다.
