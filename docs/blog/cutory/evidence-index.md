# Cutory 블로그 증빙 색인

> 2026-11-05 조사. 경로는 저장소 기준 상대 경로. `(Git 제외)`는 로컬에만 있는 파일이다. 백업은 저장소 밖 별도 폴더에 있으며 경로는 공개하지 않는다.

## 1. 실제 UI 캡처 (기존 자료 재사용)

| 파일 | 내용 | 출처·상태 | 블로그 사용 |
| --- | --- | --- | --- |
| `temporary/portfolio-pdf-assets/01-project-upload.png` (Git 제외) | 프로젝트·소스 처리 완료 | 실제 8000+5173 Chrome, 2026-11-04, 실사 데모 | 가능 |
| `temporary/portfolio-pdf-assets/02-stt-vlm-scene-analysis.png` | 후보 카드: 근거 칩·화면 설명·태그·대사 | 동일 | 가능 |
| `temporary/portfolio-pdf-assets/03-natural-language-two-cakes.png` | “음식이 보이는 장면만” → 2장면·6.7초 | 동일, 저장 전 제안 | 가능(“7→2” 화면 아님) |
| `temporary/portfolio-pdf-assets/04-saved-edit-plan.png` | 저장된 계획 2장면·6.74초 | 동일 | 가능 |
| `temporary/portfolio-pdf-assets/05-preview-download.png` | 결과 재생·MP4 다운로드 버튼(SRT 버튼 이전) | 동일 | 가능 |
| `temporary/portfolio-pdf-assets/06-real-subtitled-frame.png` | 하드 자막 MP4 3.5초 프레임 | 기존 렌더에서 추출 | 가능 |
| `temporary/portfolio-video-20261104/captures/00~03-*.png` | 위 01~05의 잘리기 전 전체 화면 | 동일 원본 | 필요 시 |
| `temporary/portfolio-captures-20261103/`, `web/temporary/p0-portfolio-capture-20261103/` | 11-03 같은 화면(이전 버전) | 실사 데모 | 중복 — 사용 안 함 |
| `evaluation/tmp/portfolio-captures-20261103/02-scene-candidates.png` | v0.4 이전 0.18초 후보·진단(영상 프레임 없음) | P1 개인 촬영 프로젝트의 UI | 파일명만 보임 — 가려서 사용 검토 |
| `evaluation/tmp/portfolio-captures-20261103/01,03` | P1 촬영물 프레임 | 개인 촬영 | **사용 금지** |
| `temporary/dm-shots/*` | 춤 MOV 데모 | 개인 촬영 | **사용 금지** |
| `evaluation/tmp/web04-frame-check/*`, `evaluation/tmp/mvp-07*/` | P1 프레임 | 개인 촬영 | **사용 금지** |
| `temporary/portfolio-pdf-assets/Cutory-Demo-Thumbnail.png`, `Cutory-Demo-Highlight.mp4` | 썸네일·35초 하이라이트 | 기존 캡처 재편집(연속 녹화 아님) | 표기 후 가능 |

## 2. 이번에 확보한 자료 (`temporary/blog-cutory/`, Git 제외)

| 파일 | 내용 |
| --- | --- |
| `images/2026-11-05-render-result-srt-button.png` | 실제 Playwright 전체 화면(2026-11-05 11:05 이후 8000)에서 렌더 결과 영역만 자름. 세 다운로드 버튼. 영상은 로딩 중 |
| `images/2026-11-04-hard-subtitle-frames-a0984ae2.png` | 렌더 `a0984ae2` 하드 자막 MP4의 1.45초·4.85초 실제 프레임 |
| `evidence/2026-11-04-render-e2e-a0984ae2-summary.json` | 렌더 E2E: 세 파일 해시=DB, 다운로드 ETag, 길이, 장면 순서 MAE, 자막 프레임 |
| `evidence/2026-11-05-srt-live-api.json` | 반영 후 실제 8000 SRT API 3건 결과 |
| `evidence/2026-11-05-srt-browser-click.json` | Chrome 클릭 다운로드 3종 해시 |
| `evidence/2026-11-05-srt-inprocess-readonly.json` | 반영 전 인프로세스 읽기 전용 검증 |
| `evidence/2026-11-05-p06-api-before/after-restart.json` | P0-6 재시작 전후 API 상태(동일) |

