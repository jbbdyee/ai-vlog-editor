# QA-05 — QA-03 적용 전 호환성 정리 (Streamlit 무결성 안내 · 기존 백엔드 실패 3건)

- 일자: 2026-11-03
- 범위: QA-04(CONDITIONAL PASS)가 남긴 호환성 항목 2개. 실제 개발 DB 적용은 **미승인·미실행**.
- 상태 구분: 구현 완료 + 합성/격리 테스트 통과. 실제 개발 DB·실제 Streamlit 클릭은 미검증.

## 보호 조건 준수

| 조건 | 결과 |
| --- | --- |
| 개발 DB migration 금지 | 개발 DB revision `b8c01e2a4f60` 유지, `project_render_runs` 0행, `projects` 13행(작업 전후 동일) |
| 원본·렌더 파일 변경 금지 | 원본·렌더 경로를 읽거나 쓰는 작업 없음. 테스트는 `TemporaryDirectory`·격리 DB만 사용 |
| FastAPI·Vite·Tailscale 재시작 금지 | 재시작 없음. 8000·5173 응답 200 유지. Streamlit은 원래 실행 중이 아니었음 |
| 보호 대상 테스트 3개 | `test_clip_download_api.py`(6/1), `test_project_render_api.py`(6/1), `test_project_rendering.py`(1/1) SHA-256·numstat 작업 전후 동일 |
| 기존 미커밋 변경 보존 | `git status` 차이는 이번 작업 파일 6개뿐(아래 변경 목록) |
| 커밋·Push 금지 | HEAD `1a2d7d7` 유지 |

격리 PostgreSQL(55432)에는 일회용 `cutory_qa01_qa05_*`, `cutory_qa03_qa05_*` DB만 만들고 테스트 후 삭제했다(남은 `cutory_qa%` DB 0개).

## 작업 1. Streamlit 무결성 안내

### 문제 (QA-04 판단 정정)

QA-04는 Streamlit을 "안전하지만 안내 문구만 누락"으로 기록했다. 이번에 실제 FastAPI 응답을 Streamlit 클라이언트에 넣어 확인해 보니 실제로는 더 나빴다.

- `frontend/api_client.py`의 `_safe_render_status_payload`는 `hard_subtitle_status` 허용 목록이 QA-03 이전 값 7개뿐이었다.
- 기본 MP4가 `CORRUPT`/`UNVERIFIED`/`MISSING`이면 서버는 `hard_subtitle_status=BASE_UNAVAILABLE`을 보낸다. 하드 자막만 문제면 `CORRUPT`/`UNVERIFIED`를 보낸다.
- 이 세 값 모두 허용 목록 밖이라 **상태 조회 전체가 "렌더링 상태 응답 형식이 올바르지 않습니다." 오류로 거부**됐다. 사용자는 무엇이 문제인지 볼 수 없었다.
- 하드 자막만 손상된 경우에도 정상인 기본 MP4 다운로드 버튼까지 사라졌다.
- 다운로드 409는 오류 코드와 무관하게 "아직 다운로드 가능한 렌더링 결과가 아닙니다."로 안내돼, 렌더 미완료와 무결성 차단을 구분하지 못했다.

안전성(검증 안 된 바이트를 주지 않음)은 그대로 지켜졌다. 문제는 상태 표시와 정상 파일 접근이었다.

재현 근거: 이번에 추가한 테스트를 HEAD의 `frontend/`(수정 전)에 대고 실행하면 8건 중 7건 ERROR, 2건 FAIL이었다(하위 테스트 포함). 계약 테스트 5건이 모두 위 형식 오류로 실패했다.

### 변경 (기존 UI 제거 없음)

`frontend/api_client.py`

- `HARD_SUBTITLE_STATUSES`에 `CORRUPT`, `UNVERIFIED`, `BASE_UNAVAILABLE`을 추가했다.
  - `BASE_UNAVAILABLE`은 `COMPLETED`이면서 `download_available=false`일 때만 허용한다(모순 응답은 계속 거부).
- 서버가 보내는 `integrity_status`, `subtitle_integrity_status`, `hard_subtitle_integrity_status`를 검증해서 전달한다.
  - 값은 `VERIFIED`/`MISSING`/`CORRUPT`/`UNVERIFIED`만 허용한다.
  - 기본 파일은 `VERIFIED` ⇔ `download_available`, 하드 자막은 `VERIFIED` ⇔ `hard_subtitle_download_available`이어야 한다. 어긋나면 거부한다.
  - 필드가 없는 이전 서버 응답은 그대로 받는다(현재 8000의 QA-03 이전 코드와 호환).
