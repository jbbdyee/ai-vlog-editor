# Cutory 기술 블로그 시리즈 — 자료 목록

> 작성 2026-11-05. Tokenly 블로그와 별개인 **Cutory 시리즈**의 준비 자료다. 블로그 본문은 아직 쓰지 않았다. 모든 주장은 아래 근거 파일로 확인 가능한 범위에 한정한다. 근거 상세는 [evidence-index.md](evidence-index.md).

## 도식 아티팩트

- **Cutory 블로그 도식**(비공개 Claude 아티팩트, 원본 HTML `temporary/blog-cutory/cutory-blog-figures.html`): https://claude.ai/artifact/FPEpwiYsR8Xi6UPGL2mxQB — 보기 `#architecture` `#pipeline` `#hybrid` `#food-fix` `#render` `#integrity` `#ops`. 모두 **설명용 재구성**이며 각 보기에 블로그 편·캡처 추천·근거가 있다. 공유하려면 페이지의 Share 메뉴를 쓴다.

## 확보된 이미지 (2026-11-05)

편별 실제 캡처·아티팩트 캡처·실제 코드/실행 출력·실제 프레임은 Git 제외 `temporary/blog-cutory/INDEX.md`에 정리했다(출처·실제/재구성 여부·시점·주의사항 포함). 아래 편별 “미확보” 항목 중 프로젝트 목록·진단 패널·음식 게이트 코드/테스트·자막 비교 프레임·테스트/점검 터미널은 이제 확보됐다. 확보 불가 항목은 INDEX의 “확보 불가” 절을 따른다.

## 공통 원칙

- **상태 구분:** 구현 / 단위·합성 테스트 / 제한된 실제 영상 검증 / 정량 품질 평가는 서로 다르다. 정량 추천 품질 평가(동결 GT)는 **미실행**이다(freeze-ready `PENDING` 28건).
- **실제 화면 vs 재구성:** 실제 앱 캡처는 `실제 캡처`, 아티팩트 도식은 `설명용 재구성`으로 캡션에 반드시 표시한다.
- **공개 가능한 영상:** 실사 데모 원본(`cutory-demo-real-cafe-walk-vlog.mp4`)은 Pexels 무료 클립 6개와 Windows TTS 내레이션으로 만든 2차 편집물이다. 출처 표시는 의무가 아니지만 권장되므로 블로그에 크레딧을 남긴다(크레딧 원문: `temporary/cutory-demo-source-real/credits.md`, Git 제외).
- **쓰면 안 되는 이미지:** P1 촬영물(`P1_S0x_take*.MOV`), 춤 MOV, `temporary/dm-shots/`, `evaluation/tmp/web04-frame-check/`, `evaluation/tmp/mvp-07*` 프레임은 개인 촬영물이다. 블로그에 쓰지 않는다.
- **이미지 보관:** 블로그용 이미지·검증 JSON은 Git 제외 폴더 `temporary/blog-cutory/`(목록 `temporary/blog-cutory/IMAGES.md`)에 둔다. 기존 캡처는 복사하지 않고 원래 위치를 참조한다.
- **캡처에 보이는 것:** 데모 프로젝트·소스·후보 UUID와 데모 파일명이 보인다(개인정보 아님). 로컬 사용자 경로·토큰·비밀번호는 기존 캡처에서 확인되지 않았다. 새 캡처도 주소창·터미널 경로를 넣지 않는다.

## 편별 자료

### 1편. Cutory 소개와 전체 아키텍처
- **주제:** 긴 촬영 영상에서 사용자가 장면을 고르는 로컬 편집 보조 도구. React → FastAPI → PostgreSQL, STT·VLM·LLM, FFmpeg/Docker.
- **구현·검증:** React 19·Vite UI가 `/api` 프록시로 FastAPI에 연결. PostgreSQL에 프로젝트·분석·계획·렌더 기록. STT faster-whisper(small, CPU int8). 로컬 Ollama `gemma3:4b`로 LLM·VLM. 기본 MP4/SRT는 FFmpeg, 하드 자막은 Docker의 고정 FFmpeg/libass 이미지. 근거 `Doc/SPEC.md`(구조와 계약), `backend/app/main.py`(`lifespan`), `README.md` 1–40행.
- **추천 캡처:** ① `temporary/portfolio-pdf-assets/01-project-upload.png`(실제 캡처: 프로젝트·소스 완료) ② 아티팩트 `#architecture`(설명용 재구성).
- **아티팩트:** 사용(`#architecture`).
- **미확보:** 프로젝트 목록 화면(`/`) 최신 캡처 — 추가 확보 필요.
- **주의:** Redis는 요청 처리 경로에 없음 — 구성도에 넣지 않는다. 인증·소유권 검증이 없으므로 “서비스 배포”라고 쓰지 않는다(로컬·tailnet 전용). Streamlit(`frontend/`)은 이전 클라이언트로만 언급.