검사: 비밀번호·토큰 문자열, 로컬 사용자 경로 없음(2026-11-05 확인).

## 3. 핵심 코드 경로·함수

| 영역 | 경로 | 함수·클래스 |
| --- | --- | --- |
| 앱 기동 | `backend/app/main.py` | `lifespan`(STT 모델, 레지스트리, 영속 모드 확인) |
| STT | `backend/app/services/stt_service.py` | `load_model`, `transcribe_audio` (faster-whisper small/CPU/int8, ko) |
| 장면 후보 | `backend/app/services/autonomous_discovery.py` | `analyze_transcript_structure`, `analyze_audio_wav`, `analyze_visual_video`, `build_promotion_manifest`, `build_scene_proposals` (v0.4) |
| 후보 조회 | `backend/app/services/project_scene_candidates.py` | `list_active_project_candidates`, `ActiveCandidateSummary` |
| VLM | `backend/app/services/vlm_scene_captioner.py` | `caption_interval`, `VLMSceneCaption`, `store_caption` |
| VLM 실행 | `backend/app/services/project_scene_vision.py` | `start_vision`, `vision_status` (상태는 메모리 보관) |
| 규칙 해석 | `backend/app/services/edit_request.py` | `parse_edit_request`, `suggest_edit`, `_stem`, `_matches` |
| LLM 해석 | `backend/app/services/llm_edit_interpreter.py` | `interpret_with_llm`, `LLMEditPlan`, `_constrained_schema`, `_apply_plan`, `_guard_visual_request`, `VISUAL_CATEGORIES` |
| 렌더 | `backend/app/services/project_rendering.py` | `render_project_edit_plan`, `_concat_command`, `probe_video_timeline`, `plan_snapshot` |
| 하드 자막 | `backend/app/services/hard_subtitles.py` | `burn_hard_subtitles`, `IMAGE` |
| 무결성 | `backend/app/services/render_integrity.py`, `backend/app/routers/verified_file_response.py` | `verify_file`, `record_output_digest`, `VerifiedFileResponse` |
| 영속 렌더 | `backend/app/services/persistent_render_execution.py` | `PersistentProjectRenderRunRegistry`, `verified_output` |
| API | `backend/app/routers/projects.py` | `get_project_rendering`, `download_project_render`, `download_project_subtitled_render`, `download_project_render_subtitles`(미커밋) |
| React | `web/src/features/edit/edit-render.tsx`, `web/src/api/edit-render.ts`, `web/src/features/scenes/scene-reasons.tsx` | `EditRender`, `downloadPath`, `fetchRenderFile`, `suggestEdit` |

## 4. 테스트 파일과 실행 명령

| 범위 | 파일 | 최근 결과(일자) |
| --- | --- | --- |
| 백엔드 전체 | `backend/tests/` | 636 OK, skip 36 (2026-11-05) |
| 자연어·VLM | `test_llm_edit_interpreter.py`, `test_edit_request.py`, `test_scene_vision.py` | 관련 24건 통과(2026-11-04 기록) |
| 장면 후보 | `test_scene_proposals.py` | 6건(DEMO-01 기록) |
| 무결성 | `test_qa03_render_integrity.py`, `test_persistent_render_api.py` | 전체 실행에 포함 |
| SRT 다운로드 | `test_srt_download_api.py` (미커밋) | 9 OK |
| Streamlit 클라이언트 | `tests/` | 72 OK |
| React | `web/src/test/*.test.tsx` (14파일) | 58 OK, `tsc -b` 오류 0 |
| 실제 Chrome | `web/e2e-real/srt-download.spec.ts`(미커밋), `demo01.spec.ts`, `qa06-apply.spec.ts`, `portfolio-capture.spec.ts` | SRT 2건 통과(2026-11-05) |

