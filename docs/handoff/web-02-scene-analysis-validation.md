# WEB-02 — 장면 분석·SceneCandidate·Evidence 화면 검증

## 범위와 기준

- 2026-10-26 Windows, `main` HEAD `1a2d7d71c4c2bbdc8d01a917227cd176d7fc7843`. WEB-01/01B는 미커밋 상태에서 이어서 작업했다.
- 기존 미커밋 `backend/tests/test_clip_download_api.py`, `backend/tests/test_project_render_api.py`, `backend/tests/test_project_rendering.py` 및 미추적 `mvp-07b-multi-clip-validation.md`와 WEB-01/01B 코드·문서를 보존했다.
- FastAPI 계약·제품 장면 분석 알고리즘, Streamlit, 원본 영상, 평가 GT·Manifest, 기존 렌더 산출물은 변경하지 않았다. 인증이 없어 로컬 전용이다.
- 루트 `SPEC.md`·`IMP-PLAN.md`는 없다. 제품·v2 범위 Source of Truth는 기존 `docs/product/full-development-plan.md`·`docs/roadmap/v2-plan.md`이며 이번 React UI 상태는 `README.md`·`TODO.md`와 이 handoff에 기록한다.

## 실제 API 계약과 UI

| API | 확인한 응답 | WEB-02 처리 |
| --- | --- | --- |
| `POST /projects/{id}/scene-process` | 202, `project_id`, `accepted`, `status_url`; 활성 중 409 | 소스 처리 완료가 1개 이상일 때 실행 가능. 202는 접수만 표시하고 중복 클릭을 막음 |
| `GET /projects/{id}/scene-processing` | `run_status`, 소스 처리·완료·보류·실패·차단·건너뜀 수, 안전한 오류 코드, 소스별 결과 | `QUEUED`·`RUNNING` 중 2초 간격 조회. 완료·실패 시 중지하고 후보·진단 무효화 |
| `GET /projects/{id}/scene-candidates` | 후보 ID·소스 ID·시작/종료초·`modality/evidence_type/count` 목록 | 원본 소스명·ID, 구간·길이, 연결 근거 요약 표시. 후보 점수·추천 순위는 표시하지 않음 |
| `GET /projects/{id}/scene-diagnostics` | 소스 상태, 기록 여부, 후보 수·보류 사유, Evidence 집계·종류·시간 구간·주의 | 주요 값 카드 표시, `null`은 미확인으로 구분, 원본 응답의 소스별 상세를 펼침 |

TanStack Query 키는 프로젝트 ID별로 분리했다. 새로고침 때 네 API를 다시 읽고, 프로젝트를 바꾸면 장면 컴포넌트를 다시 만들어 이전 실행의 로컬 상태를 섞지 않는다. 기존 프로젝트·소스 화면과 같은 다크 테마를 사용한다. 분석 진도 퍼센트와 자동 추천 품질을 만들지 않았다. 후보가 0개이거나 요청이 실패하면 별도 안내를 보여 준다. 소스 처리가 미완료된 일부 영상은 장면 분석에서 건너뛸 수 있다고 안내한다.

`scene-processing` 상태는 **서버 프로세스 메모리**의 실행 기록이다. 재시작하면 `NOT_STARTED`로 돌아갈 수 있다. SceneCandidate·진단은 DB에서 별도로 읽으므로 화면에서 실행 상태와 저장 결과를 독립적으로 보여 준다. `NOT_STARTED`를 과거 분석 결과가 없다는 뜻으로 해석하지 않는다.

## 테스트 결과

