# QA-01 — 렌더 실행 안정성 및 복구 시나리오

상태: **격리 PostgreSQL·Mock 렌더 검증 완료, 동일 크기 파일 손상 감지 결함 재현, 제품 코드 미수정.** 현재 개발 DB 쓰기·실제 영상 렌더·서버 재시작·커밋·Push는 수행하지 않았다.

## 기존 검증과 이번 범위

WEB-08B는 DB 기반 QUEUED→RUNNING→COMPLETED/FAILED 상태, 한 프로젝트 활성 행 제한, lease/owner lock, 완료 파일의 경로·크기 확인, 재시작 후 기록 조회, 이전 성공 접근, 파일 누락과 React 과거 결과 선택을 단위·격리 DB·실제 영상 E2E로 확인했다. WEB-08C는 기존 개발 DB에 migration과 새 API를 승인 후 적용했지만 현재 DB의 렌더 기록은 0건이며 새 완료 렌더의 재시작 복구는 미검증이다. 기존 보호 대상 백엔드 테스트 3개는 수정하지 않았다.

이번에는 기존 항목을 다시 구현하지 않고 **동시 접수, 다른 프로젝트 독립성, ownerless stale 기록, 실패 후 새 ID 재시도, 같은 크기의 파일 손상, 렌더 기록 API 오류**를 중점으로 검사했다. backend/tests/test_qa01_render_recovery.py는 환경변수로 지정한 일회용 격리 PostgreSQL DB만 허용한다. DB 이름은 cutory_qa01_ 접두사, 포트는 55432로 제한하며 매 실행 후 해당 DB만 제거했다. Base 모델로 일회용 DB 테이블을 만들었고 제품 DB에는 쓰지 않았다. 영상 바이트는 Mock이며 실제 MP4 검증이 아니다.

## 결과

| 시나리오 | 실제 확인 |
| --- | --- |
| 동일 프로젝트 동시 요청 | 두 registry의 스레드 동시 접수 중 한 건만 DB 행을 만들고 다른 요청은 거부됐다. PostgreSQL 프로젝트 행 잠금과 활성 행 제약을 사용했다. |
| 다른 프로젝트 | 첫 프로젝트가 QUEUED인 동안 두 번째 프로젝트를 독립적으로 접수·완료했다. |
| 실행 중 종료·lease | 실제 서버를 종료하지 않았다. ownerless RUNNING 만료 행을 격리 DB에 넣어 INTERRUPTED를 확인했다. 파일이 남은 ownerless QUEUED 만료 행은 RECONCILIATION_REQUIRED로 전이됐고 자동 재렌더는 없었다. |
| 살아 있는 owner | lease 시각을 의도적으로 과거로 바꿔도 작업 소유 advisory lock이 유지되는 동안 QUEUED를 중단 처리하지 않았다. |
| 실패와 재시도 | 실패 기록과 이전 성공 기록이 공존하고, 재시도는 새 render ID로 생성됐다. 새 registry 객체에서 최신 완료와 이전 3개 기록을 조회했다. |
| 결과 파일 누락 | 이전 완료 파일을 격리 출력에서 제거하자 다운로드 API는 404, 기록 API는 download_available=false와 RENDER_FILE_MISSING을 반환했다. 이 파일은 테스트가 생성한 Mock 출력이다. |
| 저장 계획 없음 | 격리 QA 프로젝트의 POST render는 HTTP 422, EMPTY_EDIT_PLAN이었다. 화면의 미저장 초안은 서버에 전달되지 않으므로 실제 저장 계획이 있다면 서버는 그 저장 계획으로 렌더한다. React는 미저장 초안에서 버튼을 차단한다. |
| 렌더 기록 API 오류 | React 단위·Mock Chrome에서 기록 조회 503 오류를 표시하면서 현재 완료 결과의 기본 MP4 다운로드 버튼을 유지했다. 실제 DB 장애 주입은 하지 않았다. |
| 동일 크기 손상 | **결함 재현.** 완료 후 격리 Mock MP4를 같은 크기의 다른 바이트로 바꾸자 다운로드 API가 200을 반환하고 download_available도 true였다. 기대하는 차단 assertion은 expected failure 1건으로 보존했다. |

격리 PostgreSQL 테스트는 정상 시나리오 **2건 통과, 결함 재현 expected failure 1건**이다. expected failure는 통과로 집계하지 않는다. 관련 백엔드 unittest 40건은 **26건 통과, 14건 건너뜀, 실패 0**이었다. 14건에는 Windows symlink 권한 1건과 FFmpeg 도구를 현재 테스트 셸 PATH에서 찾지 못한 합성 렌더 13건이 포함된다. React 전체 Vitest **45건 통과**, WEB-03/11/12와 QA-01 Mock Chrome **13건 통과**, TypeScript 검사와 Vite 빌드 통과했다. Mock 브라우저의 렌더·다운로드는 실제 영상이나 DB 검증이 아니다.

## 결함·수정 판단

현재 영속 기록은 결과 파일의 상대 경로·크기·코덱·재생 시간을 저장하지만 콘텐츠 SHA-256은 저장하지 않는다. 파일 제공 경로는 프로젝트/렌더 소속, 루트 이탈, symlink, 크기를 검사한다. 동일 크기의 사후 변형은 구분할 정보가 없어 API가 통과시킨다. 기존 MP4를 재검사 없이 유효하다고 간주해서는 안 된다.

권장 해결은 렌더 완료 시 기본·자막 MP4의 해시를 기록하고 조회·다운로드 시 대조하는 것이다. 이에는 영속 모델·Alembic migration 및 기존 완료 기록의 해시 부재 정책이 필요하다. **이번에는 migration을 작성·적용하거나 현재 DB를 변경하지 않았다.** 실제 FFprobe 재검사를 매 요청에 추가하는 대안은 기존 Mock 계약, 비용과 파일 제공 지연을 검토해야 하며 무검증으로 바로 적용하지 않는다. 데이터 모델 변경 승인 후 별도 구현·회귀 검증이 필요하다.

실제 프로세스 강제 종료, 다중 FastAPI worker/호스트, 장시간 DB 장애, 실제 렌더 MP4의 사후 손상 검출, 현재 개발 DB의 완료 렌더 재시작 복구는 미검증이다. 원본 영상·GT·Manifest·기존 렌더 파일·현재 DB와 실행 중인 FastAPI/Vite/Tailscale 설정은 변경하지 않았다.
