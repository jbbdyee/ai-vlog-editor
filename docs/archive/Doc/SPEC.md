# Cutory 현재 서비스 명세

> 기준: 2026-11-04 작업 트리. 미래 제품 목표는 [Full Product Plan](../docs/product/full-development-plan.md), v2 평가 계약과 범위는 [v2 Plan](../docs/roadmap/v2-plan.md)이 관리한다. 아래의 구현·검증 표시는 이 로컬 코드와 기록에 한정한다.

## 목적과 사용자 흐름

사용자가 등록한 촬영 영상에서 장면 후보를 살펴보고 직접 선택·정렬하여 편집 계획을 저장하고, 기본 MP4와 가능한 경우 한국어 하드 자막 MP4를 만든다. 창작 선택은 사용자에게 남긴다.

| 기능 | 현재 상태 | 검증 범위·한계 |
| --- | --- | --- |
| 프로젝트 목록·생성, MOV/MP4 업로드, 소스 처리(STT 포함) | 구현 | React·FastAPI·PostgreSQL 실제 영상 제한 검증. 인증·소유권 검증 없음 |
| 장면 분석, SceneCandidate·Evidence·진단, 원본·후보 미리보기 | 구현 | 실제 Chrome·P1 일부 영상 검증. 후보는 품질 순위나 동결 GT 합격 결과가 아님 |
| VLM 화면 설명·태그·분류 | 구현 | 로컬 Ollama 모델 경로와 실사 데모의 저장 결과 확인. 설명은 모델 추론이며 정답 아님 |
| VLM 실행 상태 조회 `GET /projects/{id}/scene-vision` 재시작 후 복원 | 구현·8000 반영(2026-11-05 14:31, PID 55828) | 현재 프로세스의 실행 기록이 있으면 그대로 반환(`state_source=PROCESS`). 없으면(재시작 직후 등) DB를 읽기만 해 활성 후보 중 현재 VLM 모델 결과(`VLM_SCENE_CAPTION`, `vlm:<모델>:v0.2`)가 있는 후보 수를 센다(`state_source=DATABASE`): 전부 `COMPLETED`, 일부 `PARTIAL`, 없음 `NOT_STARTED`. 실패 건수·오류 코드는 DB에 저장되지 않아 복원하지 않는다(`failed=0`). VLM 호출·DB 쓰기·migration 없음. 실제 API·5173 Chrome에서 데모 `COMPLETED` 8/8 확인. [VLM 상태 복원 기록](../docs/handoff/p1-vlm-status-restore-2026-11-05.md) |
| LLM 자연어 편집 제안 | 구현 | Ollama `gemma3:4b` 사용 사례 확인. STT 대사와 VLM 화면 근거를 구분한다. 음식·동물·풍경 등 지원하는 명시적 화면 조건은 Python이 VLM 설명·태그·분류로 최종 걸러낸다. 화면 근거가 없거나 설명이 불확실하면 빈 제안과 안내를 반환하며, 규칙 기반 fallback에도 같은 검사를 적용한다. 선택·제외·순서·길이 제약과 사용자 적용·저장 계약은 유지한다. |
| 후보 선택·순서 변경·편집 계획 저장·렌더 전 검토 | 구현 | 실제 DB 읽기·격리 저장 검증. 화면의 예상 길이는 구간 길이 합으로 실제 MP4 길이 보장 아님 |
| 기본 MP4·SRT·한국어 하드 자막 MP4, 재생·다운로드 | 구현 | 제한된 실제 영상·Chrome 검증. 자막 생성 실패 시 기본 MP4를 보존. 하드 자막은 로컬 글꼴·FFmpeg/Docker 환경에 의존 |
| SRT 다운로드 `GET /projects/{id}/renders/{render_hex}/subtitles/download` | 구현·8000 반영(2026-11-05 11:05, PID 49648) | 완료 렌더의 SRT가 기록 SHA-256과 일치할 때만 `application/x-subrip; charset=utf-8` attachment·ETag `"sha256-…"`로 제공. 누락 404 `SUBTITLE_FILE_NOT_FOUND`, 변조 409 `SUBTITLE_FILE_CORRUPT`, 해시 없음 409 `SUBTITLE_FILE_UNVERIFIED`, 미완료 409. 상태 응답 `subtitle_download_available`·`subtitle_download_url`. 단위·React 테스트, 실행 중 8000의 실제 렌더 3건 SRT 해시·ETag, 5173 Chrome 버튼 클릭 다운로드 검증. [P1 SRT 다운로드 기록](../docs/handoff/p1-srt-download-2026-11-05.md) |
| 렌더 종료 이벤트(n8n 후속 처리) | 코드 구현·격리 테스트, n8n 2.46.6 합성 이벤트 검증, 8000 미반영 | 렌더 상태의 기준은 DB. `COMPLETED`·`FAILED`·`RECONCILIATION_REQUIRED` 커밋 후에만 루프백 Webhook으로 POST(Bearer 토큰, 설정 없으면 꺼짐). 실패해도 렌더 결과·API 응답 불변. 페이로드에 경로·이름·자막 없음. 이벤트 ID `render-<render_hex>-<status>` 고정, 수신 측은 내용 비교로 중복 판단. `INTERRUPTED`는 대상 아님. [기록](../docs/handoff/n8n-render-events-design-2026-11-06.md) |
| 렌더 기록 영속화·무결성 검증 | 코드 구현 | 파일별 경로·크기·SHA-256과 상태를 확인하고 Range/다운로드에도 적용. 누락은 404, 변형 또는 해시 없는 결과는 409로 제공 차단; 기록은 보존. 적용·검증의 정확한 범위는 [HANDOFF](HANDOFF.md) 참조 |
| SceneCandidate 정량 추천 품질 | 미검증 | P1 초안 GT만 있고 freeze-ready `PENDING` 28건. 동결 GT 평가는 미실행 |

