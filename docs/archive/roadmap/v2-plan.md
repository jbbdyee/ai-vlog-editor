# Cutory v2 — Tool / MCP & Scene Intelligence

## 1. Status

> Status: Structural/Foundation Implementation Complete — Gap Closure in progress; Version Completion not declared
>
> Previous version: [v1 — Project & Large Video Foundation](v1-completion.md) — Completed
> Version sequence: [Cutory Version Roadmap](version-roadmap.md)
> Product direction: [Cutory Full Product Development Plan](../product/full-development-plan.md)

이 문서는 Cutory v2 구현 범위, 설계 경계, 구현 순서와 Completion Gate의 Source of Truth다. 구조·기반 코드, DB migration, API와 제한된 MCP Tool은 구현됐지만 이 문서의 모든 범위나 Completion Gate가 완료됐다는 뜻은 아니다. 세부사항이 평가 근거 없이 확정되지 않은 경우 `TBD`, `Evaluation으로 결정`, `구현 전 확정 필요`로 남긴다.

MVP-07A에서는 P1-S01 실제 촬영 영상 한 건으로 API 수준의 MP4·SRT·한국어 하드 자막 MP4 생성과 두 MP4의 다운로드를 확인했다([검증 기록](../handoff/mvp-07a-real-video-validation.md)). 촬영자 확인 구간과의 겹침으로 검증 스크립트가 후보를 선택했으며, 자동 추천 품질의 정량 평가나 Streamlit 실제 클릭 조작은 수행하지 않았다. GT는 미동결이다. [MVP-07B 원인 분석](../handoff/mvp-07b-root-cause-analysis.md) 당시에는 코드·의존성 변경이 없었고, 이후 [07C](../handoff/mvp-07c-stt-dependency-validation.md)에서 STT 의존성을 고정하고 [07D](../handoff/mvp-07d-subtitle-spacing-validation.md)에서 SRT 공백 손실을 수정했다. React WEB-01~04 로컬 화면은 [WEB-04 기록](../handoff/web-04-react-e2e-validation.md)의 P1-S01·S02 두 원본 전체 흐름까지 실제 Chrome으로 검증했지만, 이는 사용자 화면의 제한된 기술 검증이며 v2 Completion Gate나 독립 추천 품질 평가의 통과를 뜻하지 않는다.

[EVAL-01 진단](../handoff/eval-01-scene-candidate-quality.md)에서는 기존 Manifest 검사가 통과하고 현존 P1 초안 8개의 구조 검사가 통과했으나, freeze-ready는 28개 미비 항목으로 `PENDING`임을 재확인했다. WEB-04 두 소스의 후보 17개와 Evidence 연결은 읽기 전용으로 집계했다. 동결 GT 기반 Dataset B recall·tIoU와 시나리오별 품질 평가는 실행하지 않았다. 다음 순서는 독립 주석·GT 동결과 고정 출력 준비, 기존 평가 계약에 따른 비교, 실패 분석이며 후보 생성 알고리즘과 임계값은 평가 전에 변경하지 않는다.

[EVAL-02 동결 준비](../handoff/eval-02-gt-freeze-preparation.md)는 28개 미비 항목을 P2/P3 source envelope 12건, COVERED 작업 GT 13건, Project Event GT 3건의 사람 작업으로 대응시켰다. P1 원본 7개의 해시·길이를 다시 확인했지만 P2/P3 원본은 현재 checkout에 없고, 현존 P1 초안도 독립 인간 검토·승인이 없다. 주석·조정·미디어 대조·사람 승인과 고정 Proposal/Candidate 대응을 마친 뒤 기존 검사기를 재실행한다. 이번 단계에서 GT를 생성하거나 동결하지 않았으며 EVAL-01의 정량 품질 평가도 여전히 미실행이다.

[WEB-05 사용성 분석](../handoff/web-05-ux-gap-analysis.md)은 React/Streamlit/현재 API를 비교했다. React가 프로젝트 기반 업로드·처리·분석·편집 계획·렌더·두 MP4 다운로드를 제공하지만, 원본·후보·최종 결과의 화면 재생이 편집 경험의 핵심 공백이다. Streamlit의 `st.video`는 별도 레거시 단일 클립에만 적용된다. 로컬 전용 미디어 접근·안전한 후보 재생을 후속 P0로, 최종 영상 재생과 서버 재시작 뒤 렌더 조회/복구를 별도 단계로 제안한다. Streamlit 제거와 공개 배포는 보류하며, 이 분석으로 v2 제품 범위·평가 계약·완료 기준을 바꾸지 않는다.

[WEB-06](../handoff/web-06-source-preview-validation.md)에서는 로컬 전용 프로젝트·소스 미디어 Range API와 React 원본·후보 구간 미리보기를 추가했다. P1-S01·S02 HEVC MOV는 현재 Windows Chrome에서 원본 재생·seek를 제한적으로 확인했으며, 프록시 재인코딩은 추가하지 않았다. 선택 목록에는 소스명·시각·길이를 표시한다. 다른 브라우저 코덱 호환성, 프레임 정확도, 인증·소유권은 미해결이다. 이 구현은 SceneCandidate 품질 평가나 v2 Completion Gate의 통과를 뜻하지 않는다.

[WEB-07](../handoff/web-07-render-preview-validation.md)은 기존 두 렌더 다운로드 API의 MP4·Range 응답을 재사용해 React 최종 결과 플레이어를 연결했다. 기본·하드 자막 버전 전환, 로딩·오류·파일 누락 상태와 다운로드 유지가 구현됐다. 기존 WEB-04 QA 두 MP4를 **시험용 프로세스 메모리 완료 상태**에서 실제 Chrome으로 재생·seek하고 한국어 자막 프레임을 확인했다. 이는 일반 서버 재시작 뒤 결과 복구 검증이 아니며, 그 영속화는 WEB-08로 남긴다. 공개 배포·사용자별 권한·독립 추천 품질 평가는 여전히 미완료다.

[WEB-08A](../handoff/web-08a-render-persistence-design.md)는 현재 렌더 registry·편집 계획·파일 경로·다운로드 계약과 PostgreSQL/Alembic 구조를 조사해 영속화 정책을 설계했다. 제품 코드·DB 스키마는 변경하지 않았으며 일반 서버 재시작 복구는 아직 구현·검증되지 않았다. WEB-08B의 선행 조건은 기존 DB·QA 출력 백업 검증, 새 작업 ID와 계획 스냅샷의 DB 기록, 한 프로젝트의 동시 실행 방지, 작업 소유권 만료 후 중단 표시, 파일 재검증이다. 기존 파일 자동 등록과 자동 재렌더는 제외하고 격리 DB·QA 프로젝트의 단위/통합/실제 재시작 E2E를 거쳐야 한다. 이 로컬 제품 UX 단계는 v2 평가 계약이나 Completion Gate를 바꾸지 않는다.

[WEB-08B](../handoff/web-08b-render-persistence-validation.md)는 새 `project_render_runs` Alembic revision과 DB 기반 작업 ID·계획 스냅샷·상태 전이, lease와 PostgreSQL advisory lock, 파일 검증·기록 조회·React 과거 결과 선택을 구현했다. 당시 기존 DB/QA 결과의 백업과 별도 DB 복원 검증 뒤 **격리 DB·출력에서만** 마이그레이션과 실제 P1-S01·S02 렌더, API 프로세스 재시작, Chrome 기본/한국어 하드 자막 재생·seek·다운로드를 확인했다. 당시 기존 PostgreSQL은 이전 revision에 남아 있고 기존 8000 API는 재시작하지 않았다. 이후 기존 로컬 환경 적용은 WEB-08C에서 별도 승인 후 진행했으며 공개 배포·GT 품질 평가는 미완료다.

