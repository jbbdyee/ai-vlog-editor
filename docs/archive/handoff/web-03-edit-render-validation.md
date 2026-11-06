# WEB-03 — React 편집 계획·렌더링·다운로드 UI 검증

## 범위와 보호 상태

- 2026-10-26 Windows `main`, 작업 시작 HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. WEB-01~02 코드는 아직 미커밋 상태에서 이어서 작업했다.
- 기존 미커밋 백엔드 테스트 3개(`test_clip_download_api.py`, `test_project_render_api.py`, `test_project_rendering.py`), MVP-07B 다중 클립 보고서 및 이전 WEB 문서를 보존했다. 원본 영상·GT·Manifest·기존 렌더 출력과 Streamlit, 백엔드 계약·알고리즘은 수정하지 않았다. 커밋·Push도 하지 않았다.
- 루트 `SPEC.md`와 `IMP-PLAN.md`는 없다. 제품 범위 문서인 `docs/product/full-development-plan.md`·`docs/roadmap/v2-plan.md`를 변경하지 않고 현재 UI 상태를 `README.md`·`TODO.md`에 반영했다.
- 인증·사용자 소유권 검증이 없는 로컬 개발 화면이다. 프로젝트 ID와 렌더 ID 연결 검사는 사용자 인증이 아니다. 공개 배포는 검증하지 않았고 허용하지 않는다.

## 구현과 실제 API 계약

| 기능 | 기존 FastAPI 계약 | React 처리 |
| --- | --- | --- |
| 계획 조회·저장 | `GET/PUT /projects/{id}/scene-edit-plan`; 요청 `candidate_ids: UUID[]`, 응답에 `invalid_candidate_ids`; 무효·중복 409, 없는 프로젝트 404 | 후보 선택·해제·위/아래 순서 변경, 미저장 상태 표시, 저장 실패 시 로컬 선택 보존. 무효 ID를 그대로 표시하고 사용자의 명시적 해결 전까지 저장·렌더 차단 |
| 렌더 실행·조회 | `POST /projects/{id}/render` 202 접수, 중복·무효 계획 409, 그 외 검증 오류 422; `GET /projects/{id}/rendering`의 `NOT_STARTED/QUEUED/RUNNING/COMPLETED/FAILED`, 결과와 안전 오류 코드 | 저장된 유효 계획에서만 실행. 접수와 완료 분리, 활성 실행 중 2초 폴링, 실패·재시작 기록 소실 안내. 서버가 주지 않는 진행률 퍼센트 미표시 |
| 두 MP4 다운로드 | `GET /projects/{id}/renders/{render_id}/download`와 `/subtitled/download`; 200 `video/mp4`, 파일 누락 404, 미완료 409 | 같은 프로젝트·현재 완료 렌더 ID와 일치하는 서버 제공 URL 및 `download_available` 플래그를 함께 확인. 기본 영상과 한국어 하드 자막 영상을 구분하고, HTTP·MIME·빈 응답 오류를 표시 |

TanStack Query 키는 프로젝트 ID별이다. 후보 재조회는 WEB-02 Query와 같은 키를 사용한다. 새로고침 때 저장 계획과 현재 서버 실행 상태를 다시 읽는다. 장면 재분석으로 사라진 후보는 현재 후보 목록과 `invalid_candidate_ids`를 교차 확인한다. 오래된 ID를 자동 삭제하거나 대체하지 않는다. 새 렌더 접수 중에는 이전 결과 다운로드를 숨기고, 완료 결과에는 해당 렌더 ID를 표시한다. 현재 서버의 마지막 완료 렌더가 현재 편집 계획과 다를 수 있다는 안내도 붙인다. 서버 재시작 후 결과 파일이 남아도 프로세스 메모리의 완료 기록이 사라지면 API 다운로드는 불가능하다. SRT 다운로드 API가 없어 버튼을 만들지 않았다.

## 검증 환경과 결과

