# P1 SRT 다운로드 — 2026-11-05

범위: 이미 생성·저장·SHA-256 기록되는 `final.srt`를 React에서 내려받는 기능. 신규 렌더·LLM·VLM 호출, migration, 원본·렌더 파일 변경, 8000·5173 재시작, 커밋·Push 없음.

## 구현

- API `GET /projects/{project_id}/renders/{render_id_hex}/subtitles/download` (`backend/app/routers/projects.py`). 기존 MP4·하드 자막 다운로드와 같은 구조를 재사용한다: 렌더 ID 형식(소문자 32자리 hex) 검사 422 `INVALID_RENDER_ID` → 프로젝트 없음 404 → `_completed_result_or_error`(진행 중·실패 409 `RENDER_NOT_COMPLETED`, 없음·다른 프로젝트 404 `RENDER_NOT_FOUND`) → 허용 경로 재구성(`_render_output_path`: 루트·프로젝트·렌더 ID·심볼릭 링크 검사) → `verify_file(keep_open=True)` → `VerifiedFileResponse`.
- SRT 오류: 자막 없음·생성 실패·파일 누락 404 `SUBTITLE_FILE_NOT_FOUND`, 내용 변조 409 `SUBTITLE_FILE_CORRUPT`, 기록 해시 없음 409 `SUBTITLE_FILE_UNVERIFIED`.
- 응답: `Content-Type: application/x-subrip; charset=utf-8`, `Content-Disposition: attachment; filename="<render_id_hex>.srt"`, 강한 ETag `"sha256-<hex>"`. 전체 응답은 스트리밍 중 SHA-256을 다시 계산해 불일치 시 마지막 청크를 보내지 않는다. Range는 206을 유지한다(기존 응답 클래스 동작).
- 상태·기록 응답에 `subtitle_download_available`(bool, 기본 false)·`subtitle_download_url`(nullable)을 추가했다(하위 호환 추가 필드). COMPLETED이고 SRT가 VERIFIED일 때만 URL을 준다. SRT는 MP4 인코딩과 별도로 생성되므로 기본 MP4 무결성과 독립적으로 판정한다(하드 자막 MP4는 기존대로 기본 MP4에 종속).
- 경로 순서: 일반 `/{render_id:path}/download`보다 먼저 등록해 경로 변수에 흡수되지 않게 했다. 기존 MP4·하드 자막 경로와 응답은 바꾸지 않았다.
- React (`web/src/api/edit-render.ts`, `web/src/features/edit/edit-render.tsx`): 다운로드 종류 `srt`, 결과 영역의 **‘자막(SRT) 다운로드’** 버튼. 상태의 URL이 기대 경로와 정확히 같고 `subtitle_download_available === true`이며 렌더가 COMPLETED일 때만 활성화된다. 필드가 없는 이전 서버에서는 비활성. 응답 형식이 `application/x-subrip`이 아니면 거부, 오류 코드별 문구, 실패 시 렌더 상태 재조회. 저장 파일명 `final.srt`. SRT 무결성 안내 문구를 “진단만”에서 실제 차단 안내로 바꿨다.

## 검증

- 백엔드 신규 `backend/tests/test_srt_download_api.py` 9건 통과: 성공(본문·Content-Type·attachment 파일명·ETag=SHA-256), Range 206, 자막 없음/생성 실패/파일 미작성, 완료 후 삭제 404, 같은 크기 변조 409 CORRUPT(기본 MP4는 200 유지), 해시 없음 409 UNVERIFIED, 진행 중 409·없는 렌더·다른 프로젝트·잘못된 ID 422, 렌더 디렉터리 밖 경로 차단, DB 기반 영속 레지스트리 재생성 후 다운로드·ETag와 변조 차단.
- 백엔드 전체 `unittest discover -s backend/tests`: 636건 OK(skipped 36, 기존 건너뜀이며 통과로 세지 않음). `tests/`(Streamlit 클라이언트) 72건 OK. 보호 대상 테스트 3개는 수정하지 않았다.
- React 신규 `web/src/test/srt-download.test.tsx` 3건 통과(버튼 클릭 → SRT 경로 요청·`final.srt` 저장·본문 일치, 변조·필드 없는 이전 서버·URL 불일치·미완료 시 비활성/null, 409 코드 문구·상태 재조회, 비SRT 응답 거부). Vitest 전체 14파일 58건 통과, `tsc -b` 오류 0.
- 실제 기존 렌더(읽기 전용): 새 코드를 인프로세스 `TestClient`로 띄우고 실제 개발 DB에 `default_transaction_read_only=on` 세션으로 연결해 실사 데모 프로젝트의 COMPLETED 렌더 3건(`a0984ae2…`, `59d20741…`, `cb2b80d2…`)을 GET만으로 확인했다. 세 SRT 모두 200 `application/x-subrip; charset=utf-8`, attachment 파일명, 본문 SHA-256 = DB `srt_sha256` = 디스크 파일, ETag 일치, Range 206, 첫 자막 “우와! 대단!”. 같은 렌더의 기본·하드 자막 MP4 다운로드 해시도 DB와 일치. 이 하네스는 영속 레지스트리의 만료 작업 정리(`SELECT … FOR UPDATE`)를 끈다(활성 렌더 0건을 먼저 확인). 검증 전후 DB 17개 테이블 491행 md5·파일 40개 SHA-256 동일.

## 미검증·남은 일

- 실행 중인 8000(PID 38684)은 이전 코드라 새 경로가 없다. 5173의 React는 새 버튼을 보이지만 서버가 필드를 주지 않아 비활성이다(하위 호환 동작). 실제 서버 반영과 브라우저 클릭 E2E는 8000 교체 승인 후 진행한다.
- Streamlit 클라이언트(`frontend/`)에는 SRT 다운로드를 추가하지 않았다.
- SRT 내용 품질(STT 오인식 “대박→대단” 등)은 이 기능 범위 밖이다.

## 8000 반영·실제 UI 검증 — 2026-11-05 11:05 (완료)

- 8000 PID 38684 → **49648**(Ctrl+Break 정상 종료 + allowlist 기동 1회). 새 경로가 실제 API에서 동작하고, 실사 데모 렌더 3건의 SRT 해시·ETag가 DB와 일치한다.
- 5173 실제 Chrome에서 버튼 클릭 → `final.srt` 다운로드(해시 = ETag), 기존 MP4 두 버튼 다운로드 해시 = ETag. 비활성·차단 상태는 브라우저 측 응답 변형으로만 확인(실데이터 미변경).
- 위 ‘미검증’ 첫 항목(실행 서버·브라우저 E2E)은 해소됐다. Streamlit 미지원과 SRT 내용 품질은 그대로 남는다. 상세는 [HANDOFF](../../Doc/HANDOFF.md).