[WEB-08C](../handoff/web-08c-production-local-rollout.md)는 기존 로컬 DB의 새 백업·격리 복원과 기존 16개 테이블 행 수, 격리 DB migration 경로를 확인한 뒤 승인받아 기존 DB를 `b8c01e2a4f60`으로 업그레이드하고 FastAPI만 영속화 모드로 교체했다. 기존 데이터·원본·렌더 파일을 보존하고 새 기록 API 및 실제 Chrome의 빈 기록 화면을 확인했다. 새 렌더를 실행하지 않아 기존 환경의 완료 기록 재시작 복구는 아직 미검증이다. 기존 QA 파일은 자동 등록하지 않았다.

[WEB-10](../handoff/web-10-project-list.md)은 로컬 개발용 프로젝트 목록 API와 React 홈의 목록·선택 화면을 추가했다. DB의 프로젝트 생성일 최신순, 영상 수, 편집 계획 존재, 최신 렌더 상태를 제한된 페이지로 조회하며 새 렌더 실행·파일 자동 등록·DB 마이그레이션은 하지 않았다. 실제 Chrome+FastAPI+PostgreSQL의 목록·상세 진입 및 모바일 너비를 확인했다. 이는 인증·소유권이나 독립 SceneCandidate 품질 평가의 완료를 뜻하지 않는다.

[WEB-11](../handoff/web-11-edit-plan-ux.md)은 기존 EditPlan API와 후보 미리보기를 재사용해 React의 선택 수·상태·순서 조작과 빈 계획 저장을 개선했다. 격리 PostgreSQL의 실제 저장 후보로 저장·재조회를 확인하고 원래 계획을 복원했다. 현재 사용 중인 DB는 읽기 전용 Chrome 조작만 확인했으며 렌더·알고리즘·평가 계약은 변경하지 않았다. 장면 후보는 품질 순위가 아니다.

[WEB-12](../handoff/web-12-render-review.md)는 저장된 EditPlan 후보 순서와 각 구간 길이의 합계를 렌더 실행 전에 검토할 수 있게 했다. 미저장·저장 중·실패·빈 계획·무효 구간에서는 렌더를 차단하고 기존 편집 카드로 이동할 수 있다. React 단위·Mock Chrome 모바일/데스크톱 검증은 완료했다. WEB-12 당시 기존 DB의 실제 Chrome 읽기 전용 확인은 미실행이었으며 DEV-01에서 후속 검증했다. 실제 영상 렌더는 미실행이고 예상 길이는 실제 렌더 길이나 영상 미리보기를 보장하지 않는다.

[DEV-01](../handoff/dev-01-server-and-web12-validation.md)은 기존 FastAPI가 실제로 실행 중임을 확인하고, 기존 PostgreSQL의 저장 4장면 계획을 Chrome 375·1440px에서 읽기 전용으로 검증했다. 화면의 예상 길이 6.16초가 API 구간 합계와 일치하고 미저장 초안에서 렌더 버튼이 차단됨을 확인했다. 기존 렌더 기록은 0건이어서 과거 렌더가 있는 실제 화면은 미검증이며 새 영상 렌더는 실행하지 않았다.

[QA-01](../handoff/qa-01-render-recovery.md)은 WEB-08B의 격리 영속 렌더 경로를 일회용 PostgreSQL과 Mock 실행기로 추가 검증했다. 동시 접수·프로젝트 분리·ownerless lease 만료·실패 후 새 ID 재시도·파일 누락은 기대한 상태였다. **동일 크기로 바뀐 완료 파일은 현재 경로/크기 검증만으로 감지되지 않는 결함**이 확인됐다. 콘텐츠 해시의 영속 저장과 기존 기록 정책은 별도 DB 스키마 변경 검토가 필요하며 이 단계에서 제품 코드·현재 DB를 변경하지 않았다. 실제 프로세스 강제 종료나 새 영상 렌더도 실행하지 않았다.

[QA-02](../handoff/qa-02-render-integrity-design.md)는 이 결함에 대해 완료 시 파일별 SHA-256 기록과 조회·다운로드·미리보기 요청의 검증, 해시 없는 과거 완료 기록의 보수적 처리, 파일별 누락/손상 오류와 비용 평가를 설계했다. b8 revision 일회용 격리 DB에서 세 nullable 해시 컬럼·CHECK SQL을 시험했지만 실제 migration·제품 코드·현재 DB 적용은 하지 않았다. 구현은 스키마 변경과 호환성 정책 승인, 대용량·동시 Range 요청 비용 검증이 선행 조건이다.

[QA-03](../handoff/qa-03-render-integrity-implementation.md)은 QA-02 설계를 구현했다. 후속 revision `e3a1c9d27b45`가 세 nullable SHA-256 컬럼과 형식 CHECK를 추가하며 기존 행은 NULL로 보존한다. 영속 렌더 완료는 기본 MP4 해시를 기록하지 못하면 COMPLETED를 기록하지 않고, SRT·하드 자막 MP4는 파일별로 해시한다. 상태·기록·미리보기·다운로드·Range는 같은 정책으로 크기·SHA-256을 검증하고 검증한 핸들에서만 스트리밍한다(Windows는 공유 모드로 쓰기 거부). 누락 404, 불일치 409 `RENDER_FILE_CORRUPT`, 해시 없는 과거 기록 409 `RENDER_FILE_UNVERIFIED`로 구분하며 기록은 보존한다. 합성 파일·SQLite 23건, QA-01 격리 PostgreSQL 3건(기존 expected failure를 실제 해결 후 정상 통과로 전환), 격리 DB migration 왕복과 WEB-08C 백업 복원 데이터 보존, React 52건·Mock Chrome 22건을 확인했다. 요청마다 전체 해시하므로 대용량 결과의 Range 지연(warm 1GiB 약 0.6초/요청)이 남은 위험이며 정책을 약화하지 않았다. **현재 개발 DB 적용·FastAPI 교체·실제 렌더 MP4 검증은 미실행이고 승인이 필요하다.**

[QA-04](../handoff/qa-04-pre-rollout-verification.md)는 적용 전 최종 검증으로, 일회용 격리 DB(`head`=`e3a1c9d27b45`)와 Git 제외 임시 루트의 합성 원본에서 실제 FFmpeg 렌더·Docker 하드 자막을 실행했다. 세 파일의 SHA-256이 DB와 일치했고 API 재초기화 후에도 유지됐으며, 다운로드·Range·실제 Chrome 재생/다운로드와 동일 크기·다른 크기·누락·하드 자막·SRT·해시 없음 변조의 차단과 복원을 확인했다. Windows에서는 스트리밍 중 쓰기·교체·삭제가 OS 수준에서 거부됐고 POSIX는 제자리 수정과 Range 부분 바이트 위험이 남는다. 같은 DB를 쓰는 두 API 프로세스의 판정은 일치했다. 판정은 **CONDITIONAL PASS**이며 적용 순서·중단 조건·롤백 계획과 운영 정책 승인이 조건이다. 실제 개발 DB 적용·운영 FastAPI 재시작·실제 사용자 영상 렌더는 미실행이다.

