# WEB-04 — 두 실제 영상의 React 전체 흐름 E2E 검증

## 범위와 실행 전 상태

- 실행일: 2026-10-26, Windows, `main` HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. WEB-01~03의 `web/`, `README.md`, `TODO.md`, handoff 문서는 미커밋 상태였다. 기존 미커밋 백엔드 테스트 세 파일과 `mvp-07b-multi-clip-validation.md`를 수정·스테이징하지 않았다.
- 기존 [MVP-07A](mvp-07a-real-video-validation.md)의 P1-S01 단일 영상 API 경로, [MVP-07B 다중 클립](mvp-07b-multi-clip-validation.md)의 TestClient 기술 검증, [WEB-01B](web-01b-real-backend-e2e-validation.md)·[WEB-02](web-02-scene-analysis-validation.md)·[WEB-03](web-03-edit-render-validation.md)의 단계별 브라우저 검증을 확인했다. WEB-04는 **새 프로젝트에서 두 원본을 업로드해 처음부터 끝까지 실제 Chrome UI로 수행**한 첫 실행이다. 기존 검증 프로젝트나 출력은 재실행·초기화하지 않았다.
- 원본·평가 계약·GT·Manifest·제품 FastAPI 및 렌더 알고리즘·Streamlit·의존성은 변경하지 않았다. 인증·소유권 검증은 여전히 없어 로컬 전용이다. `SPEC.md`·`IMP-PLAN.md`는 없으며 제품·v2 Source of Truth의 기능 범위는 이번에 변경하지 않았다.

## 환경과 영상

| 항목 | 실제 확인 |
| --- | --- |
| 브라우저·앱 | 로컬 Chrome Playwright → Vite `127.0.0.1:5173` 프록시 → FastAPI `127.0.0.1:8000` |
| 데이터베이스·미디어 | 기존 PostgreSQL 17.11, Windows Python 3.12.15, 번들 FFmpeg/FFprobe 9.0.2 |
| 하드 자막 | Docker Desktop Linux 엔진 29.9.2, 이미 로컬에 있던 코드 고정 FFmpeg 이미지 digest `sha256:1f9755c920d41b30c4630eb6d54ac4d9badc4f5b0ca3e7f495a98d00e8020c3a`; 새 이미지 다운로드 없음. NotoSansCJKkr-Regular.otf SHA-256 `6bcb2a0703aa137e874fc2dffa85f6c21ba9a67fa329e81b8c801663af7e992a` |
| 외부 호출 보호 | API 프로세스에서 `OPENAI_API_KEY`·`GEMINI_API_KEY`를 빈 값으로 가리고 `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` 적용. 외부 LLM/VLM·유료 API 호출 없음. 기존 `.env` 변경 없음 |

새 격리 QA 프로젝트: `d1f2c447-93dc-4d8c-bd31-5f3682c83eb7`. 대상은 `evaluation/data/P1/P1_S01_take01.MOV`와 `evaluation/data/P1/P1_S02_take01.MOV`이다. 두 원본의 촬영 관계는 기존 P1 평가 시나리오를 참고했지만 GT·Recorder Event를 후보 선택이나 합격 판정에 사용하지 않았다. 두 원본은 이미 개발·탐색에 사용된 P1 사례이므로 독립 추천 품질 평가가 아니다.

| 영상 | 원본/등록 사본 크기 | 원본·등록 사본·실행 후 원본 SHA-256 | 이번 소스 ID |
| --- | ---: | --- | --- |
| P1-S01 | 141,327,567바이트 | `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2` | `17e2f1f5-8eda-4a3c-8e0b-737b313f6ff1` |
| P1-S02 | 378,391,573바이트 | `f158d2260bd3c7b48d0d88a130d922ba0c8d20f191820ec8af0f58b1af78ce95` | `e6da369e-c15b-498e-8169-b497ec12e2ab` |

