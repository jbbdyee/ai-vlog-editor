# QA-04 — QA-03 렌더 무결성의 실제 개발 DB 적용 전 최종 검증

상태: **격리 환경 실제 FFmpeg 렌더·재시작·변조·실제 Chrome 검증 완료. 판정 CONDITIONAL PASS. 실제 개발 DB 적용·운영 FastAPI 재시작은 미실행(승인 대기).** 새 기능은 추가하지 않았다. 시작·종료 Git `main`, HEAD `1a2d7d7`. 기존 미커밋 변경과 보호 대상 백엔드 테스트 3개(6/1, 6/1, 1/1, 파일 SHA-256 동일)를 보존했다. 커밋·Push 없음. 기준: [QA-01](qa-01-render-recovery.md), [QA-02](qa-02-render-integrity-design.md), [QA-03](qa-03-render-integrity-implementation.md).

## 1. 현재 상태(읽기 전용)

| 항목 | 확인 |
| --- | --- |
| 개발 DB | `127.0.0.1:5432`, revision `b8c01e2a4f60`, 렌더 기록 0건, 프로젝트 13건, 다른 활성 쿼리 0. `READ ONLY` 트랜잭션으로만 조회 |
| 서비스 | FastAPI `127.0.0.1:8000`(영속 렌더 모드·번들 FFmpeg `PATH`, `--reload` 없음, **QA-03 이전 코드 실행 중**) 200, Vite 5173 200(HMR로 QA-03 React 반영 중), PostgreSQL localhost 게시 유지 |
| QA-03 산출물 | 미커밋 신규 `render_integrity.py`, `verified_file_response.py`, revision `e3a1c9d27b45`, 테스트 2개; 수정 `projects.py`, `persistent_render_execution.py`, `project_render_execution.py`, `project_rendering.py`, `models/render.py`, `main.py`, React 3파일 |
| 사용자 파일 | WEB-08C 인벤토리의 원본 9개·렌더 17개 26개 파일 크기·SHA-256 전부 일치. 원본 10번째 MOV(2026-11-03 12:28)는 이번 세션 전 [새 MOV 처리 작업](scene-preview-recovery-2026-11-03.md)에서 생긴 파일이며 이번 작업은 `storage/`·`outputs/`에 쓰지 않았다 |

## 2. 실제 렌더 검증(격리)

**격리 구성:** 일회용 DB `cutory_qa04_20261103171135`(격리 컨테이너 55432, Alembic `head`=`e3a1c9d27b45`까지 실제 upgrade), 데이터 루트 `temporary/qa04-20261103171135/`(Git 제외; sources·outputs·work). 테스트 전용 서버 `backend/tests/qa04_isolated_server.py`는 루트가 `temporary/` 밖이거나 DB가 55432·`cutory_qa04_` 접두사가 아니면 시작을 거부하고 원본·출력·임시 경로를 모두 격리 루트로 바꾼다(STT 모델 미로딩). 원본은 FFmpeg `testsrc2`+440Hz 톤 12초 **합성 영상**이며 사용자 영상은 읽지 않았다. 한국어 전사 2개, 후보 2개(0.5–3.5초, 6.0–9.0초), 편집 계획 2장면. 하드 자막은 기존 검증된 글꼴(SHA-256 `6bcb2a07…e992a`)과 기존 Docker 이미지 `lscr.io/linuxserver/ffmpeg@sha256:1f9755c9…`로 생성했다. 격리 API는 127.0.0.1:8002(및 다중 프로세스 시험용 8003), 격리 Vite는 5175(`CUTORY_API_PROXY_TARGET=8002`).