[QA-05](../handoff/qa-05-pre-rollout-compatibility.md)는 QA-04가 남긴 호환성 항목을 정리했다. QA-04는 Streamlit 문제를 '안내 문구 누락'으로 기록했지만, 실제로는 Streamlit 클라이언트가 하드 자막 `CORRUPT`/`UNVERIFIED`/`BASE_UNAVAILABLE`을 허용하지 않아 무결성 차단 시 상태 조회 전체가 형식 오류로 실패했다. 하드 자막만 손상된 경우 정상 기본 MP4 다운로드 버튼도 사라졌다. 이를 고쳐 상태를 받아들이고, 409 무결성 코드와 하드 자막 상태를 한국어로 구분해 안내한다. 다운로드 가능 조건은 바꾸지 않았다. 기존 백엔드 실패 3건은 미커밋 WEB-08B 모델 등록으로 늘어난 `project_render_runs` 테이블 때문이었고(QA-03 무관, 보호 대상과 중복 없음), 정확한 집합 일치 검사를 유지한 채 기대값만 갱신했다. 회귀는 백엔드 0 실패, Streamlit 72건이다. 판정은 **CONDITIONAL PASS**이며, QA-04 조건 1–4가 남고 실제 개발 DB 적용은 미실행이다.

[QA-06](../handoff/qa-06-dev-db-rollout-preparation.md)은 사용자가 Windows 단일 호스트 개발 환경에 한정해 운영 정책 5개를 승인한 뒤 진행한 적용 준비 단계다. 개발 DB(`b8c01e2a4f60`, 렌더 기록 0)를 백업·격리 복원해 데이터가 일치함을 확인했고, `e3a1c9d27b45` upgrade·downgrade와 새 코드 기동이 무손실이었다. 보강 단계에서는 실행 중인 8000의 코드가 HEAD가 아닌 'HEAD + 세션 시작 시점 미커밋 변경'임을 확인하고, 그 트리를 재구성·보존했다(OpenAPI 지문 일치). 복구 런처로 기존 코드의 영속 기동, 실제 렌더, 재시작을 확인했고, migration 실패·새 서버 기동 실패·렌더 실패·회귀 상황의 복구를 격리 환경에서 리허설했다. 기존 코드는 e3 DB에서도 동작하고 새 코드는 b8 DB에서 기동을 거부한다. 해시가 있는 상태의 downgrade는 해시를 소실시키므로 자동 실행하지 않는다. 실제 migration·FastAPI 재시작·실제 렌더 검증은 사용자 승인 전이라 미실행이다.

[WEB-09](../handoff/web-09-responsive-ui-validation.md)는 React의 프로젝트 제목·UUID·파일명·선택 장면 줄바꿈과 모바일 여백·타이포그래피, 작업 단계의 스크롤 중 이동을 개선했다. 모의 API Chrome에서 320·375·390·430px 및 1440px 레이아웃과 기존 화면 기능을 검증했으나 실제 iPhone Safari 조작·코덱 재생은 후속 확인이 필요하다. 백엔드·DB·Tailscale 설정과 v2 평가 계약은 변경하지 않았다.

[WEB-09B](../handoff/web-09b-iphone-layout-validation.md)는 실제 iPhone 13 mini에서 보고된 가로 잘림을 조사했다. 모바일 표시 영역 300px 재현에서 `body`의 320px 최소 너비가 문서를 321px로 넓히는 것을 확인하고 해당 제한과 단계 바 음수 여백을 제거했다. 입력의 모바일 글자를 16px로 조정하고 등록 카드의 너비 경계를 검증했다. Chrome 모바일 에뮬레이션과 기존 화면 회귀는 통과했으나, 실제 iPhone Safari에서의 원인 확정과 수정 효과 확인은 남아 있다. 이 UI 수정은 v2 품질 평가나 백엔드 계약을 변경하지 않는다.

[SEC-01](../handoff/sec-01-postgres-network-hardening.md)은 Compose의 PostgreSQL 호스트 게시를 `127.0.0.1:5432`로 제한했다. 기존 DB의 새 백업과 별도 DB 복원, 원래 볼륨/테이블·주요 행 수 보존 및 FastAPI→Vite→Tailscale HTTPS 경로를 확인했다. 이 PC의 Tailscale IP에서 5432 접속은 차단됐고 다른 tailnet 기기 검증은 미실행이다. WEB-08B 마이그레이션은 적용하지 않았으며 이 네트워크 설정은 v2 평가 계약이나 인증 범위를 변경하지 않는다.

기존 `docs/mvp-v1-spec.md`의 “MVP v1”은 단일 영상 Baseline의 역사적 명칭이다. 이 문서의 v2는 Version Roadmap의 `Tool / MCP & Scene Intelligence`를 뜻한다.

## 2. Goal

v2의 목표는 100개 이상의 SourceVideo를 대상으로 Memo-guided와 Autonomous 두 경로에서 편집 후보 장면을 발견하고, 발견 근거와 장면 간 관계를 구조화하며, Scene Intelligence에 필요한 실행 capability를 Tool Layer와 MCP 경계로 제공하는 것이다.

```text
Project
→ SourceVideo[]
→ v1 Processing: MediaInfo / Transcript / EditMemo
→ Scene Intelligence
   ├─ Memo-guided Discovery
   └─ Autonomous Discovery
→ SceneCandidate + SceneEvidence + QualityFlags
→ SceneRelation
→ EventGroup
```

v2는 최종 브이로그 편집 Version이 아니다. 결과는 v3의 Scene Agent, Style Agent, Edit Planner와 Orchestrator가 사용할 구조화 기반이다. v2는 “영상에서 무엇이 관측되었는가”를 bounded Evidence와 Candidate/Relation으로 만들고 평가 가능한 상태로 보존하지만, 최종 narrative·timeline·creative decision이나 authoritative SceneRole을 내리지 않는다.

## 3. v1에서 이어받는 기반

v1에서 구현·검증된 다음 자산을 다시 만들지 않고 재사용한다.

- Project, SourceVideo, ProcessingStage, Transcript, EditMemo
- PostgreSQL, SQLAlchemy 2.x, Alembic
- Project별 Local Original Source Storage와 resource reference
- SHA-256 source fingerprint와 result validity metadata
- Media Probe, Audio Extraction, faster-whisper STT, Memo Detection
- Source ingestion과 Project/Source processing application boundary
- Resume, Retry, Reprocess, stale `RUNNING` recovery, downstream invalidation
- Project runner, Partial Failure, bounded concurrency, Session isolation
- FastAPI Project API와 DB-backed processing status
- Original Source와 Temporary Workspace lifecycle 분리

현재 저장소에는 SceneCandidate, SceneEvidence, SceneRelation, EventGroup의 Product persistence가 구현돼 있다. 일반 SceneUnit, 별도 QualityFlag, final Scene entity는 아직 구현하지 않았다. `scene_boundary_proposals`, transcript block retrieval, 과거 semantic selectors·audio/visual refiners·Gemini/Ollama VLM selector의 실험 결과는 historical baseline으로 보존하며, 이를 평가 없이 production truth로 승격하지 않는다.

v1 background execution은 in-process executor이며 durable queue가 아니다. v2는 v1의 durable DB state와 manual resume 철학을 확장하되, distributed queue/worker 도입을 자동 전제로 삼지 않는다.

## 4. Scope

v2 범위는 다음과 같다.

### Scene Intelligence data foundation

- SceneUnit, SceneCandidate, SceneEvidence, QualityFlag의 표현과 lineage
- SceneRelation과 한 단계 EventGroup
- logical work item, attempt, producer/version/config 기반 result validity
- Source/Project 경계를 넘지 않는 안전한 resource reference

### Discovery

- EditMemo 기반 Memo-guided Scene Discovery
- Memo 유무와 독립적으로 실행되는 Autonomous Scene Discovery
- Transcript, Audio, Visual, Shot Structure Evidence
- proposal generation, semantic selection, deterministic validation
- candidate merge/deduplication과 conflict preservation
- authoritative SceneRole assignment가 아닌 관측 가능한 semantic/technical Evidence

### Cost-aware analysis

- Cheap deterministic analysis
- Candidate Reduction과 priority
- 선택된 구간만 LLM/VLM으로 심층 분석
- provider-independent capability와 failure taxonomy