### 2편. 장면 후보 만들기 — STT·오디오·화면 근거를 SceneCandidate로
- **주제:** 말·소리·움직임 관측 근거(Evidence)를 겹쳐 3초 이상 장면으로 묶는 과정과, 너무 짧은 후보·0개 문제 해결.
- **구현·검증:** `autonomous_discovery.py`의 `analyze_transcript_structure`·`analyze_audio_wav`·`analyze_visual_video` → `build_promotion_manifest` → `build_scene_proposals`(승격 v0.4: 1초 간격 병합, 최소 3초, 최대 15초, 오디오 교집합이 없을 때만 대사+움직임 대안 규칙). 오프라인 비교: P1-S01 5개(0.18–2.14초) → 2개(3.0–5.6초), P1-S02 12개 → 6개, 춤 MOV 0개 → 6개. 근거 `docs/handoff/demo-01-portfolio-edit-flow.md` §1, `docs/handoff/scene-preview-recovery-2026-11-03.md`, 테스트 `backend/tests/test_scene_proposals.py`.
- **추천 캡처:** ① `evaluation/tmp/portfolio-captures-20261103/02-scene-candidates.png`(실제 캡처, v0.4 이전 0.18초 후보 — **영상 프레임 없음, P1 파일명만 보임**) ② `temporary/portfolio-pdf-assets/02-stt-vlm-scene-analysis.png`(실제 캡처, 근거 칩·대사·화면 설명) ③ 아티팩트 `#pipeline`.
- **아티팩트:** 사용(`#pipeline`).
- **미확보:** 같은 영상의 v0.3/v0.4 후보 화면 나란히 비교 캡처(현재는 서로 다른 프로젝트) — 추가 확보 필요. 진단 패널(소스별 Evidence) 실사 데모 캡처 — 추가 확보 필요.
- **주의:** 후보는 “AI 품질 순위”가 아니다. 3·1·15초는 제품 파라미터이며 GT에 맞춘 값이 아니다. 오프라인 비교는 후보 수·길이만 본 것이다.

### 3편. VLM 화면 설명과 LLM 자연어 편집 — 하이브리드 설계
- **주제:** LLM이 의미를 해석하고 Python이 명시적 제약(길이·개수·제외·순서·문자 일치)을 보장하는 구조, Pydantic 검증과 규칙 기반 fallback.
- **구현·검증:** `vlm_scene_captioner.py`(`caption_interval`, 3프레임·`VLMSceneCaption` 스키마, `store_caption`이 `VLM_SCENE_CAPTION` Evidence로 저장), `llm_edit_interpreter.py`(`interpret_with_llm`, `_constrained_schema`, `_apply_plan`, `LLMEditPlan`), `edit_request.py`(`parse_edit_request`, `suggest_edit`). API `POST /projects/{id}/edit-suggestions`(저장 없음), `POST /projects/{id}/scene-vision`. 테스트 `test_llm_edit_interpreter.py`·`test_edit_request.py`·`test_scene_vision.py`. 실사 데모 실제 Ollama 결과는 `Doc/HANDOFF.md` 2026-11-04 절.
- **추천 캡처:** ① `temporary/portfolio-pdf-assets/02-stt-vlm-scene-analysis.png`(실제 캡처: 화면 설명·태그·대사) ② `temporary/portfolio-pdf-assets/03-natural-language-two-cakes.png`(실제 캡처: 요청→제안, `ollama/gemma3:4b` 배지) ③ `temporary/portfolio-pdf-assets/04-saved-edit-plan.png`(실제 캡처: 적용·저장 후 계획) ④ 아티팩트 `#hybrid`.
- **아티팩트:** 사용(`#hybrid`).
- **미확보:** LLM 실패→규칙 기반 fallback 안내가 보이는 실제 화면 — 추가 확보 필요(현재는 단위 테스트 근거만). VLM 프롬프트 v0.1→v0.2 변경(강아지가 소로 읽힌 사례) 기록 — 문서에 남아 있지 않음, 추가 확보 필요.
- **주의:** VLM 설명은 모델 추론이며 정답이 아니다. 제안은 저장 전이고 사용자가 적용·저장해야 계획이 된다. `gemma3:4b` 단일 모델·단일 데모 영상 사례다.