- React Vite `127.0.0.1:5173` → 프록시 → FastAPI `127.0.0.1:8000` → 기존 PostgreSQL 17.11. Windows Python 3.12.15, 번들 FFmpeg/FFprobe 9.0.2, 기존 Docker 이미지 `lscr.io/linuxserver/ffmpeg@sha256:1f9755c920d41b30c4630eb6d54ac4d9badc4f5b0ca3e7f495a98d00e8020c3a`, Docker 엔진 29.9.2를 확인했다. 로컬 NotoSansCJKkr-Regular.otf SHA-256 `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a`를 API 프로세스의 `CUTORY_SUBTITLE_FONT_PATH`에만 지정했다. `.env`는 변경하지 않았다. 외부 LLM/VLM 키는 프로세스 범위에서 비우고 모델 다운로드를 오프라인으로 제한했다.
- 실제 입력은 기존 격리 QA 프로젝트 `c6782332-b2bf-4e48-956a-33bc127670fc`에 등록·분석된 `evaluation/data/P1/P1_S01_take01.MOV` 한 건이다. 원본 141,327,567바이트, SHA-256 `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2`. 파일을 다시 업로드하거나 원본을 변경하지 않았다. 이 영상은 개발 사례이며 독립 추천 품질 검증 자료가 아니다.
- 첫 실제 Chrome 실행에서 계획 저장과 렌더 API 202·기본 MP4 생성은 성공했다. 0.733333초 H.264/AAC MP4와 SRT가 남았다. 하드 자막은 `SUBTITLE_RENDER_FAILED`였다. 일반 실행 셸에서 Docker CLI 실행이 `Access denied`로 거부됨을 재현했다. 또한 테스트가 매우 짧은 렌더의 버튼을 완료 이후에도 비활성으로 기대해 실패했다. 이 기대를 실제 상태에 맞게 수정했다. 첫 결과 디렉터리 `outputs/projects/projects/c6782332b2bf4e48956a33bc127670fc/renders/0cd4484bcaa54c99972a507fd1506237/`는 보존했다.
- Docker 실행이 가능한 로컬 API 프로세스로 재시작한 뒤 **새 렌더 ID** `f72511d4-a756-4c88-a399-4ff72cc893a9`를 사용해 다시 검증했다. Chrome에서 후보 `4.64–4.84초`, `5.54–6.12초`를 명시적으로 선택·저장하고 새로고침 후 순서 복구를 확인했다. 계획 GET과 읽기 전용 DB `project_scene_edit_plan_items` 조회 모두 선택한 두 후보의 순서 `0, 1`을 확인했다. 렌더 POST는 202, 최종 상태는 `COMPLETED`, 기본·자막 다운로드 가능 플래그는 모두 true였다. 첫 렌더 디렉터리는 그대로 존재한다.
- 새 산출물은 `outputs/projects/projects/c6782332b2bf4e48956a33bc127670fc/renders/f72511d4a7564c88a3994ff72cc893a9/`에 있다. `final.mp4` 65,134바이트 SHA-256 `1769af0e9562a5ac68be07009191957f3f955e7c741e106cbd4bc50c586132cb`; `final-subtitled.mp4` 64,788바이트 SHA-256 `8c3edc4aec855f9abae1382643523121cda319fc4c2a2ec77263e185b01bc839`. 둘 다 FFprobe에서 0.783333초, H.264 영상 + AAC 오디오를 확인했다. `final.srt`는 0.000–0.167초 `아`, 0.167–0.733초 `아 뭐야`이며 최종 영상 길이를 넘지 않는다. 0.4초 프레임에서 하드 자막의 `아 뭐야` 표시를 눈으로 확인했다. 프레임 파일은 Git 제외 검증 경로에만 둔다. 전체 자막 품질이나 추천 품질 평가로 일반화하지 않는다.
- 실제 API의 두 다운로드는 200·`video/mp4`. Playwright Chrome에서 기본 `final.mp4`와 하드 자막 `final-subtitled.mp4`를 클릭해 받아, 각각 직접 API 응답 본문과 다운로드 파일의 SHA-256 일치를 확인했다. 첫 실패 렌더에서는 기본 영상만 사용 가능하고 자막 다운로드는 불가능했다. 서버 재시작 후 과거 렌더의 API 다운로드 권한 복구는 기존 백엔드 계약상 지원되지 않는다.

| 검증 종류 | 결과 | 범위 |
| --- | --- | --- |
| TypeScript 검사·Vite 빌드 | 통과 | `pnpm build` |
| Vitest/React Testing Library | 22건 통과, 실패 0 | 기존 15 + WEB-03 7. 선택·정렬·저장 실패 보존·무효 ID·중복 차단·렌더 오류·자막 누락·다운로드 응답 검사·프로젝트 분리 |
| 모의 API Chrome Playwright | 5건 통과, 실패 0 | 기존 3 + WEB-03 2. 계획 저장·새로고침·렌더·두 다운로드·다른 프로젝트·무효 계획. 영상 바이트는 모의이며 실제 렌더 검증으로 세지 않음 |
| 실제 Chrome + FastAPI + PostgreSQL | 최종 1건 통과 | WEB-03의 별도 `web03.spec.ts`, 기존 P1-S01 QA 프로젝트, 실제 렌더·두 다운로드. 첫 시도는 테스트 기대 오류 및 하드 자막 환경 실패로 통과에 집계하지 않음 |

재현 시에는 별도 로컬 API·Vite를 실행하고, 아직 사용하지 않은 격리 QA 프로젝트에 `WEB03_QA_PROJECT_ID`를 지정해 `cd web; pnpm exec playwright test --config=playwright.real.config.ts web03.spec.ts`를 실행한다. 기존 프로젝트 계획과 출력 파일을 보호하기 위해 계획 또는 실행 기록이 있으면 기본적으로 테스트가 건너뛴다. 본 검증의 명시적 재시도에서만 `WEB03_ALLOW_RERENDER=1`을 사용했다. 테스트 건너뜀은 통과로 계산하지 않는다.

## 한계와 후속 작업

- 실제 영상은 P1-S01 한 건, 두 짧은 후보 연결만 확인했다. 여러 원본 클립, 긴 렌더, 다른 운영체제·브라우저, 대량 다운로드, 서버 재시작 중 실행, 무효 후보·409 충돌의 실제 브라우저 경로는 미검증이다. 해당 상태 중 일부는 모의 API 테스트에서만 확인했다.
- 백엔드 실행 기록·완료 렌더 ID는 프로세스 메모리에 있으며 서버 재시작 후 다운로드 권한이 복구되지 않는다. WEB-03은 이를 숨기지 않고 표시하며 백엔드 저장 수명주기는 변경하지 않았다.
- 타임라인 편집, 클립 세부 자르기, 실제 영상 미리보기, 자막 편집, SRT 다운로드, 인증·권한, 자동 추천 품질 순위는 구현하지 않았다. 다음 단계에서는 실제 사용자 작업 흐름과 독립 평가 자료를 확장해 검증해야 한다.