### Execution boundary

- 의미 있는 capability 중심 Tool Layer
- 단일 Video Editing MCP Server
- resource ID, validation, structured result, safe error와 execution reference
- v1 service 재사용과 새 Scene service의 명확한 경계

### Reliability and evaluation

- Scene work-item 수준 persistence, Resume, Retry, Reprocess, stale recovery
- dependency lineage와 targeted invalidation
- Memo/Autonomous/Reduction/AI/Event/Reliability 평가
- focused, project, scale dataset의 목적별 분리

## 5. Non-goals

다음은 v2 범위가 아니며 구현 단계에서도 앞당기지 않는다.

- LangGraph 전체 orchestration
- Scene Agent 전체 판단 loop
- Style Agent, Edit Planner, Orchestrator
- Creative Agent, Reviewer Agent
- Caption 생성·적용, BGM 선택·적용, Color Grading
- 최종 Vlog 구성과 Final Render product flow
- Shorts/Reels와 Final Mobile Frontend
- RAG와 장기 Style Memory
- production deployment 최적화
- Agent 간 자유 대화 또는 Multi-Agent workflow
- Project/EditPlan context에 따른 authoritative SceneRole assignment

MCP를 구현한다는 사실은 Agent나 Multi-Agent를 구현한다는 뜻이 아니다. v2 MCP Client는 Scene Intelligence application 경계에서 Tool capability를 호출할 수 있으며, v3 Agent가 같은 capability contract를 재사용할 수 있게 한다.

## 6. Core Principles

1. **사용자 의도 우선**: Explicit User Intent인 EditMemo는 일반 heuristic score와 단순 평균하지 않는다.
2. **Evidence ≠ Decision**: audio spike, motion, transcript hit는 근거이지 좋은 장면이라는 최종 판단이 아니다.
3. **Candidate ≠ Final Scene**: v2는 검토 가치가 있는 후보를 발견한다. 최종 편집 선택은 후속 Version 책임이다.
4. **Observed Evidence ≠ Editorial Role**: reaction cue, location view, shot change와 quality signal은 관측 근거다. 최종 role은 v3 Planner의 EditPlan context에서 결정한다.
5. **Cheap → Expensive**: 전체 원본을 같은 비용으로 AI Provider에 보내지 않는다.
6. **Proposal ID selection**: AI가 authoritative timestamp를 자유 생성하지 않는다.
7. **Deterministic validation**: interval, resource ownership, proposal mapping과 실행은 일반 코드가 검증한다.
8. **Capability over provider**: business logic을 Gemini, Ollama/Qwen 등 특정 Provider에 결합하지 않는다.
9. **Structured intermediate result**: Evidence, status, version, lineage와 failure를 보존한다.
10. **Incremental and resumable**: 유효한 결과를 재사용하고 영향받은 downstream만 재계산한다.
11. **Local-first and minimal disclosure**: 전체 MOV/WAV의 외부 전송을 기본 금지하고 선택된 최소 context만 전송한다.
12. **Baseline → Evaluation → Failure Analysis → Improvement**: threshold와 모델은 평가 전에 성공을 보장하는 방향으로 조정하지 않는다.

## 7. Target Architecture

```text
Frontend / Future Mobile Client
              |
              v
      FastAPI Product API
              |
              v
Scene Intelligence Application Services
  |-- Memo-guided Discovery
  |-- Autonomous Discovery
  |-- Candidate Reduction / Merge
  |-- Relation / Event Grouping
  |-- Persistence / Resume / Reprocess
  |
  +-------- MCP Client ----------------------+
              |                              |
              v                              |
     Video Editing MCP Server                |
              |                              |
              v                              |
          Tool Layer                         |
  |-- Media / Transcript / Audio             |
  |-- Visual / Scene / Validation            |
              |                              |
              v                              |
Existing v1 Services + New v2 Services       |
FFmpeg / STT / OpenCV / selective AI Provider
              |
              +------------------------------+

PostgreSQL: entity, relation, state, lineage, result reference
Original Storage: source lifetime binary
Temporary Workspace: WAV, frame, contact sheet, analysis artifacts
```

FastAPI는 Client ↔ Cutory Product 경계다. MCP는 Cutory AI/Application ↔ Execution Capability 경계다. LangGraph는 v3 이후 workflow orchestration 후보이며 v2 architecture에 구현된 것으로 가정하지 않는다.

## 8. Scene Intelligence Data Model

이 절은 conceptual model이다. exact table, column, index, enum과 migration 단위는 **구현 전 확정 필요**다.

### 8.1 SceneUnit

SceneUnit은 분석을 수행하는 시간 구간 단위다. transcript block, shot interval, fixed interval, audio/visual proposal envelope 등에서 만들어질 수 있다.

- 모든 SceneUnit이 편집 후보는 아니다.
- 같은 source의 여러 분석기가 겹치는 SceneUnit을 만들 수 있다.
- SceneUnit의 boundary는 분석 입력 경계이며 최종 Scene boundary를 의미하지 않는다.
- 저장 여부, 생성 단위와 장기 보존 정책은 **TBD**다. 재생성 비용과 lineage 필요성을 구현 전에 평가한다.

### 8.2 SceneCandidate

SceneCandidate는 편집 후보로 검토할 가치가 있다고 발견된 구간이다.

개념 필드 후보:

- `id`
- `source_video_id`
- `start_seconds`, `end_seconds`
- `discovery_method`
- `confidence`
- `created_at`
- input/result validity와 lineage reference

Discovery method 후보는 `MEMO_GUIDED`, `TRANSCRIPT`, `AUDIO`, `VISUAL`, `MULTIMODAL`이다. exact enum은 Evaluation으로 조정하며 구현 전에 확정한다. Candidate에 판단 근거 전체를 JSON으로 몰아넣지 않고 SceneEvidence와 연결한다.

SceneCandidate와 향후 validated/final Scene entity를 분리할지는 **Evaluation으로 결정**한다. v2에서 필요성이 확인되기 전 final Scene entity를 미리 만들지 않는다.

### 8.3 SceneEvidence

SceneEvidence는 Candidate가 왜 생성·유지·축소·관계화됐는지 설명하는 독립 근거다.

개념 필드 후보:

- `id`, `scene_candidate_id`
- `modality`, `evidence_type`
- `start_seconds`, `end_seconds`
- `confidence`, structured `payload`
- `producer`, `producer_version`
- `source_reference`
- analysis configuration/result validity reference

Evidence type 후보:

- `USER_MEMO`, `TEMPORAL_REFERENCE`, `TRANSCRIPT`
- `AUDIO_REACTION`, `AUDIO_EVENT`
- `VISUAL_EVENT`, `SHOT_CHANGE`, `MOTION`
- `VLM_SELECTION`

Evidence는 서로 충돌할 수 있으며 충돌 자체도 정보로 보존한다. payload allowlist, 크기 제한, schema version과 민감정보 정책은 **구현 전 확정 필요**다.

### 8.4 QualityFlag

후보 예시는 `BLUR`, `SHAKE`, `DARK`, `OVEREXPOSED`, `LONG_SILENCE`, `DUPLICATE`, `ACCIDENTAL_RECORDING`, `LOW_AUDIO_QUALITY`다.

Quality는 semantic value와 분리한다. 품질 문제가 있다고 자동 삭제하지 않으며 Explicit Intent나 의미 가치가 있으면 Candidate로 유지할 수 있다. QualityFlag를 SceneEvidence subtype으로 둘지 별도 entity로 둘지는 **TBD**다.

### 8.5 SceneRelation

SceneRelation은 Candidate 간 의미 관계와 근거를 표현한다.