| 단계 | 결과 |
| --- | --- |
| 실제 렌더 | POST 202 → 4.1초 후 COMPLETED. `final.mp4` 2,292,105B(h264/aac, 6.0초), `final.srt` 140B(한국어 2개 큐, 0.5–2.5초·3.5–5.5초로 정상 매핑), `final-subtitled.mp4` 2,209,523B(h264/aac, 6.0초). 프레임 캡처에서 “두 번째 합성 자막입니다” 하드 자막 확인 |
| 해시 저장 | DB `base/srt/hard_sha256`가 파일 실측 SHA-256과 모두 일치(`0c86a105…`, `c7aabdc7…`, `fef20815…`). 상태 API `VERIFIED`×3 |
| 다운로드·Range | 두 MP4 전체 200·본문 SHA-256=DB 값·`ETag "sha256-…"`; 앞 1KiB·중간 4KiB·끝 512B Range 206 바이트 정확, 파일 끝 이후 416. **18/18 통과** |
| 재시작 준하는 재초기화 | 8002 프로세스(QA-04 서버만 식별해 종료) → 새 프로세스(PID 변경) 기동, 영속 모드 시작 가드 통과 → 같은 최신 렌더·기록 VERIFIED·위 검증 반복 **18/18 통과** |
| 실제 Chrome 미리보기·다운로드 | 격리 Vite 5175에서 두 버전 `<video>` 재생·3.6초 seek·프레임 디코딩, 두 다운로드 버튼 파일 SHA-256=서버 ETag. **통과** (`web/e2e-real/qa04.spec.ts`, clean) |
| 변조 차단 | 기본 MP4 동일 크기 1바이트 변경: 상태 CORRUPT·COMPLETED 유지·하드 자막 `BASE_UNAVAILABLE`, 전체·Range·하드 자막 409 `RENDER_FILE_CORRUPT`, 오류 본문 JSON(512B 미만), DB 해시 불변 → 짧아진 파일 409 → 삭제 404 `RENDER_NOT_FOUND`/`MISSING` → 복원 200. 하드 자막만 변조: 기본 206 유지, 하드 409 `SUBTITLED_RENDER_CORRUPT`. SRT만 변조: 진단 CORRUPT, 두 MP4 유지. DB 해시 NULL: `UNVERIFIED` 409·backfill 없음. 모든 파일 원래 해시로 복원. **21/21 통과** |
| 실제 Chrome 차단 화면 | 기본 MP4 동일 크기 변조 상태에서 “기록한 SHA-256과 다릅니다”·“기본 파일 변형 감지” 표시, 미리보기 없음, 다운로드 비활성, 직접 Range 409. 이후 원본 복원·VERIFIED 복귀 확인 |
| 정리 | 격리 프로세스 8002/8003/5175만 종료(명령줄 확인 후), 일회용 DB 삭제, 격리 루트 8.9MB 삭제, 자격 정보 임시 파일 삭제. 기존 격리 DB 3개 유지 |

## 3. 파일 제공 안전성

| 환경 | 보장 수준 | 근거 |
| --- | --- | --- |
| Windows(현재 호스트) | 검증 핸들이 열려 있는 동안 다른 프로세스의 쓰기·교체·삭제 **거부**. 응답 바이트는 검증된 내용 | 실제 8002 서버가 하드 자막 MP4를 전체/Range로 스트리밍하는 도중 `open r+b` 쓰기, `os.replace`(winerror 5), `unlink`(winerror 32) 모두 PermissionError. 전체 응답 SHA-256=기록 값. 스트림 종료 후 쓰기 핸들 재획득 가능·내용 불변 |
| POSIX(미검증) | 경로 교체는 무해(검증 핸들 사용), `O_NOFOLLOW`. **같은 inode 제자리 수정은 막지 못함** | 코드 분석만. 이번 PC에서 실행 불가 |

**부분 바이트 전송 한계(POSIX 해당):**
- 전체 응답은 스트리밍 해시를 계산하고 마지막 청크(최대 256KiB)를 보류해 불일치 시 연결을 끊는다. 그 전에 보낸 앞부분에는 변형된 바이트가 포함될 수 있다. 클라이언트는 Content-Length 미달의 잘린 응답을 받으며(React `fetch`·브라우저 다운로드는 실패 처리) 완전한 잘못된 파일은 받지 않는다.
- Range 응답은 부분 구간을 해시로 검증할 수 없다. 마지막 청크 전 핸들 식별자(장치·inode·크기·mtime_ns)만 재확인하므로, mtime을 되돌리는 의도적 제자리 수정은 그 구간의 변형 바이트를 전달할 수 있다. 다음 요청은 사전 전체 해시에서 차단된다.
- 해시 사전 검증과 응답 시작 사이 및 응답 도중의 위 위험은 Windows에서는 공유 모드로 차단된다.

**다중 worker/프로세스:**
- 같은 DB·출력 루트를 쓰는 독립 프로세스 2개(8002·8003)에서 VERIFIED→CORRUPT→VERIFIED 판정이 동일했고, 두 프로세스로 나눈 동시 Range 32건이 모두 정확했다. 무결성 판정은 요청별 DB 해시+파일 재계산이라 프로세스 간 공유 캐시가 없어 불일치가 생기지 않는다.
- 렌더 접수·완료는 기존 DB 행 잠금·활성 행 제약·advisory lock·owner fencing(QA-01)을 그대로 사용한다. 프로세스 로컬 registry(영속 비활성 모드)는 다중 worker에 부적합하므로 운영은 영속 모드 전제다.
- 시작 가드는 프로세스마다 실행된다. 서로 다른 호스트가 다른 출력 루트를 쓰면 MISSING으로 차단된다(안전하지만 가용성 저하). 해시 비용은 worker 수만큼 늘어나며 공유되지 않는다.