원본 SHA-256은 업로드 전후 모두 같았다. 읽기 전용 DB·SourceStorage 조회로 등록 사본 2개의 크기와 해시도 원본과 일치함을 확인했다. 프로젝트·사본·렌더는 보존하며 자동 정리하지 않는다. 원본이나 검증 프레임은 Git에 추가하지 않는다.

## 전체 사용자 흐름

재현 가능한 브라우저 실행기는 `web/e2e-real/web04.spec.ts`다. 별도 실행한 실제 Chrome 테스트 1건이 **통과**했다. 이미 존재하는 QA 프로젝트를 덮어쓰지 않도록 기본 경로는 새 프로젝트를 만든다. 실패 후 수동 재개가 필요할 때만 `WEB04_RESUME_PROJECT_ID`를 지정하며, 같은 프로젝트에서 계획·렌더를 다시 쓰기 전 상태를 확인해야 한다.

| 단계 | 실제 결과 | 확인 방법 |
| --- | --- | --- |
| 새 프로젝트 생성 | 성공 | Chrome 요청 201, 전용 프로젝트 ID로 이동 |
| 실제 MOV 2개 업로드 | 성공 | 각각 201, 서버 소스 ID·파일명 및 처리 API의 소스 수 2 확인 |
| 소스 처리 | 성공 | POST 202 뒤 GET에서 `COMPLETED`, 완료 2·실패 0. 새로고침 후 두 소스 표시 |
| 장면 분석 | 성공 | POST 202 뒤 후보 17개(S01 5, S02 12), 진단 소스 2개. 두 진단 모두 `COMPLETED`, Evidence interval 25·38개, warning 0개. 후보 생성 성공이며 추천 품질 평가는 아님 |
| 장면 선택·순서 변경 | 성공 | 각 소스의 **가장 긴 유효 후보** 하나씩 수동 선택 후 UI 위로 이동 버튼으로 S02 → S01 순서로 변경. 자동 추천 순위나 GT를 사용하지 않음 |
| 계획 저장·새로고침 | 성공 | PUT 200, GET 및 읽기 전용 DB `project_scene_edit_plan_items`의 position 0·1 일치. 새로고침 후 같은 순서 표시 |
| 렌더 접수·진행·복구 | 성공 | POST 202, 요청 직후 `RUNNING` 상태에서 Chrome 새로고침. 실행 중 버튼 비활성, 실제 중복 POST는 409. 최종 API `COMPLETED`와 새 렌더 ID 확인 |
| 두 MP4 다운로드 | 성공 | 두 API 모두 200·`video/mp4`, Chrome 클릭 파일명 `final.mp4`·`final-subtitled.mp4`, 다운로드 바이트 SHA-256과 직접 API 응답 바이트 일치 |

저장한 후보와 원본 구간은 아래와 같다. DB 저장 순서가 최종 출력 순서에 반영됐다.

| 순서 | 소스 | 후보 ID | 원본 구간 | 최종 영상 구간(측정) |
| --- | --- | --- | --- | --- |
| 1 | P1-S02 | `38dba40c-055a-4748-81ac-a350319bc3ab` | 30.68–33.92초 | 0–3.267초 |
| 2 | P1-S01 | `cd35b787-33e3-4711-a28a-72f49a83d269` | 8.86–11.00초 | 3.267–5.433초 |

## 렌더 파일·자막 시간축

렌더 ID `8328898b-9edb-45e4-9d07-4938a48ebc6c`; Git 제외 상대 경로 `outputs/projects/projects/d1f2c44793dc4d8cbd315f3682c83eb7/renders/8328898b9edb45e49d074938a48ebc6c/`.

| 파일 | 크기 | SHA-256 | 실제 검사 |
| --- | ---: | --- | --- |
| `final.mp4` | 253,677바이트 | `2d2150168971c9a8e633e68fd464f24d76833e661317cd49ec86a8cd4bae5c2d` | FFprobe: 5.433333초, H.264 영상 163프레임·AAC 오디오 5.416667초 |
| `final.srt` | 172바이트 | `a06b2722d4b34b7a23ed188724f8d6976041ebb92ea8b54d0c7a5f3286702012` | UTF-8 cue 2개, 마지막 종료 5.433초로 영상 종료를 넘지 않음 |
| `final-subtitled.mp4` | 268,513바이트 | `3b720a6e77add537c8391a0483bec4fa14fb22f487a9be73cd59598fefc6a523` | FFprobe: 5.433333초, H.264 영상 163프레임·AAC 오디오 5.416667초 |