초기 후보:

- `SAME_EVENT`
- `CONTINUATION`
- `REACTION_TO`
- `DUPLICATE`

기존 Full Product/Data Flow 문서에는 `ALTERNATIVE`도 존재한다. `DUPLICATE`와 `ALTERNATIVE`의 의미가 겹치지 않도록 exact relation enum은 구현 전 설계·Evaluation으로 확정한다. `BEFORE`/`AFTER`처럼 timestamp로 계산 가능한 관계는 LLM 판단보다 deterministic derivation을 우선한다.

Relation에는 source/target Candidate, relation type, confidence, Evidence/producer/version과 방향성을 추적할 수 있어야 한다. exact schema는 **TBD**다.

### 8.6 EventGroup

EventGroup은 여러 SourceVideo의 관련 SceneCandidate를 같은 사건·경험 단위로 묶는다.

```text
우도 이동
├─ 선착장 설명
├─ 배 탑승
├─ 바다 B-roll
├─ 멀미 반응
└─ 우도 도착
```

파일 경계와 Event 경계는 같지 않다. v2는 우선 한 단계 EventGroup을 사용한다. Event/SubEvent 재귀 계층, immutable group versioning과 group label schema는 필요성이 확인되기 전 확정하지 않는다. label/summary는 grouping 이후 생성할 수 있지만 primary grouping criterion으로 사용하지 않는다.

## 9. Memo-guided Discovery

```text
EditMemo
→ Memo Intent
→ Temporal Search Region
→ Boundary Proposals
→ Semantic Selection
→ Deterministic Validation
→ SceneCandidate + SceneEvidence
```

### Memo Intent

MemoIntent는 `action`, `temporal_reference`, `semantic_reference`, `strength`를 구조화한다. action 후보는 `KEEP`, `REMOVE`, `SHORTEN`, `START_FROM`, `END_AT`이지만 exact enum과 parser 전략은 구현 전에 확정한다.

기존 EditMemo의 matched action/reference/trigger를 우선 입력으로 사용한다. LLM parser가 필요한 범위는 deterministic parser Baseline의 실패 분석 후 결정한다.

### Temporal Search Region

“방금”, “아까”, “여기부터” 같은 표현은 탐색 범위를 만든다. Memo timestamp를 곧바로 실제 장면 끝점으로 사용하지 않으며 Temporal Search Region도 최종 boundary가 아니다.

Search Region 정책과 최대 범위는 **Evaluation으로 결정**한다. Source duration 밖으로 나가지 않도록 Python validator가 제한한다.

### Boundary Proposals

Proposal source 후보:

- Transcript boundary
- Fixed Padding Baseline
- Shot Boundary
- Audio signal
- Visual signal
- surrounding Context

과거 audio/motion refinement 실패를 보존한다. audio activity는 semantic event boundary가 아니며 motion은 semantic relevance가 아니다. 두 signal은 truth가 아니라 proposal/evidence generator다.

### Semantic Selection and Validation

Semantic Selector에는 opaque proposal ID와 필요한 최소 context만 제공한다. LLM/VLM은 proposal ID를 선택하거나 abstain하며 자유 timestamp를 authoritative result로 반환하지 않는다. Python은 선택 ID가 manifest에 존재하는지 검증한 뒤 저장된 interval로 매핑한다.

Semantic 상태는 최소 `SELECTED`, `AMBIGUOUS`, `NO_MATCH`, `INSUFFICIENT_EVIDENCE`를 구분한다. `PROVIDER_FAILURE`, `PARSE_FAILURE`, `VALIDATION_FAILURE`는 semantic uncertainty와 분리한다.

Explicit User Intent는 Autonomous signal보다 우선한다. 단 Memo가 있다는 이유로 Autonomous Discovery를 비활성화하지 않는다.

## 10. Autonomous Discovery

```text
Memo-guided Discovery ─┐
                       ├→ Candidate Pool → Merge / Deduplication
Autonomous Discovery ──┘
```

Autonomous Discovery는 Memo가 없는 영상에서도 실행하며 Memo가 있는 영상에서도 독립적으로 수행한다. 목적은 최종 편집 여부 결정이 아니라 “검토할 가치가 있는 구간을 근거와 함께 발견”하는 것이다.

현재 deterministic promotion baseline에서 `REACTION_CUE_PLUS_AUDIO`는 시간상 겹치는 `AUDIO_ACTIVITY`만 반응 단서의 보강 근거로 사용한다. `SILENCE` Evidence는 분석 기록으로 유지하지만 이 조합의 보강 근거로 사용하지 않는다. 다른 허용 Evidence 조합과 STT 설정은 이 제한으로 변경되지 않는다.

MVP-05M에서는 `TRANSCRIPT_REACTION_CUE`의 시간 구간을 segment 전체가 아닌 확인된 단어 timestamp로 제한한다. 단어 시점이 없거나 유효하지 않으면 반응 Evidence를 임의로 만들지 않으며, `TRANSCRIPT_STRUCTURE`와 다른 modality 규칙은 유지한다. 이는 STT 오인식 자체를 해결하거나 VAD를 운영 활성화한 결과가 아니다.

### SceneRole Scope Amendment

G4 Architecture Review 결과 authoritative SceneRole assignment는 v2에서 v3 Edit Planner로 이동한다. 이는 누락 기능을 삭제하거나 SceneRole capability 자체를 제거한 것이 아니다. `HIGHLIGHT`, `ESTABLISHING`, `B_ROLL`, `TRANSITION`처럼 최종 사용 역할은 Project theme, target duration, surrounding scenes, Episode와 placement에 따라 같은 Candidate에도 달라질 수 있기 때문이다.

v2는 `REACTION` cue, dialogue, location view, action/event cue 같은 observed semantic fact와 Memo/preference match, technical quality를 분리된 Evidence로 제공한다. v3 Scene Agent는 필요할 때 evidence-backed, optional, potentially multi-label semantic/role hint를 제공할 수 있고, v3 Edit Planner가 전체 Project/EditPlan context에서 final editorial/narrative role을 결정한다. role enum, multi-label 정책과 Planner output contract는 v3 Detailed Plan에서 결정한다.

Evidence channel:

1. Transcript / Story
2. Audio
3. Visual
4. Shot Structure
5. User Preference interface

User Preference는 v2에서 input interface만 고려할 수 있다. persistent personalization 학습과 Style Memory는 v5 범위이며 v2에서 만들지 않는다.

겹치거나 유사한 Candidate를 merge/deduplicate하되 Evidence를 잃지 않는다. temporal overlap, semantic similarity와 duplicate 관계의 결합 방식은 Baseline 비교 후 결정한다.

## 11. Cheap → Expensive Analysis

```text
100+ SourceVideo
→ Cheap Deterministic Analysis
→ SceneUnit / Proposal
→ Cheap Evidence
→ Candidate Reduction / Priority
→ Selective Expensive Analysis
→ SceneCandidate
```

Cheap analysis 후보:

- Media Probe, STT, Memo Detection
- Shot Change, Audio Activity, Silence
- Basic Quality, Keyframe, Basic Visual Change

Candidate Reduction은 삭제가 아니라 expensive analysis 우선순위 결정이다. 개념적 priority는 `HIGH_PRIORITY`, `UNCERTAIN`, `LOW_PRIORITY`이나 exact enum은 구현 전에 확정한다.

Reduction threshold, 비율과 budget은 사전에 고정하지 않고 Baseline Evaluation으로 결정한다. `USER_MEMO`가 있는 영역은 cheap heuristic만으로 제거하지 않는다. 어떤 Candidate가 deep analysis를 받지 못했는지도 추적 가능해야 한다.