명령(저장소 루트, 로컬 Python·Node 경로는 환경에 맞게):

```
python -m unittest discover -s backend/tests -t .
python -m unittest discover -s tests -t .
cd web && npx vitest run && npx tsc -b
cd web && SRT_PROJECT_ID=<데모 프로젝트 ID> npx playwright test --config=playwright.real.config.ts srt-download.spec.ts
```

테스트 결과를 파일로 남긴 로그는 없다(결과 수치는 handoff 문서에 기록). 블로그용 터미널 캡처는 **추가 확보 필요**.

## 5. 커밋·diff

| 커밋 | 내용 | 블로그 편 |
| --- | --- | --- |
| `e17c90e`, `9ac9414` | 편집 계획 기반 MP4 렌더 엔진·API | 5 |
| `530348e`, `75f479a` | SRT 시간 매핑, 실제 렌더 시간축 SRT | 5 |
| `7393056` | Docker 하드 자막 | 5 |
| `ad01fef`, `485de9b` | STT PyAV 호환, 자막 공백 복원 | 5 |
| `4a0e797` | 렌더 기록 영속화·무결성 | 6, 7 |
| `fe9e4ea` | 장면 분석·자연어 편집·VLM(음식 게이트 포함, **일괄 추가라 수정 전 diff 없음**) | 3, 4 |
| `f6695ba` | React 편집 화면·브라우저 테스트 | 6 |
| 미커밋 | SRT 다운로드 API·React 버튼·테스트 | 6 |

## 6. 검증 기록·로그

| 기록 | 내용 |
| --- | --- |
| `Doc/HANDOFF.md` | 시간순 실행·검증 기록(음식 과포함 전후, Docker 계정, 8000 교체, 백업, 재시작, allowlist, SRT 반영) |
| `docs/handoff/demo-01-portfolio-edit-flow.md` | 후보 v0.4, 자연어 요청 최소 기능, 실제 영상 1개 E2E |
| `docs/handoff/render-e2e-8000-2026-11-04.md` | 실제 렌더 1회 E2E |
| `docs/handoff/backup-restore-2026-11-04.md` | 백업·격리 복원 |
| `docs/handoff/restart-persistence-8000-2026-11-05.md` | 재시작 후 영속성 |
| `docs/handoff/env-allowlist-8000-2026-11-05.md` | 토큰 상속·allowlist·Ctrl+Break |
| `docs/handoff/p1-srt-download-2026-11-05.md` | SRT 다운로드 구현·반영 |
| `docs/handoff/qa-03-render-integrity-implementation.md` | 무결성 설계·구현 |
| `temporary/qa07-recovery/logs/8000-*.stderr.log` (Git 제외) | uvicorn 기동·정상 종료(“Finished server process”) 로그 |
| `temporary/qa07-recovery/logs/probe-*.json` (Git 제외) | `-EnvProbe` 결과(변수 이름만) |
| 백업 폴더 `restore-check.json` (저장소 밖) | 격리 복원 테이블별 비교 |

## 7. 추가 확보 필요 (요약)

1. 프로젝트 목록 화면 최신 캡처(1편)
2. 진단 패널 실사 데모 캡처, 같은 영상 v0.3/v0.4 비교(2편)
3. LLM fallback 안내 실제 화면, VLM 프롬프트 v0.2 변경 기록(3편)
4. 음식 게이트 테스트 코드 스크린샷(4편) — 수정 전 화면·diff는 존재하지 않음
5. 같은 시각 자막 없음/있음 프레임 비교, MAX_PATH 실패 기록(5편)
6. 409 차단 실제 UI(격리 데이터 필요)(6편)
7. 테스트 실행 터미널 캡처, `-EnvProbe` 터미널 캡처(7편)