- `pnpm build`: TypeScript 검사와 Vite 프로덕션 빌드 통과.
- `pnpm test`: 15건 통과(기존 WEB-01 계열 10건 + WEB-02 5건). 접수·상태 전환·후보 재조회, 소스 처리 게이트, 0개/여러 후보, Evidence·미확인 값·원본 진단, 실패·409·연결 오류, 프로젝트 상태 분리를 확인했다.
- 모의 API Chrome Playwright `pnpm test:e2e`: 3건 통과(기존 2 + WEB-02 1). 분석 중→완료, 후보·Evidence, 새로고침, 다른 프로젝트 분리를 실제 브라우저 조작으로 확인했다. 이 3건의 API 응답은 모의다.
- 실제 API Chrome Playwright: WEB-01B 격리 프로젝트 `c6782332-b2bf-4e48-956a-33bc127670fc`의 이미 처리 완료된 P1-S01 소스를 재사용했다. 전용 FastAPI·Vite를 `127.0.0.1`에서 실행하고 외부 LLM/VLM 키를 프로세스 범위에서 빈 값으로, 모델 다운로드를 오프라인으로 설정했다. `WEB02_QA_PROJECT_ID`를 지정한 `web/e2e-real/web02.spec.ts`의 분석 실행 1건이 통과했다. 서버를 재시작한 뒤 `WEB02_AFTER_RESTART=1`로 별도 읽기 전용 1건을 실행해 `NOT_STARTED`와 저장 후보 5개가 함께 보이는 것을 확인했다. 환경변수가 없는 재현 실행의 스킵은 통과에 더하지 않는다.

실제 분석 전 `GET /scene-processing`은 `NOT_STARTED`, `GET /scene-candidates`는 0개였다. Chrome의 `POST /scene-process`는 202·`accepted=true`; 이후 서버는 `COMPLETED`, 분석한 소스 1·완료 1·보류 0·실패 0, 후보 5개, 진단 소스 1개를 반환했다. 원본 P1-S01은 [WEB-01B](web-01b-real-backend-e2e-validation.md)에서 141,327,567바이트·SHA-256 `205e4143822520183d446c154fc314f607b3c948ec2e264b37195933d89a01d2`로 검증한 개발 사례다. 이번에는 재업로드하거나 원본을 수정하지 않았다.

| 후보 구간(초) | API Evidence 요약 |
| --- | --- |
| 2.44–2.62 | AUDIO_ACTIVITY 1, VISUAL_ACTIVITY 1 |
| 4.08–4.60 | AUDIO_ACTIVITY 1, VISUAL_ACTIVITY 1 |
| 4.64–4.84 | AUDIO_ACTIVITY 1, STATIC_INTERVAL 1, TRANSCRIPT_STRUCTURE 1 |
| 5.54–6.12 | AUDIO_ACTIVITY 1, STATIC_INTERVAL 1, TRANSCRIPT_STRUCTURE 1 |
| 8.86–11.00 | AUDIO_ACTIVITY 1, STATIC_INTERVAL 1, TRANSCRIPT_STRUCTURE 1 |

읽기 전용 PostgreSQL 조회에서 이 QA 소스의 SceneCandidate 5행, 연결 SceneEvidence 13행, `AUDIO_EVIDENCE`·`TRANSCRIPT_EVIDENCE`·`VISUAL_EVIDENCE`·`AUTONOMOUS_PROMOTION` 작업 4건 및 완료 Attempt 4건을 확인했다. 진단 API는 `COMPLETED`, 후보 5개, Evidence interval 25개, warning 0개를 반환했다. 후보 생성 성공을 추천 품질 평가로 해석하지 않는다. P1-S01은 이미 개발·탐색에 사용됐고 GT가 동결되지 않아 정량 품질 합격을 선언하지 않는다.

## 한계와 WEB-03

- 실제 장면 분석은 P1-S01 QA 프로젝트 한 건만 검증했다. 다른 영상, 0개 후보의 실제 분석, 실제 분석 실패·409 동시 실행, 장시간 분석, 다른 OS/브라우저는 미검증이다. 모의 API 테스트에서만 해당 오류·빈 결과 화면을 확인했다.
- 서버 재시작 뒤 실행 상태가 초기화되는 것은 기존 API의 현재 동작이다. 장면 후보·진단은 DB 조회로 보존됨을 확인했다. 다중 서버·durable queue를 이 작업에서 추가하지 않았다.
- WEB-03에서는 기존 EditPlan 저장·렌더링 상태·기본/자막 MP4 다운로드 API를 실제 스키마에 맞춰 연결하고 별도 실제 브라우저 검증을 수행한다. 타임라인 편집·미리보기·추천 점수는 현재 구현되지 않았다.