Cheap Analysis는 어디를 깊게 볼지 정하고, Expensive Analysis는 선택 구간의 의미를 분석한다. 100+ Source 전체를 동일하게 LLM/VLM에 보내지 않는다.

## 12. Evidence Model

### Transcript Evidence

언어 의미, 주제, 설명, 대화, temporal expression과 narrative cue를 다룬다. Transcript segment/word timestamp와 source lineage를 유지한다.

### Audio Evidence

웃음, 비명, 박수, silence, loudness change와 speech/non-speech 같은 음향 사건을 표현한다. Audio event는 important scene과 동의어가 아니다.

### Visual Evidence

- deterministic visual signal: motion, shot change, brightness change
- semantic visual evidence: 행동, 표정, 장소, 객체, 시각적 사건

motion은 semantic relevance와 동의어가 아니다. deterministic signal과 VLM semantic result의 producer/type을 구분한다.

### Quality Evidence

Technical quality는 semantic value와 분리한다. 낮은 품질은 경고·ranking input이 될 수 있지만 자동 삭제 결정은 아니다.

`BAD_TAKE`는 editorial role이 아니라 quality judgment 또는 exclusion/preservation reason에 가깝다. 이름만으로 자동 drop하지 않으며 Explicit User Intent가 technical issue보다 우선할 수 있다.

### Memo Evidence

Memo는 Explicit User Intent다. 일반 Evidence confidence와 단순 평균하지 않으며 source EditMemo와 lineage를 보존한다. 다른 Evidence가 충돌해도 Memo를 삭제하지 않고 conflict를 기록한다.

## 13. LLM / VLM Boundary

```text
Python: proposal ID + validated interval 생성
   ↓
LLM/VLM: proposal ID 선택 또는 abstain
   ↓
Python: schema / ID / ownership / range validation
   ↓
Python: stored timestamp mapping과 persistence
```

- Deterministic code: 측정, proposal 생성, resource/interval 검증, 실행
- LLM: 언어 의미, MemoIntent 또는 transcript semantic selection이 필요한 경우
- VLM: 축소된 구간의 시각 의미

Capability 후보:

- `MemoIntentParser`
- `TranscriptSemanticSelector`
- `VisualEventAnalyzer`
- `VisualProposalSelector`
- `EventSimilarityAnalyzer`

Provider는 Gemini, Ollama/Qwen 또는 future provider로 교체 가능해야 한다. v2에서 특정 Provider를 고정하지 않는다.

결과 상태는 semantic result와 infrastructure failure를 분리한다.

- semantic: `SELECTED`, `ABSTAIN`, `AMBIGUOUS`, `INSUFFICIENT_EVIDENCE`
- infrastructure/contract: `PROVIDER_FAILURE`, `PARSE_FAILURE`, `VALIDATION_FAILURE`

VLM은 Candidate Reduction 이후 선택적으로 사용한다. frame strategy는 3-frame, 5-frame, adaptive keyframe을 비교할 수 있으며 **Evaluation으로 결정**한다. Provider별 payload, timeout, model과 token/frame budget도 **TBD**다.

External Provider에는 전체 MOV/WAV를 기본 전송하지 않는다. transcript excerpt, selected low-resolution frame/contact sheet, structured context와 opaque resource/proposal ID만 최소 전송하며 provider/model/purpose를 추적한다.

## 14. Cross-video Event Grouping

```text
SceneCandidate[]
→ Cheap Relation Filter
→ Likely Related Pairs
→ Selective Semantic Analysis
→ SceneRelation
→ EventGroup
```

Grouping evidence 후보는 Temporal, Semantic, Location, People/Object, Visual, Audio와 Narrative다. 같은 장소라는 이유만으로 같은 Event로 확정하지 않는다.

모든 Candidate pair를 LLM/VLM으로 비교하면 비용이 제곱으로 증가하므로 cheap blocking/filtering으로 likely pair를 먼저 만든다. filter key, neighbor window와 embedding 사용 여부는 **Evaluation으로 결정**한다.

`DUPLICATE`는 삭제 명령이 아니라 관계 정보다. EventGroup 생성 후에도 원 Candidate와 Evidence lineage를 유지한다. Event Grouping은 현재 Project 내부 장면 관계 분석이며 외부 knowledge/reference retrieval인 RAG와 다르다.

## 15. Tool Layer

> Agent judges. Tool executes. Python function ≠ Tool.

모든 helper를 Tool로 노출하지 않고 독립 호출 가치가 있는 bounded capability만 제공한다. v1 service를 폐기하거나 같은 기능을 중복 구현하지 않는다.

### Domain 후보

- **Media Tools**: probe, extract audio, frame/keyframe extraction
- **Transcript Tools**: transcribe, detect memo, transcript window
- **Audio Analysis Tools**: activity, silence, audio event evidence
- **Visual Analysis Tools**: shot detection, basic quality, keyframes
- **Scene Tools**: temporal region, proposal generation, deterministic merge
- **Validation Tools**: interval, proposal, ownership, resource reference

`is_good_scene()`처럼 final scene value를 판단하는 Tool은 만들지 않는다.

### Tool contract

공통 ToolResult의 개념 후보:

- `success` 또는 status
- `tool_name`, `tool_version`
- structured `data`
- warnings
- safe error code/message와 retryability hint
- timing/execution metadata

exact schema와 version negotiation은 **구현 전 확정 필요**다. raw FFmpeg stderr, secret, absolute path, 전체 prompt와 media binary를 Agent/frontend에 노출하지 않는다.

Tool은 가능한 범위에서 deterministic/idempotent하게 설계하고 request/idempotency reference를 검토한다. Business retry 횟수와 backoff는 Orchestrator/application 정책이며 Tool 내부에 숨기지 않는다.

## 16. MCP Architecture

v2 초기 구조는 하나의 **Video Editing MCP Server**다. 구현 복잡도나 독립 배포 요구가 검증되기 전에 domain별 server로 나누지 않는다.

```text
Scene Intelligence
→ MCP Client
→ Video Editing MCP Server
→ Tool Layer
→ Existing / New Services
→ FFmpeg / STT / OpenCV / selective AI Provider
```

MCP Server는 Tool을 재구현하지 않고 Tool Layer capability를 표준 contract로 노출하는 adapter/interface다.

- FastAPI: Frontend/Client ↔ Cutory Product
- MCP: Cutory AI/Application ↔ Execution Capability
- LangGraph: v3 이후 workflow orchestration 후보

금지 capability:

- `run_shell(command)`
- `run_ffmpeg(command)`
- `read_any_file(path)`

선호 capability:

- `extract_keyframes(source_video_id, bounded_config)`
- `detect_shot_changes(source_video_id, bounded_config)`
- `generate_scene_proposals(source_video_id, search_region_id)`

Input은 absolute path 대신 resource ID와 bounded interval/config를 사용한다. ownership, project scope와 duration을 adapter 또는 validator에서 확인한다.

MCP Tools는 v2 핵심이다. MCP Resources와 MCP Prompts 사용 여부, transport, auth/deployment boundary, streaming/progress는 stable MCP SDK와 실제 요구를 구현 시 확인한 뒤 결정한다. 현재 문서에서는 특정 transport를 고정하지 않는다.

## 17. Persistence / Resume / Reprocess

v1의 상태·결과 유효성 철학을 Scene work item까지 확장한다.

필요한 개념:

- Source-level persistence와 Work-item-level persistence
- logical work item과 Attempt 분리
- result persistence/reference
- input fingerprint
- producer와 producer version
- analysis configuration
- dependency lineage
- stale recovery와 safe failure

SceneUnit, SceneCandidate, SceneEvidence, SceneRelation, EventGroup은 persistent data 후보다. exact table/schema와 어떤 중간 결과까지 영속화할지는 **구현 전 확정 필요**다.