## 구조와 계약

`web/`의 React·TypeScript·Vite UI → Vite `/api` 프록시 → `backend/` FastAPI → PostgreSQL의 프로젝트·분석·편집 계획·렌더 기록이다. 원본·렌더 파일은 DB와 별도 저장 경로에 둔다. 기본 MP4·SRT 생성은 로컬 FFmpeg/FFprobe를 사용한다. 별도 한국어 하드 자막 MP4는 검증된 글꼴과 Docker CLI·엔진을 통해 고정 FFmpeg 이미지의 libass 필터로 생성하며, 로컬 FFmpeg fallback은 없다. `frontend/` Streamlit은 기존 클라이언트로 유지한다. 현재 코드와 Compose에서 Redis를 실제 작업 큐로 사용하는 경로는 확인되지 않았으므로 운영 구성으로 명시하지 않는다.

장면 후보는 관측 Evidence를 연결한 구간이다. VLM 화면 설명과 STT 대사는 서로 다른 근거다. LLM은 후보를 제안하지만 사용자가 적용·저장해야 편집 계획이 된다. AI 제안은 품질 순위나 자동 편집 완료를 뜻하지 않는다. 상세 API·오류 동작과 역사적 검증은 [README](../README.md) 및 [handoff](../docs/handoff/)를 따른다.

시각 조건 검증은 보수적인 명시 범주 어휘에 한정한다. 음식의 예로 케이크는 포함하지만 음료는 자동으로 음식으로 간주하지 않는다. VLM 추론 자체의 정확성이나 동결 GT 품질은 이 검사로 보장되지 않는다.

## 안전·제약

로컬 개발용이다. 인증·사용자 소유권 검증이 없어 공개 배포하지 않는다. 서버 환경과 원본 코덱에 따라 모바일 재생은 달라질 수 있다. 실행 중인 8000 서버에는 현재 작업 트리의 P0 추천 이유·무음 확인·시각 조건 수정이 반영됐다. 포트폴리오 캡처의 프레임 대기 수정은 실제 Chrome에서 확인했고, 새 8000의 자연어 제안은 실사 데모로 확인했다. 같은 `Pro` 계정의 격리 합성 입력에서 Docker 하드 자막 생성·한글 프레임은 확인했지만, 이번 서버 교체 후 새 실사 영상의 API 렌더·전체 자막 품질은 미검증이다.