**검증 비용 절감 대안(적용하지 않음 — 승인 필요):**

| 대안 | 비용 | 무결성 | 판단 |
| --- | --- | --- | --- |
| 현재: 요청마다 전체 SHA-256 | Range당 파일 전체 읽기(warm 1GiB 약 0.58초, 하드 자막 약 2배) | 가장 강함 | 현재 결과물(최대 수 MB)에는 충분 |
| 진행 중 해시 공유(singleflight, 같은 핸들 식별자) | 동시 요청 중복 제거 | Windows 쓰기 거부 하에서 동일 내용 보장 가능, POSIX 약화 | 동시 Range가 많은 긴 영상이 생기면 1순위 후보 |
| 청크 해시(Merkle) 완료 시 기록, Range는 해당 청크만 검증 | 구간 크기에 비례 | 강함(구간 단위 검증 가능, POSIX 부분 전송 문제도 해결) | DB/사이드카 스키마 변경 필요 — 장기 권장 |
| 목록은 `UNCHECKED`, 선택 렌더만 검증 | 목록 비용 제거 | 동일(미검증은 비가용) | React 흐름 변경 필요 |
| 크기·mtime 캐시 | 매우 낮음 | **약함**(동일 크기·mtime 보존 변형 미검출) | 채택 불가 |
| 출력 폴더 읽기 전용 ACL·정기 감사 | 낮음 | 보조 수단 | 해시 검증과 병행 가능 |

## 4. 기존 기능 호환성

- **React:** Vitest 52건, `tsc -b`, Mock Chrome 전체 32건 통과(WEB-01~04·09~12, QA-01, QA-03). 실제 Chrome은 격리 스택에서 미리보기·다운로드·차단 화면 확인. 새 필드가 없는 이전 API 응답과도 호환(QA-03 테스트).
- **Streamlit(`frontend/app.py`) — 안전성 문제 없음, 안내 누락 있음:** `download_available`/`hard_subtitle_download_available`이 true일 때만 다운로드를 준비하고, 404/409 응답에서 바이트를 받지 않는다. 그러나 ① 409(무결성 차단)를 “아직 다운로드 가능한 렌더링 결과가 아닙니다”로 잘못 안내, ② COMPLETED·비가용을 일반 경고 한 문장으로만 표시, ③ 새 하드 자막 상태 `CORRUPT`/`UNVERIFIED`/`BASE_UNAVAILABLE`에서 아무 문구도 없음. Streamlit 프런트 테스트 64건은 통과. **이번에 수정하지 않았다.** 최소 변경안(기존 UI 제거 없음):

```python
# frontend/app.py — _render_project_render_status의 마지막 else
    else:
        reason = {"RENDER_FILE_CORRUPT": "결과 파일 내용이 렌더 완료 때와 달라(SHA-256 불일치) 제공을 막았습니다.",
                  "RENDER_FILE_UNVERIFIED": "무결성 기록이 없는 과거 렌더라 제공하지 않습니다.",
                  }.get(status.get("safe_error_code"), "결과 파일을 찾을 수 없습니다.")
        st.warning(f"렌더링은 완료됐지만 결과 파일을 다운로드할 수 없습니다. {reason}")

# _render_hard_subtitle_status 끝에 추가
    elif state == "CORRUPT":
        st.warning("자막 적용 영상 파일이 렌더 완료 때와 달라 제공하지 않습니다.")
    elif state == "UNVERIFIED":
        st.warning("자막 적용 영상의 무결성 기록이 없어 제공하지 않습니다.")
    elif state == "BASE_UNAVAILABLE":
        st.warning("기본 영상을 확인할 수 없어 자막 적용 영상도 제공하지 않습니다.")

# frontend/api_client.py — _download_project_video의 409 분기
        if response.status_code == 409:
            code = (response.json().get("detail") or {}).get("code") if response.headers.get(
                "content-type", "").startswith("application/json") else None
            message = {"RENDER_FILE_CORRUPT": "영상 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다.",
                       "RENDER_FILE_UNVERIFIED": "무결성 기록이 없는 렌더라 다운로드를 제공하지 않습니다.",
                       "SUBTITLED_RENDER_CORRUPT": "자막 영상 파일이 렌더 완료 때와 달라 다운로드를 차단했습니다.",
                       "SUBTITLED_RENDER_UNVERIFIED": "무결성 기록이 없는 자막 영상이라 다운로드를 제공하지 않습니다.",
                       }.get(code, "아직 다운로드 가능한 렌더링 결과가 아닙니다.")
            raise BackendApiError(message, status_code=409)
```