`final.srt` 원문은 다음과 같다. 이는 저장 STT 텍스트의 자막 매핑 결과이며 전사 정확도 합격을 뜻하지 않는다.

```srt
1
00:00:00,000 --> 00:00:03,267
에이아이아 아까 물건 떨어뜨린 장면 살려줘

2
00:00:03,267 --> 00:00:05,433
에이아이아 방금 장면 살려줘
```

두 MP4의 AAC 복사 스트림 SHA-256은 모두 `e33b37a606ebc0b348c81179d97cdd3504414638969b7fd5a4cbfce521aa0012`로 동일했다. 기본·하드 자막 영상에서 1.500, 3.200, 3.350, 4.500초 표본 프레임을 추출했다. 3.200초에는 첫 소스의 한국어 cue, 3.350초에는 두 번째 소스의 cue가 나타났고 기본 영상의 같은 시각 프레임에는 자막이 없었다. 표본에서 자막이 다음 클립에 남는 현상은 보지 못했다. **정확한 경계 프레임과 전체 프레임은 검사하지 않았으므로 전체 자막 품질 합격은 선언하지 않는다.** 개인정보가 담길 수 있는 프레임은 `evaluation/tmp/web04-frame-check/`에만 보관하고 Git에서 제외했다.

기존 WEB-03 렌더의 기본·하드 자막 MP4 해시도 [이전 기록](web-03-edit-render-validation.md)의 `1769af0e…`, `8c3edc4a…`와 각각 일치해 이번 실행이 기존 렌더 파일을 바꾸지 않았음을 확인했다.

## Docker 실행 권한 분석과 안전한 재현

- WEB-03 첫 실패 API는 제한된 샌드박스 계정·실행 컨텍스트에서 시작했다. 그 환경에서는 Docker CLI 파일의 프로세스 시작 자체가 `Access denied`로 거부됐다. 기본 MP4는 완료됐지만 하드 자막 상태는 `FAILED`·`SUBTITLE_RENDER_FAILED`였다. Docker daemon 접속 실패인지 판정할 단계에도 도달하지 못한 **CLI 실행 거부**다.
- Docker 접근이 설정된 일반 로컬 사용자 세션에서는 동일 설치의 CLI가 실행됐고 `docker version`의 서버 29.9.2 및 코드 고정 이미지의 로컬 digest를 확인했다. 이 세션에서 실행한 WEB-03 재시도와 이번 WEB-04 API는 하드 자막 MP4를 만들었다. 두 컨텍스트는 계정·실행 제한이 다르다. 이 결과만으로 모든 Windows 사용자나 macOS에서 동작한다고 주장하지 않는다.
- 안전한 Windows 로컬 점검 순서: (1) API를 실행할 사용자 세션에서 `docker version`으로 CLI·daemon을 함께 확인, (2) `docker image inspect`로 코드 고정 digest가 로컬에 있는지 확인해 자동 다운로드를 피함, (3) FFmpeg/FFprobe·Docker CLI 경로와 해시가 확인된 글꼴 경로를 **해당 API 프로세스에만** 전달, (4) 실제 상태 API의 `hard_subtitle_status`와 파일을 확인. Docker 접근이 없는 프로세스에서 하드 자막이 실패하면 기본 MP4는 별도로 확인한다. 사용자에게 광범위한 관리자 권한을 주거나 Docker 소켓을 노출하는 조치는 하지 않았다.

## 오류·복구 및 테스트 수준