WAV, extracted frame, contact sheet와 analysis temporary file은 재생성 가능한 temporary artifact다. Project/Source/Work-item ownership과 privacy/storage 정책에 따라 cleanup하며 original source를 삭제하지 않는다.

`COMPLETED`만으로 결과를 재사용하지 않는다.

```text
Reusable Result
= COMPLETED
+ matching input fingerprint
+ compatible producer / producer version
+ compatible analysis configuration
+ required result and dependency lineage 존재
```

Invalidation 예:

- STT 변경 → 영향받는 Transcript/Memo/Transcript Evidence/Scene downstream 재계산
- Visual Analyzer 변경 → Visual Evidence와 의존 downstream만 재계산
- grouping config 변경 → Source-level Candidate를 유지하고 Relation/EventGroup부터 재계산 가능

전체 Project를 무조건 처음부터 실행하지 않는다. 외부 AI 호출 성공 직후 DB 저장 전에 process가 종료되는 경우를 고려해 idempotency reference, reconciliation 또는 safe re-execution 전략을 구현 단계에서 결정한다.

Retry 횟수, stale timeout과 자동 recovery 정책은 **TBD**이며 Evaluation과 운영 요구로 결정한다.

## 18. Evaluation Strategy

v2 평가는 discovery 단계, failure 단계와 비용을 분리해 기록한다. Ground Truth/Oracle은 product execution flow에 넣지 않는다.

### Memo-guided Discovery

- Temporal IoU, GT Coverage
- Start/End Boundary Error
- Proposal Recall
- Semantic Selection Accuracy

Proposal Generation 실패와 Semantic Selection 실패를 분리한다.

### Autonomous Discovery

- Candidate Recall, Candidate Precision
- Candidate Count, Candidate Duration

중요 장면을 놓치지 않는 Recall을 중시하되 전체 영상을 Candidate로 만드는 방식은 Precision/Count/Duration으로 드러낸다.

### Candidate Reduction

- Reduction Rate
- GT Recall After Reduction

목표 threshold는 Baseline 결과 후 결정한다.

### LLM / VLM

- Correct Selection, Wrong Selection
- Abstain, Ambiguous, Insufficient Evidence
- Provider Failure, Parse Failure, Validation Failure

Provider 장애와 semantic 판단 실패를 합치지 않는다.

### Efficiency

- LLM/VLM calls, frames sent, input tokens
- execution time, provider failures
- 측정 가능한 경우 cost

### Frame Strategy

필요성이 확인되면 3-frame, 5-frame, adaptive keyframe을 동일한 사전 기준으로 비교한다.

### Event Grouping

- Pairwise Relation Precision / Recall / F1
- Event Group Purity
- `OVER_MERGE`, `OVER_SPLIT`, `MISASSIGNMENT`

### Reliability

- Resume, Retry, Reprocess, stale recovery
- dependency invalidation, Partial Failure, duplicate processing
- temporary cleanup, MCP error propagation, provider failure isolation

정확한 목표 수치와 acceptance threshold는 각 evaluation 시작 전에 별도 설계로 고정하며 현재는 **TBD**다.

## 19. Dataset Strategy

기존 eval_01~05, fixed-window, transcript block, semantic block, audio boundary, visual motion, Gemini/Ollama VLM과 contact sheet 실험은 historical baseline/evidence로 보존한다. 다섯 sample만으로 일반화 성능을 주장하지 않는다.

### Focused Evaluation Set

- 짧고 통제된 영상
- Memo, boundary, proposal
- LLM/VLM과 frame strategy
- failure 원인을 사람이 확인 가능한 규모

### Project Evaluation Set

- 여러 SourceVideo
- Autonomous Discovery, Candidate Reduction
- Cross-video Event Grouping
- Resume와 Scale

### 규모별 목적

- Small, 10~20 Source: semantic accuracy와 failure analysis
- Medium, 30~50 Source: relation/event/reduction
- Scale, 100+ Source: state scale, resume, reliability와 비용 구조

100+ 실제 영상 전체에 초 단위 Ground Truth annotation을 요구하지 않는다. Semantic Accuracy Evaluation과 Scale/Reliability Evaluation을 분리한다. 개인정보, 촬영 동의, 외부 Provider 전송 범위와 Git 제외 정책을 dataset별로 기록한다.

## 20. Implementation Steps

각 Step은 `Design confirmation → Implementation → Test → Integration → Evaluation where applicable → Documentation → Commit` 순서를 따른다. 한 번에 v2 전체를 구현하지 않는다.

### Step 1 — Scene Intelligence Data Foundation

- conceptual model을 실제 v2 최소 schema로 확정
- SceneCandidate/Evidence/Relation/EventGroup persistence
- enum, constraint, index, lineage와 migration 설계
- model/unit/PostgreSQL migration test
- SceneUnit/QualityFlag/final Scene entity의 저장 경계 결정

### Step 2 — Tool Layer Foundation

- 기존 v1 service를 capability 기준으로 매핑
- 공통 Tool input/result/error/version contract
- resource ID validation, ownership, bounded interval
- deterministic/idempotent behavior와 execution metadata
- arbitrary shell/path capability 부재 검증

### Step 3 — Video Editing MCP Server

- 단일 MCP Server와 Tool adapter
- stable SDK/transport를 구현 시점에 검증해 선택
- capability discovery/call, schema validation, safe error propagation
- FastAPI/MCP 책임 분리와 resource scope test
- Resources/Prompts는 필요성 평가 후 포함 여부 결정

### Step 4 — Memo-guided Scene Discovery

- MemoIntent와 Temporal Search Region Baseline
- 여러 source의 boundary proposal 생성
- proposal ID semantic selector와 deterministic validator
- SceneCandidate/Evidence persistence
- proposal failure와 selection failure 분리 평가

### Step 5 — Autonomous Scene Discovery

- Transcript/Audio/Visual/Shot/Quality cheap Evidence
- Memo와 독립적인 Candidate 생성
- candidate merge/deduplication과 conflict 보존
- observed semantic fact, technical quality, candidate utility Evidence의 분리 평가
- final SceneRole assignment는 수행하지 않고 v3 Planner responsibility로 handoff

### Step 6 — Selective LLM / VLM Analysis

- Candidate Reduction과 priority
- provider-independent semantic capability
- 선택 구간의 최소 context 전송
- abstain/failure/parse/validation 상태 분리
- frame strategy와 비용/성능 비교

### Step 7 — Cross-video Event Grouping

- cheap relation filter와 likely pair generation
- selective semantic relation analysis
- SceneRelation과 한 단계 EventGroup persistence
- pairwise/group failure taxonomy와 평가

### Step 8 — Persistence / Resume Integration

- Scene work item/attempt 상태
- validity/reuse, Retry/Reprocess, stale recovery
- dependency-based targeted invalidation
- external side-effect 후 durable write 실패 대응
- 100+ synthetic/state scale와 Partial Failure 검증

### Step 9 — v2 Evaluation / Failure Analysis / Completion

- Focused/Project/Scale 평가 실행
- Memo/Autonomous/Reduction/AI/Event/Reliability 결과 분리
- regression, privacy, cost와 operational limitation 기록
- Completion Gate 판정과 v3 handoff 문서화

Step별 정확한 commit 수와 파일 배치는 해당 Step 시작 시 현재 repository 상태를 다시 확인해 결정한다.

## 21. Completion Gate

v2 완료 선언 전 최소 다음을 실제로 검증하고 근거를 남긴다.

### Data