### 4편. “음식이 보이는 장면만”에 7장면이 나온 문제
- **주제:** LLM 과포함의 원인(문자 일치가 0건이면 제약이 걸리지 않음)과 Python 시각 조건 게이트(`_guard_visual_request`)로 해결한 과정.
- **구현·검증:** 이전: 2026-11-03 격리 8014 API에서 `llm:ollama/gemma3:4b`가 7장면 선택, 음식 근거 없는 장면 포함(`Doc/HANDOFF.md` “2026-11-03 P0 격리 실행 검증 추가”). 원인·변경·이후: 같은 문서 “2026-11-04 명시적 화면 조건 과포함 수정” — 격리 실사 복제에서 케이크 화면 근거 2건(6.74초), 강아지·노을 2건(11.42초), 풍경 3건(13.52초). 8000 반영 후 실제 Ollama로 케이크 2건 재확인(“2026-11-04 최신 P0 코드의 8000 적용”). 코드 `backend/app/services/llm_edit_interpreter.py`의 `VISUAL_CATEGORIES`·`_guard_visual_request`(182–231행). 테스트 `test_food_visual_gate_rejects_unrelated_llm_scenes`, `test_missing_visual_evidence_returns_empty_including_rule_fallback`, `test_uncertain_or_negated_visual_caption_does_not_pass_gate`, `test_landscape_visual_gate_keeps_length_limit`.
- **추천 캡처:** ① `temporary/portfolio-pdf-assets/03-natural-language-two-cakes.png`(실제 캡처: 수정 후 2장면) ② 아티팩트 `#food-fix`(설명용 재구성, 기록 수치만 사용) ③ 테스트 코드 스크린샷(126–134행) — 추가 확보 필요.
- **아티팩트:** 사용(`#food-fix`).
- **미확보:** **수정 전 7장면 화면 캡처는 없다**(격리 API 응답만 문서에 기록). 수정 전 코드 diff도 없다 — 수정이 커밋 `fe9e4ea`(새 파일 추가)에 한꺼번에 들어가 이전 버전이 Git에 없다. 블로그에서는 “수정 전 동작은 검증 기록으로만 남아 있다”고 밝힌다.
- **주의:** 7건과 2건은 **서로 다른 실행**(수정 전 격리 8014 / 수정 후 격리·8000)이다. 기존 캡처의 “AI 선택 3개를 뺐습니다” 문구는 또 다른 실행의 결과이므로 “7→2”와 같은 화면처럼 쓰지 않는다. 다른 개체·동의어·VLM 자체 오인식·복합 조건은 미검증. 음료(라떼)는 음식으로 보지 않는 보수적 어휘다.

### 5편. FFmpeg로 영상 잇기, SRT와 한국어 하드 자막
- **주제:** 편집 계획 → 구간 추출·30fps 정규화·concat → 실제 시간축 기반 SRT → Docker libass 하드 자막. Windows 환경에서 만난 문제들.
- **구현·검증:** `project_rendering.py`(`render_project_edit_plan`, `_concat_command`, `probe_video_timeline`, `_subtitle_timeline_command`; 1280×720·30fps·48kHz), `hard_subtitles.py`(`burn_hard_subtitles`, 고정 이미지 digest). 커밋 `530348e`(SRT 시간 매핑), `75f479a`(실제 렌더 시간축 SRT), `7393056`(Docker 하드 자막), `ad01fef`(STT PyAV 호환), `485de9b`(자막 공백 복원). 실제 렌더 E2E: 렌더 `a0984ae2…` 6.767초(계획 6.74초), 장면 순서 프레임 비교, 한국어 자막 2큐 확인(`docs/handoff/render-e2e-8000-2026-11-04.md`). Docker 실행 계정 차이 조사(`Doc/HANDOFF.md` “Docker 접근 차이 원인 조사”).
- **추천 캡처:** ① `temporary/portfolio-pdf-assets/06-real-subtitled-frame.png`(실제 프레임: 케이크+한국어 자막) ② `temporary/blog-cutory/images/2026-11-04-hard-subtitle-frames-a0984ae2.png`(실제 프레임 2장: 두 자막 큐) ③ 아티팩트 `#render`.
- **아티팩트:** 사용(`#render`).
- **미확보:** 같은 시각의 자막 없는/있는 프레임 나란히 비교(실사 데모) — 추가 확보 필요. MAX_PATH(경로 226자) 실패 로그 원문 — 대화 기록에만 있고 handoff 문서에 없음, 추가 확보 필요.
- **주의:** 하드 자막은 Docker 엔진·고정 이미지·검증된 글꼴이 있어야 한다(로컬 FFmpeg fallback 없음). 자막 내용에는 STT 오인식(“대박”→“대단”)이 그대로 들어간다. 자막 전체 품질은 평가하지 않았다.