- 다운로드 409는 `detail.code`로 문구를 나눈다. 모르는 코드는 기존 문구를 유지한다. `BackendApiError.code`에 안전한 코드를 담는다.
  - `RENDER_FILE_CORRUPT`: 결과 영상 파일이 렌더링 완료 당시 기록과 일치하지 않아(손상 또는 변경 의심) 제공하지 않습니다. 다시 렌더링해 주세요.
  - `RENDER_FILE_UNVERIFIED`: 무결성 기록이 없는 과거 렌더링 결과라 제공하지 않습니다. 다시 렌더링해 주세요.
  - `SUBTITLED_RENDER_CORRUPT`, `SUBTITLED_RENDER_UNVERIFIED`: 위와 같은 의미의 자막 적용 영상 문구.
  - 404는 기존 문구를 유지하고 코드만 함께 담는다.

`frontend/app.py`

- `_render_project_render_status`: 기존 문장 "렌더링은 완료됐지만 결과 파일을 다운로드할 수 없습니다." 뒤에 `safe_error_code`별 사유를 덧붙인다.
  - `RENDER_FILE_MISSING`: 파일 없음.
  - `RENDER_FILE_CORRUPT`: 기록 불일치.
  - `RENDER_FILE_UNVERIFIED`: 무결성 기록 없음.
- `_render_hard_subtitle_status`: 세 상태에 문구를 추가했다.
  - `CORRUPT`: 기록 불일치. 자막 없는 영상은 따로 받을 수 있다고 안내.
  - `UNVERIFIED`: 무결성 기록 없음.
  - `BASE_UNAVAILABLE`: 기본 영상을 제공할 수 없어 자막 적용 영상도 제공하지 않는다고 안내.

다운로드 정책은 바꾸지 않았다. 버튼 표시·활성 조건은 여전히 서버의 `download_available`/`hard_subtitle_download_available`만 따른다. 다운로드 직전 상태 재조회도 기존 그대로다.

### 신규 테스트 `tests/test_frontend_qa05_render_integrity.py` (8건)

**계약 테스트 5건.** 실제 FastAPI 앱을 쓰고, 격리 SQLite와 임시 출력 폴더는 QA-03 fixture를 조합으로 재사용했다. 실제 서버 응답을 Streamlit 클라이언트에 그대로 전달한다.

1. 정상 렌더: 세 파일 `VERIFIED`, 두 MP4 다운로드 바이트가 일치한다.
2. 기본 MP4를 같은 크기로 변조: 상태 조회가 성공한다. `CORRUPT`, `RENDER_FILE_CORRUPT`, `BASE_UNAVAILABLE`이 오고 다운로드 URL은 없다. 다운로드는 409와 해당 코드·문구로 막히고, 화면 문구 2개가 나온다.
3. 해시 없는 과거 기록: `UNVERIFIED`와 409 `RENDER_FILE_UNVERIFIED`. 문구가 "아직 다운로드 가능한"이 아님을 확인한다.
4. 하드 자막만 `CORRUPT` 또는 `UNVERIFIED`: 기본 MP4는 계속 받을 수 있다. 자막 적용 영상은 409와 해당 코드로 막히고, 문구가 나온다.
5. 기본 MP4 삭제: `MISSING`와 404 `RENDER_NOT_FOUND`. 기존 계약을 유지한다.

**검증·화면 테스트 3건.**

1. 모순 응답 4종을 거부한다: VERIFIED인데 다운로드 불가, 알 수 없는 상태, 하드 자막 무결성 불일치, 기본 파일이 가용한데 `BASE_UNAVAILABLE`.
2. 무결성 필드가 없는 이전 서버 응답을 그대로 받는다.
3. 차단 상태에서는 기존에 받아 둔 바이트가 세션에 있어도 다운로드 준비·다운로드 버튼을 만들지 않는다. 하드 자막만 차단이면 해당 버튼만 비활성화한다.

## 작업 2. 기존 백엔드 실패 3건

### 보호 대상과의 중복 확인

실패 3건은 다음 세 테스트다.

- `backend/tests/test_alembic_foundation.py::test_alembic_configuration_loads_without_stored_database_url`
- `backend/tests/test_database.py::test_foundation_metadata_contains_current_product_tables`
- `backend/tests/test_product_models.py::test_metadata_contains_all_current_product_tables`

보호 대상 3개(`test_clip_download_api.py`, `test_project_render_api.py`, `test_project_rendering.py`)와 **겹치지 않는다**. 세 파일은 작업 전 미커밋 변경이 없는 커밋 상태였다(마지막 변경 `c59dd2e`).

### 원인과 검증

- 세 테스트는 `Base.metadata.tables`가 15개 테이블 집합과 **정확히 같은지** 검사한다.
- 실패 메시지는 셋 다 `Items in the first set but not the second: 'project_render_runs'` 하나였다.
- 원인 확정 방법은 다음과 같다.
  - 미커밋 WEB-08B 변경인 `backend/app/models/__init__.py`가 `from backend.app.models.render import ProjectRenderRun`을 추가해 테이블을 메타데이터에 등록한다(`git diff`로 확인).
  - `git archive HEAD`로 추출한 커밋 트리에서 같은 세 테스트 모듈을 실행하면 18건이 모두 통과했다. 즉 이 실패는 WEB-08B 변경에서만 생긴다.
  - QA-03은 테이블을 만들지 않고 컬럼 3개와 CHECK만 추가했다(`op.add_column`). 실패 메시지도 테이블 이름 하나뿐이라 QA-03과 무관하다.