- **기존 백엔드 실패 3건:** `test_alembic_foundation`, `test_database`, `test_product_models`의 테이블 집합 단언. 세 테스트 파일은 커밋 `c59dd2e`의 15개 테이블 목록 그대로이며, WEB-08B의 미커밋 변경(`models/__init__.py`에 `ProjectRenderRun` 등록, 신규 `models/render.py`)이 `project_render_runs`를 메타데이터에 추가해 실패한다. 실패 메시지의 차이는 `project_render_runs` 하나뿐이고 QA-03은 테이블을 추가하지 않았다(컬럼만 추가). **QA-03 영향 없음.** 기대 목록 갱신은 해당 테스트 소유 범위라 수정하지 않았다(필요 시 별도 승인).
- **expected failure 현황:** 저장소 테스트(backend·frontend tests·web)에 활성 `expectedFailure`/`it.fails` 표시 **0건**. QA-01의 동일 크기 손상 테스트는 QA-03에서 실제 해결 후 일반 테스트로 전환됐고 이번 격리 PostgreSQL 재실행에서도 통과했다.
- **회귀 수치:** 백엔드 전체 593건 중 554 통과·36 건너뜀·기존 3 실패(QA-03과 동일). 격리 PostgreSQL QA-01 3건+QA-03 migration 1건 통과(일회용 DB 생성·삭제).

## 5. 최종 적용 계획(승인 후 실행)

전제: 사용자 승인, 작업 창 동안 Vite/React 사용자 조작 없음, 승인자가 관찰 가능. 각 단계는 앞 단계 PASS일 때만 진행한다.

| 단계 | 내용 | 중단 조건 | 롤백 |
| --- | --- | --- | --- |
| 0. 사전 확인 | Git HEAD·미커밋·보호 테스트 3개 해시, 개발 DB revision `b8c01e2a4f60`, 렌더 행 수(현재 0)·활성 처리/분석/렌더 0·PG 활성 쿼리 0, 원본·렌더 인벤토리 해시 작성 | revision 불일치, 활성 작업 존재, 인벤토리 오류 | 없음(변경 전) |
| 1. 백업 | `pg_dump -Fc`를 `temporary/qa04-rollout-<날짜>/db.dump`로, SHA-256·`pg_restore -l` 확인, 파일 인벤토리 JSON 저장 | 덤프 실패, 목록 검사 실패, 디스크 부족 | 없음 |
| 2. 격리 복원 | 격리 컨테이너 55432 새 DB에 `--exit-on-error` 복원 → 전 테이블 행 수 원본과 일치 → `alembic upgrade e3a1c9d27b45` → 행 수·내용 md5 동일·해시 NULL·CHECK 3개 확인(QA-03 스크립트 재사용) | 복원/업그레이드 실패, 행 수·md5 불일치 | 격리 DB 삭제 |
| 3. 새 렌더 접수 중지 | 활성 렌더·처리 0 재확인. 인증·플래그가 없으므로 운영 규칙으로 중지: 사용자에게 공지하고 React/Streamlit 렌더 조작 금지, 5173 사용 중단 요청. 이 상태에서 `project_render_runs` 행 수 고정 확인 | 활성 행 존재 또는 조작 중지 불가 | 중지 해제만 |
| 4. migration 적용 | 기존 DB에 `alembic upgrade e3a1c9d27b45`(환경변수로 5432 명시, 출력 기록) → revision 확인, 세 컬럼 nullable·CHECK 3개, 전 테이블 행 수 0단계와 동일 | 오류, 행 수 변화 | 렌더 행이 그대로 0건이면 `alembic downgrade b8c01e2a4f60`(해시 증거 손실 없음). 렌더 행이 생겼거나 downgrade 실패 시 1단계 덤프로 복원(별도 승인) |
| 5. FastAPI 재시작 | 기존 8000 프로세스만 식별해 종료(명령줄 `backend.app.main:app`·포트 8000 확인) → 같은 환경(`CUTORY_RENDER_PERSISTENCE_ENABLED=1`, 번들 FFmpeg `PATH`, 기존 글꼴 설정 유지)으로 새 코드 기동. Vite·PostgreSQL·Tailscale 재시작 없음 | 시작 가드 오류(컬럼 없음), `/health` 실패, 포트 점유 | 이전 코드로 되돌릴 수 없으므로(미커밋 작업 트리) 4단계 이전 상태가 필요하면 downgrade 후 기동; 시작 실패 원인이 가드면 4단계 결과 재확인 |
| 6. 실제 검증 | `/rendering`·`/renders` 응답에 `integrity_status` 필드, 기존 프로젝트 목록·편집 계획 조회 정상 → 승인된 QA 프로젝트 1건만 실제 렌더 → DB 세 해시=파일 SHA-256 → 두 MP4 다운로드·Range·Chrome 미리보기 → API 재시작 후 동일 확인(WEB-08C 미검증 항목 해소) | 해시 불일치, COMPLETED 아닌 상태, 다운로드 오류, 다른 프로젝트 데이터 변화 | QA 렌더 행·파일은 기록으로 보존(삭제 금지), 렌더 접수 중지 유지, 원인 조사 후 결정 |
| 7. 사후 확인 | 원본·기존 렌더 인벤토리 해시 동일, PG localhost 게시 유지, 보호 테스트 해시 동일, 문서 갱신 | 불일치 | 원인 조사; 데이터 복구는 1단계 백업 기준(승인) |