### 6편. React UI와 “검증된 파일만” 내려주는 다운로드
- **주제:** 결과 미리보기와 MP4·하드 자막 MP4·SRT 다운로드. 파일별 SHA-256 기록, 검증한 파일 핸들로만 응답, 강한 ETag, 오류 코드 구분.
- **구현·검증:** `render_integrity.py`(`verify_file`, `record_output_digest`), `routers/verified_file_response.py`(`VerifiedFileResponse`), `routers/projects.py`(`download_project_render`, `download_project_subtitled_render`, `download_project_render_subtitles`, `_render_status_response`), React `web/src/api/edit-render.ts`(`downloadPath`, `fetchRenderFile`), `web/src/features/edit/edit-render.tsx`. SRT 다운로드: 8000 반영 후 실제 API 3건 해시=DB=ETag, Chrome 클릭 `final.srt` 다운로드(`docs/handoff/p1-srt-download-2026-11-05.md`). SRT 기능은 **미커밋 작업 트리**에 있다.
- **추천 캡처:** ① `temporary/blog-cutory/images/2026-11-05-render-result-srt-button.png`(실제 캡처: 세 다운로드 버튼, 영상은 로딩 중) ② `temporary/portfolio-pdf-assets/05-preview-download.png`(실제 캡처: 재생 프레임) ③ 아티팩트 `#integrity`.
- **아티팩트:** 사용(`#integrity`).
- **미확보:** 변조 파일로 다운로드가 409로 막히는 **실제 UI 화면** — 실데이터를 바꿀 수 없어 브라우저 측 응답 변형 테스트로만 확인. 격리 데이터로 캡처하려면 별도 작업 필요(추가 확보 필요).
- **주의:** 무결성 검증은 “파일이 완료 때와 같은지”를 보는 것이지 영상 품질 검증이 아니다. 모바일 Safari는 미검증.

### 7편. 테스트·데이터 영속성·백업과 안전한 재시작
- **주제:** 렌더 기록 DB 영속화, 백업·격리 복원 검증, 서버 재시작 후 영속성, 에이전트 세션 토큰이 서버 환경 변수로 새던 문제와 allowlist 기동.
- **구현·검증:** `persistent_render_execution.py`(`PersistentProjectRenderRunRegistry`, lease·heartbeat), Alembic `e3a1c9d27b45`. 백업: DB 덤프+파일 40개 매니페스트, 격리 복원 17개 테이블 491행 md5 일치(`docs/handoff/backup-restore-2026-11-04.md`, `docs/handoff/render-e2e-8000-2026-11-04.md`). 재시작 후 영속성(`docs/handoff/restart-persistence-8000-2026-11-05.md`). 토큰 상속·Ctrl+C 무시 원인·allowlist·Ctrl+Break(`docs/handoff/env-allowlist-8000-2026-11-05.md`). 테스트 수: 백엔드 636(skip 36)·`tests/` 72·Vitest 58·Chrome 실제 2건(2026-11-05).
- **추천 캡처:** ① 테스트 실행 터미널 출력(백엔드·Vitest) — 추가 확보 필요 ② 아티팩트 `#ops` ③ `-EnvProbe` 출력(이름만 보이는 터미널) — 추가 확보 필요.
- **아티팩트:** 사용(`#ops`).
- **미확보:** 위 터미널 캡처들. 백업 폴더 구조 화면(경로 가림 필요).
- **주의:** 재시작·백업 스크립트(`temporary/qa07-recovery/`)는 Git 밖이며 이 PC 경로에 고정돼 있다 — “재사용 가능한 배포 도구”라고 쓰지 않는다. 재부팅 직후 기동·자동 시작은 미검증. 토큰 값·비밀번호·로컬 사용자 경로는 캡처에 넣지 않는다. 36건 skip은 통과가 아니다.

## 시리즈 전체에서 단정하면 안 되는 것

- “AI가 자동으로 편집한다” — 사용자 선택·적용·저장이 필요하다.
- “추천 정확도 N%” — 정량 평가 미실행.
- “VLM이 장면을 정확히 인식한다” — 모델 추론, 오인식 가능.
- “운영 배포/서비스 중” — 로컬 개발 환경, 인증 없음.
- “Redis 작업 큐” — 확인된 처리 경로에 없음.
- 시연 MP4(`temporary/portfolio-video-20261104/…mp4`, `Cutory-Demo-Highlight.mp4`)는 **기존 캡처·렌더를 편집한 영상**이지 연속 녹화가 아니다.