- [ ] SceneCandidate / Evidence / Relation / EventGroup 영속화 가능
- [ ] Candidate, Evidence, Quality와 Decision 의미가 혼합되지 않음
- [ ] Observed Evidence와 Project-context editorial role이 혼합되지 않음
- [ ] source/result/producer/config lineage가 추적 가능

### Tool

- [ ] Scene Intelligence 핵심 capability가 Tool Layer로 분리됨
- [ ] 기존 v1 service를 중복 구현하지 않음
- [ ] structured ToolResult와 safe failure가 검증됨

### MCP

- [ ] Video Editing MCP Server를 통해 핵심 Tool 호출 가능
- [ ] FastAPI와 MCP 책임이 분리됨
- [ ] arbitrary shell/path 접근이 없음

### Discovery

- [ ] EditMemo에서 관련 SceneCandidate 생성 가능
- [ ] Memo 없이도 SceneCandidate 발견 가능
- [ ] Memo가 있는 Source에서도 Autonomous Discovery가 독립 실행됨
- [ ] Candidate merge/deduplication이 Evidence를 보존함

### Multimodal / AI

- [ ] Transcript / Audio / Visual Evidence가 분리되어 보존됨
- [ ] Shot Structure Evidence가 Visual Activity와 구분되어 생성·재사용됨
- [ ] Quality와 semantic value가 분리됨
- [ ] LLM/VLM이 Candidate Reduction 이후 selective하게 사용됨
- [ ] capability와 provider가 분리됨
- [ ] AI free timestamp를 authoritative interval로 사용하지 않음
- [ ] semantic/provider/parse/validation failure가 구분됨

### Scale / Event

- [ ] 100+ Source 구조에서 모든 영상을 동일하게 full VLM 분석하지 않음
- [ ] Candidate Reduction Rate와 GT Recall을 함께 평가함
- [ ] 여러 Source의 관련 Candidate를 EventGroup으로 묶을 수 있음
- [ ] pairwise relation과 grouping failure를 평가함

### Reliability

- [ ] 중단 후 valid result를 재사용하고 이어서 처리 가능
- [ ] dependency 기반 targeted invalidation 가능
- [ ] Partial Failure와 provider failure가 격리됨
- [ ] duplicate processing과 temporary cleanup이 검증됨
- [ ] v1 동작에 의도하지 않은 regression이 없음

### Evaluation / Analysis

- [ ] Memo / Autonomous / Reduction / LLM-VLM / Event 평가 결과 존재
- [ ] efficiency와 external transmission 범위가 기록됨
- [ ] 주요 failure case와 후속 개선 근거가 문서화됨
- [ ] v3 handoff contract와 남은 위험이 기록됨

“AI가 100% 정확하다”는 Completion Gate가 아니다. Scene Intelligence 구조가 실제 동작하고, 객관적으로 평가 가능하며, 실패 원인을 분리하고, 다음 Version에서 개선 가능한 상태인지가 기준이다.

## 22. Risks / Open Decisions

| 항목 | 현재 상태 | 결정 시점/근거 |
|---|---|---|
| exact DB schema/index/migration 단위 | TBD | Step 1 설계 및 query pattern |
| exact enum 전체 | TBD | Step 1 + Evaluation |
| SceneUnit 영속 범위 | TBD | 재생성 비용/lineage 검토 |
| QualityFlag 별도 entity 여부 | TBD | Step 1 |
| final Scene entity 도입 | TBD | v2 validation 결과 |
| authoritative SceneRole | v3 Edit Planner로 이동 | Project/EditPlan context-dependent editorial decision |
| optional semantic/role hint | v3 Scene Agent에서 설계 | evidence-backed, non-authoritative Planner input |
| `DUPLICATE`와 기존 `ALTERNATIVE` relation | 구현 전 확정 필요 | relation semantics/Evaluation |
| Candidate Reduction threshold/비율 | Evaluation으로 결정 | Step 6 Baseline |
| target accuracy 숫자 | TBD | evaluation protocol 사전 등록 |
| VLM frame strategy | Evaluation으로 결정 | 3/5/adaptive 비교 |
| AI Provider/model | TBD | privacy, quality, cost, latency |
| embedding/cheap relation filter 사용 | TBD | Event pair scale Evaluation |
| MCP transport/SDK version | 구현 전 확정 필요 | 당시 stable SDK/운영 요구 |
| MCP Resources 사용 | TBD | 실제 resource discovery 필요성 |
| MCP Prompts 사용 | TBD | 실제 반복 prompt contract 필요성 |
| retry 횟수/backoff | Evaluation으로 결정 | failure/reliability 결과 |
| stale timeout | Evaluation으로 결정 | workload timing |
| Event/SubEvent hierarchy | v2에서 미도입 | 한 단계 EventGroup 결과 |
| ToolResult exact fields/versioning | 구현 전 확정 필요 | Step 2 contract |
| queue/worker 도입 | TBD, v2 자동 범위 아님 | real workload/operational evidence |

주요 위험:

- Candidate Reduction이 중요한 Scene을 제거할 위험
- Explicit Intent가 generic score aggregation에 묻힐 위험
- AI selection의 provider/parse 실패를 semantic failure로 잘못 집계할 위험
- Candidate pair 증가로 Event Grouping 비용이 제곱 증가할 위험
- stale/invalid result가 downstream에서 재사용될 위험
- frame/transcript 외부 전송으로 privacy 범위가 커질 위험
- 실제 faster-whisper/VLM 병렬 workload가 v1 기본 동시성 가정과 충돌할 위험

각 위험은 숨겨진 fallback이 아니라 metric, status, warning과 Failure Analysis로 드러나야 한다.

## 23. v3 Handoff

v2는 v3에 다음 결과를 넘긴다.

- validated SceneCandidate와 modality별 SceneEvidence/QualityFlags
- SceneRelation과 EventGroup
- discovery method, confidence, conflict와 abstain/failure metadata
- Tool Layer와 Video Editing MCP capability contract
- resource ID, execution reference와 producer/version lineage
- Scene work-item Resume/Retry/Reprocess 기반
- Memo/Autonomous/Reduction/LLM-VLM/Event Evaluation 결과
- 비용·privacy·provider·scale Failure Analysis
- authoritative role로 고정되지 않은 observed semantic/technical Evidence

v3는 이 기반 위에서 Scene Agent, Style Agent, Edit Planner와 필요한 Orchestrator를 설계한다. Scene Agent는 필요하면 Evidence 기반 semantic/usage/role hint를 제공하지만 final authority를 갖지 않는다. Edit Planner는 Project instruction, Candidate/EventGroup, target duration, ResolvedStyle, surrounding scenes와 Episode placement를 반영해 SceneEditPlan의 authoritative editorial/narrative role을 결정한다. v2 문서에서 exact role enum, v3 Agent prompt, LangGraph state graph, planning schema와 Multi-Agent interaction을 미리 확정하지 않는다.

## References

- [Cutory Full Product Development Plan](../product/full-development-plan.md)
- [Cutory Version Roadmap](version-roadmap.md)
- [v1 Detailed Plan](v1-plan.md)
- [v1 Completion](v1-completion.md)
- [Full Product Architecture](../architecture/full-architecture.md)
- [Large Video Processing Architecture](../architecture/large-video-processing.md)
- [Data Flow and Lineage](../architecture/data-flow.md)
- [Tool Layer](../tools/tool-layer.md)
- [MCP Architecture](../mcp/mcp-architecture.md)
- [Privacy and License Design](../privacy/privacy-license.md)
- [Historical MVP v1 Specification](../mvp-v1-spec.md)
- [Historical Real-media Integration](../integration-eval01-v0.1.md)
- [Historical Browser E2E](../browser-e2e-v0.1.md)
- [v1 Foundation Evaluation](../../evaluation/results/cutory-v1-foundation-eval-v0.1.md)