장애 시 공통: 새 렌더 접수 중지를 유지하고, 렌더 기록·파일을 삭제하거나 해시를 수동 재등록하지 않는다. DB 복원은 백업 해시 확인 후 승인받아 수행한다. migration 이후 이전 코드로 렌더하면 그 기록은 해시 NULL로 새 코드에서 차단되므로 4→5단계 사이 렌더를 금지한다.

## 6. 판정: CONDITIONAL PASS

**근거(PASS 요소):** 실제 FFmpeg/Docker 렌더에서 세 해시가 파일과 일치하고, 재초기화 후에도 유지되며, 정상 다운로드·Range·실제 Chrome 재생이 동작하고, 동일 크기·다른 크기·누락·하드 자막·SRT·해시 없음 변조가 모두 의도대로 차단·복원됐다. Windows에서 스트리밍 중 변경이 OS 수준에서 거부됨을 실측했다. migration은 격리 합성 데이터와 실제 백업 복원 데이터에서 무손실이었고 현재 DB의 렌더 행이 0건이라 과거 기록 차단 영향이 없다. 회귀에서 새 실패는 없다.

**조건(PASS가 아닌 이유):**
1. 5장의 순서(특히 migration 후 FastAPI 재시작, 그 사이 렌더 금지)와 중단 조건을 지킬 것. 새 코드는 미적용 DB에서 영속 모드 시작을 거부한다.
2. 운영 정책 승인: 해시 없는 과거 기록 기본 차단, 기본 MP4 종속 하드 자막 차단, 409 코드·React 문구, 요청마다 전체 해시 비용.
3. 배포 호스트가 Windows 단일 호스트일 것. POSIX·다중 호스트 배포 전에는 청크 해시 등 추가 설계가 필요하다.
4. 긴 결과 영상(수백 MB 이상)이 생기면 Range 지연을 재측정하고 대안 승인 여부를 결정할 것.
5. Streamlit 안내 누락(안전성 무관)과 기존 테이블 집합 테스트 3건은 별도 처리 대상으로 인지할 것.

FAIL 사유(데이터 손실, 변조 미검출, 기존 기능 회귀)는 발견되지 않았다.

## 남은 위험

- POSIX 동작, cold cache·외장 디스크·긴 영상의 실측, 실제 사용자 영상 렌더(이번은 합성 영상), 다중 호스트 출력 공유, Streamlit 실제 클릭은 미검증.
- 실행 중인 8000은 여전히 QA-03 이전 코드이며 Vite는 QA-03 React를 제공 중이다(호환 확인).
- 인증·소유권이 없어 공개 배포 경계로 해석하면 안 된다.

## 산출물

- `backend/tests/qa04_isolated_server.py`: 격리 전용 서버(가드 포함, unittest 수집 대상 아님).
- `web/e2e-real/qa04.spec.ts`: 실제 Chrome 검증(환경변수 미설정 시 skip, `QA04_MODE=clean|corrupt`).
- 시드·구동·변조·스트리밍 중 변경·다중 프로세스 스크립트와 결과 JSON은 세션 스크래치 경로에만 두었고 저장소에 추가하지 않았다(필요 시 재작성 가능한 절차를 이 문서에 기술).