### 최소 수정 (완화 없음)

- 세 기대 집합에 `"project_render_runs"`를 1줄씩 추가했다. 정확한 집합 일치 검사는 그대로다.
- `test_product_models.py`는 기대 기본키 표에 `"project_render_runs": ["render_id"]`를 추가했다. 그래서 새 테이블도 기본키 검사를 받는다(기본값 `["id"]`였다면 실패). 검사가 오히려 하나 늘었다.
- 변경량: 각각 +1, +1, +2줄이다. CRLF 줄바꿈을 유지했다.

수정 뒤 세 모듈은 18/18 통과한다.

## 작업 3. 회귀 검증 (QA-04 대비)

| 항목 | QA-04 | QA-05 |
| --- | --- | --- |
| 백엔드 전체 (`unittest discover -s backend/tests`) | 593건: 554 통과, 36 건너뜀, **3 실패** | 593건: **557 통과**, 36 건너뜀, 0 실패 |
| QA-03 무결성 테스트 | 23 통과 | 23 통과 |
| 격리 PostgreSQL (QA-01 3건, QA-03 migration 1건) | 4 통과 | 4 통과 (일회용 DB 생성 후 삭제) |
| Streamlit (`unittest discover -s tests`) | 64 통과 | **72 통과** (신규 8건 포함) |
| React Vitest | 52 통과 | 52 통과 |
| 타입 검사 (`tsc -b`) | 통과 | 통과 |
| Mock Chrome (Playwright `e2e/`) | 32 통과 | 32 통과 |

- 건너뛴 36건은 통과로 세지 않았다. 대부분 격리 PostgreSQL 등 환경 조건부 테스트다.
- QA-04의 실제 FFmpeg 렌더와 실제 Chrome 검증은 백엔드 코드 변경이 없어 다시 하지 않았다. 이번 변경은 Streamlit 클라이언트·화면과 테스트 기대값뿐이다.

## 변경 파일

- 수정:
  - `frontend/api_client.py`
  - `frontend/app.py`
  - `backend/tests/test_alembic_foundation.py`
  - `backend/tests/test_database.py`
  - `backend/tests/test_product_models.py`
- 추가:
  - `tests/test_frontend_qa05_render_integrity.py`
  - 이 문서
- 동기화: `README.md`, `TODO.md`, `docs/roadmap/v2-plan.md`

## 판정: CONDITIONAL PASS (QA-04 조건 5 해소)

- QA-04 조건 5(Streamlit 안내 누락, 기존 실패 3건)는 해소됐다. 백엔드 실패는 0건이다.
- Streamlit은 QA-03 서버의 모든 무결성 상태를 받아들이고 구분해서 안내한다.
- 적용 후 Streamlit을 띄우면 새 코드가 그대로 쓰인다. 현재 Streamlit은 실행 중이 아니라 별도 재시작이 필요 없다.

다음 조건은 그대로 남아 PASS로 올리지 않았다.

1. QA-04 적용 계획의 순서와 중단 조건을 지킨다. migration 다음에 FastAPI를 재시작하고, 그 사이에는 렌더하지 않는다.
2. 운영 정책 승인이 필요하다.
   - 해시 없는 과거 기록을 기본 차단한다.
   - 기본 MP4에 문제가 있으면 하드 자막도 차단한다.
   - 409 코드와 문구(이번 Streamlit 문구 포함)를 확정한다.
   - 요청마다 파일 전체를 해시하는 비용을 감수한다.
3. Windows 단일 호스트 배포를 전제한다. POSIX·다중 호스트는 추가 설계가 필요하다.
4. 긴 결과 영상이 생기면 Range 지연을 다시 측정한다.

## 남은 위험

- Streamlit 실제 브라우저 클릭은 검증하지 않았다(`st` 함수 patch 단위 테스트와 실제 FastAPI 응답 계약 테스트만 했다).
- Streamlit은 SRT 무결성(`subtitle_integrity_status`)을 표시하지 않는다. 원래 SRT를 따로 제공하지 않는 화면이라 범위 밖으로 두었다.
- 하드 자막 다운로드 직전 재조회에서 상태가 바뀌면 기존 문구 "자막 적용 영상 상태가 변경되었습니다"가 나간다. 구체적인 사유는 다음 화면 갱신 때 상태 문구로 보인다.
- 실제 개발 DB 적용, 운영 FastAPI 재시작, 실제 사용자 영상 렌더는 실행하지 않았다.