| 항목 | 결과·수준 |
| --- | --- |
| 백엔드 연결 실패 | 실제 API 프로세스를 종료한 뒤 Vite를 통한 Chrome에서 프로젝트 생성 연결 오류를 확인; 성공 상태로 처리하지 않음. 기존 WEB-01B의 전용 오류 테스트를 선택 실행해 1건 통과 |
| Docker 접근 부족·하드 자막 실패·기본 MP4만 생성 | WEB-03에서 실제 발생·기록된 현상과 이번 CLI 컨텍스트 비교로 원인 범위를 확인. WEB-04에서는 실제 실패 렌더를 새로 만들지 않음. React의 기본 다운로드 유지·자막 버튼 비활성은 Mock Chrome에서 확인 |
| 렌더 중 새로고침·중복 요청 | 이번 실제 Chrome/API에서 `RUNNING` 중 새로고침 후 상태 복구, 중복 POST 409 확인 |
| 잘못된·없는 렌더 ID | 이번 실제 API 읽기 요청에서 각각 422 `INVALID_RENDER_ID`, 404 `RENDER_NOT_FOUND` |
| 후보 재분석 뒤 무효 ID | 기존 후보·DB를 훼손하지 않기 위해 Mock 단위 테스트에서 활성 후보 목록을 바꿔 확인. 저장된 ID는 남고 저장·렌더가 차단됨. 실제 재분석으로 계획이 무효화되는 실행은 미실행 |
| 프로젝트 전환·다운로드 실패 | Mock Chrome에서 다른 프로젝트로 결과가 섞이지 않음, 다운로드 404 `RENDER_NOT_FOUND`를 오류로 표시함 |

WEB-04에서 재현된 제품 결함은 홈 화면이 아직 “편집 계획과 렌더링은 다음 단계”라고 안내하던 **오래된 문구**였다. `web/src/features/projects/home-page.tsx`의 안내를 현재 지원 기능에 맞게 수정하고 Mock Chrome 회귀 테스트를 추가했다. 백엔드 API·영상 알고리즘은 변경하지 않았다. `README.md`·`TODO.md`의 현재 상태와 `docs/roadmap/v2-plan.md` 첫머리의 오래된 MVP-07B 상태 문장도 실제 07C·07D 및 WEB-04 검증 수준에 맞게 정정했다. 제품 목표·v2 범위·Completion Gate는 바꾸지 않았다.

| 검증 | 결과 |
| --- | --- |
| TypeScript 검사·Vite 빌드 | 통과 |
| Vitest/React Testing Library | 전체 23건 통과, 실패 0. WEB-04 신규 1건은 재분석 뒤 무효 후보 상태 |
| 모의 API Chrome Playwright | 전체 7건 통과, 실패 0. WEB-04 신규 2건은 홈 문구·연결 오류, 자막 실패·다운로드 404·프로젝트 분리 |
| 실제 Chrome + FastAPI + PostgreSQL + FFmpeg + Docker | 새 두 영상 전체 흐름 1건 통과. 검증을 마친 뒤 백엔드를 내려 연결 실패 1건도 별도로 통과 |

건너뛴 테스트는 통과로 집계하지 않았다. 실제 영상 통합 검증은 이 프로젝트·Windows 환경의 한 실행이며 자동 추천 성능 또는 GT 대비 품질의 정량 평가가 아니다.

## 남은 범위

- P1 외 다른 실제 영상·P2/P3, 여러 줄·특수문자 자막, 전체 프레임·정확한 경계 프레임, 긴 프로젝트·큰 다운로드의 메모리 사용, 다른 OS·브라우저는 미검증이다.
- 렌더 실행 상태와 다운로드 권한은 서버 프로세스 메모리 수명에 묶여 있다. 서버 재시작 후 파일이 남아도 현재 API로 이전 결과를 다시 내려받을 수 없으며 WEB-04는 해당 백엔드 계약을 바꾸지 않았다.
- 후보 추천 품질은 GT가 동결되지 않아 평가하지 않았다. 외부 공개 배포는 인증·소유권 검증이 구현되기 전까지 진행하지 않는다.
