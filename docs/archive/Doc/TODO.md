# Cutory 현재 작업 상태

> 상태는 완료·진행·대기·보류로 표시한다. 검증 수준은 별도 열이다. 장기 작업의 상세 이력은 [루트 TODO](../TODO.md), 제품 단계는 [v2 Plan](../docs/roadmap/v2-plan.md)을 따른다.

| 작업 | 상태 | 검증 수준 | 다음 조건·근거 |
| --- | --- | --- | --- |
| React 업로드→분석→편집 계획→렌더→두 MP4 재생·다운로드 | 구현 완료 | 일부 실제 영상·Chrome E2E. 전체 영상 품질·모바일 Safari 미검증 | [WEB-04](../docs/handoff/web-04-react-e2e-validation.md), [WEB-07](../docs/handoff/web-07-render-preview-validation.md), [데모](../docs/handoff/demo-01-portfolio-edit-flow.md) |
| LLM/VLM 편집 제안과 화면 분석 | 구현 완료 | 로컬 Ollama·실사 데모 제한 검증. 정량 추천 품질 미검증 | 제안은 사용자가 적용·저장. fallback은 규칙 기반. [HANDOFF](HANDOFF.md) |
| P0 추천 이유·무음 판정·시각 조건 과포함 | **최신 코드 8000 적용 완료** | 관련 백엔드 테스트 24건·8014 격리 검증; 새 8000에서 실제 Ollama 음식 조건 2건, 기존 후보·MP4 다운로드·Vite 프록시 확인. 새 분석·렌더와 하드 자막 생성은 미검증 | 추가 시연에서 무음 표시·화면 캡처를 확인. 사용자 DB·영상·렌더 유지 |
| 포트폴리오 검은 MP4 캡처 | 완료 | 실제 Chrome에서 프레임이 보이는 자막 MP4 캡처 1건 | 재생 프레임 준비 후 캡처. [HANDOFF](HANDOFF.md) |
| 렌더 기록 영속화·SHA-256 제공 차단 | 코드 구현·현재 개발 DB 적용 완료 | WEB-08B 격리 재시작 E2E, QA-03~05 격리 무결성 검증. 현재 DB revision `e3a1c9d27b45`; 기존 MP4 다운로드·로컬 파일 해시 일치 확인. 새 실사 렌더 후 재시작 E2E는 미검증 | [WEB-08C](../docs/handoff/web-08c-production-local-rollout.md), [QA-03](../docs/handoff/qa-03-render-integrity-implementation.md), [HANDOFF](HANDOFF.md) |
| 사용자 데이터 백업·격리 복원 검증 (P0) | 완료 | DB 덤프 해시·목록 검사, 37개 파일 SHA-256 매니페스트·복사본 일치, 격리 복원본 17개 테이블 490행 md5 일치 | 저장소 밖 `Cutory-Backups/backup-20261104-165721`. 신규 렌더 뒤 재백업 필요. [기록](../docs/handoff/backup-restore-2026-11-04.md) |
| 현재 8000 실사 데모 신규 렌더 E2E (P0) | 완료 | API 실제 렌더 1회 COMPLETED, 세 파일 DB·디스크·다운로드 SHA-256 일치, 길이·순서·한국어 하드 자막 확인, 증분 백업·복원 검증 | 렌더 `a0984ae2…`. 재시작 후 영속성은 별도 P0. [기록](../docs/handoff/render-e2e-8000-2026-11-04.md) |
| 서버 재시작 후 렌더 영속성 (P0) | 완료 | 2026-11-05 계획 재시작 1회(PID 13384→45336) 뒤 렌더 COMPLETED·VERIFIED, 두 MP4 다운로드 해시·ETag, VLM 근거 8건·계획, DB 전 테이블 md5·파일 40개 해시가 재시작 전과 동일 | [기록](../docs/handoff/restart-persistence-8000-2026-11-05.md) |
| 8000 정지·기동 절차 (`run-8000.ps1`·`stop_server.py`) | 완료(현재 PC) | Ctrl+C 정지(13384)·Ctrl+Break 정지(45336)·allowlist 기동(38684) 각 1회 실제 검증. 재부팅 직후 기동 미검증 | Git 제외 스크립트, 이 PC 경로에 고정. 자동 시작 미등록. 14:31 정지 후 자체 포트 재확인 단계 `WinError 6` → 2026-11-06 수정(콘솔 처리를 도우미 프로세스로 분리), 8099 더미 8가지 격리 검증 통과, **실제 8000 정지 미검증**. VLM 진행 여부는 스크립트 검사 대상 아님. [정지 스크립트 WinError 6 수정](../docs/handoff/stop-server-winerror6-2026-11-06.md) |
| 8000 세션 토큰 환경 변수 상속 제거 (P0) | 완료 | 2026-11-05 10:36 실제 교체(45336→38684). 새 프로세스 세션 변수·토큰 이름 0건, health·revision·렌더 VERIFIED·다운로드 해시·DB 491행·파일 40개 동일 | [기록](../docs/handoff/env-allowlist-8000-2026-11-05.md) |
| 5173 Vite 세션 변수 상속 (P1) | 대기 | 이름만 확인: Claude 토큰 없음, Codex 세션 변수 17개·`GIT_CONFIG_*` 상속 | 재시작 승인 시 allowlist 기동 방식 적용 검토 |
| SRT 다운로드 API·React 버튼 (P1) | 완료(8000 반영) | 백엔드 신규 9건·전체 636건 OK(skip 36), `tests/` 72건, React 신규 3건·전체 58건, `tsc` 통과. 실제 DB 읽기 전용 인프로세스로 기존 렌더 3건 SRT 해시·ETag 일치. 11:05 8000 반영(PID 49648) 후 실제 API 3건·5173 Chrome 클릭 다운로드(`final.srt`) 해시·ETag 일치, MP4 2종 회귀 통과 | Streamlit 미지원. [기록](../docs/handoff/p1-srt-download-2026-11-05.md) |
| VLM 실행 상태 DB 기반 조회 (P1) | **완료(8000 반영)** | 신규 회귀 7건(수정 전 코드에서 5건 실패 확인), 백엔드 전체 643건 OK(skip 36). 2026-11-05 14:31 8000 반영(PID 49648→55828, 중단 약 20초). 실제 API: 데모 `COMPLETED`·total 8·captioned 8·`DATABASE`, 나머지 13개 `NOT_STARTED`. 5173 Chrome에서 ‘gemma3:4b · 분석 8/8’ 표시, 분석 없는 프로젝트는 기존 안내 문구(비GET 0건). DB 17개 테이블 491행 md5·revision·파일 40개 SHA-256·두 MP4 다운로드 해시·ETag 재시작 전후 동일 | 실패 건수·오류 코드는 DB에 없어 복원 안 됨. [VLM 상태 복원 기록](../docs/handoff/p1-vlm-status-restore-2026-11-05.md) |
| n8n 렌더 완료·실패 후속 처리 MVP | 구현·격리 테스트 완료, **n8n 2.46.6 합성 이벤트 검증 완료(1단계), 8000 미반영** | 신규 백엔드 27건·전체 670건 OK(skip 38, 신규 skip 0), Node 로직 검증. 격리 컨테이너 `cutory-n8n`(127.0.0.1:5678)에서 import·활성화, 403 인증 실패, 200 `recorded`/`duplicate`, 409 충돌, 기록 실패 500, 8건 동시 중복 1건만 기록, 재시작·재생성 후 유지(17/17·4/4). task runner에 `process` 전역이 없어 JS 수정. **실행 이력에 토큰 평문 저장 발견 → 성공·실패·수동 저장 안 함, 실제 삭제 1분 주기로 설정**. 새 테스트 토큰으로 재검증 17/17, 실행 18건이 약 40초 안에 테이블에서 삭제됨, 옛 토큰 403. SQLite 바이트 잔존·과거 오류 실행 13건은 미정리. Cutory 실시간 전송·실제 렌더 E2E 미검증 | HMAC 전환 설계·격리 검증 완료(구현 안 함, `crypto` 허용 필요). 구현 여부·과거 이력 정리 방식(소유자 UI 또는 `MAX_AGE`+VACUUM)·운영 키·8000 재시작은 승인 필요. [HMAC 설계](../docs/handoff/n8n-hmac-design-2026-11-06.md), [보안 정리](../docs/handoff/n8n-security-cleanup-2026-11-06.md), [1단계 기록](../docs/handoff/n8n-live-stage1-2026-11-06.md), [설계](../docs/handoff/n8n-render-events-design-2026-11-06.md), [deploy/n8n](../deploy/n8n/README.md) |
| P1~P3 독립 GT 동결·SceneCandidate 정량 평가 | 대기 | freeze-ready `PENDING` 28건; 정식 평가 미실행 | 인간 독립 주석·검토·승인 및 자료 확보. [EVAL-02](../docs/handoff/eval-02-gt-freeze-preparation.md) |
| 제출 범위 밖 기능·공개 배포 | 보류 | 미검증 | 11월 14일 제출 이후 별도 우선순위 결정. 인증·소유권 검증 없이 공개 배포 금지 |

2026-11-03 격리 검증: 실제 춤 영상 오디오는 상대 기준 `LONG_SILENCE`이지만 `confirmed_silence=False`; 복제된 실사 프로젝트의 Chrome 후보 5건에는 ‘실제 무음 미확인’이 표시되고 단정적 무음 경고는 0건이었다. 기본 MP4 다운로드 해시는 복제 산출물과 일치했다. 하드 자막 파일 복제가 Windows 읽기 거부로 실패해 격리 다운로드는 미검증이다. 8014는 종료했으며 [HANDOFF](HANDOFF.md)에 범위를 기록했다.

2026-11-04 사전 점검: 기존 8000의 비밀을 제외한 환경 설정, 글꼴 해시, `.env` DB 접속과 revision을 확인했다. 명시적 로컬 Ollama 인자로 8014를 격리 기동해 health·렌더 이력 조회·음식 시각 조건 2건을 확인했다. 점검 당시 14개 프로젝트의 처리·장면 분석·렌더·VLM 활성 상태는 0건이었다. 8014는 종료했고 8000·5173은 유지했다. 재시작 직전에는 활성 상태를 다시 확인한다.

2026-11-04 적용 시도 중단: 기존 8000 PID 46708, 활성 작업 0건, DB `e3a1c9d27b45`, FFmpeg·글꼴 해시·로컬 Ollama를 재확인했다. 기존 8000 PATH에는 Docker CLI가 있지만 점검 셸은 별도 sandbox 계정·PATH라 접근 거부됐다. 8000·5173 및 데이터는 유지했다.

2026-11-04 Docker 원인 조사: 하드 자막 생성은 Docker/libass가 필수이며 기본 MP4·SRT는 로컬 FFmpeg를 사용한다. 기존 8000과 같은 `Pro` 계정의 동일 Python 자식 프로세스에서 Docker 엔진 29.9.2 접근 및 고정 FFmpeg 이미지 캐시를 확인했다. 계정·PATH 차이로 이전 접근 거부를 설명할 수 있다. **8000 교체는 설정 재현 가능으로 판단하되 이번에는 미실행**; 실제 하드 자막 새 렌더와 교체 후 검증은 남았다.

2026-11-04 8000 적용: 활성 작업 0건, DB revision `e3a1c9d27b45`, FFmpeg 9.0.2·글꼴 해시·Ollama·Docker 엔진을 재확인했다. 기존 PID 46708에만 Ctrl+C를 보내 정상 종료하고 동일 `Pro` 계정의 검증된 런처로 최신 코드 PID 13384를 기동했다. health·기존 프로젝트·VLM 화면 설명 8건·실제 Ollama 음식 조건 케이크 2건·기본 MP4 다운로드/로컬 파일 SHA-256 일치·5173 프록시를 확인했다. 5173 PID 41712 유지. 신규 하드 자막 렌더는 격리 입력 미준비로 실행하지 않았다.

2026-11-04 신규 하드 자막 최소 검증: `Pro` 계정에서 사용자 DB와 분리한 2초 합성 MP4·한국어 SRT로 기존 Docker/libass 함수를 1회 실행했다. `final-subtitled.mp4` 생성, FFprobe H.264/AAC·2.00초, 1초 프레임 한글 표시, 출력 SHA-256의 독립 계산 일치를 확인했다. 격리 산출물은 확인 후 삭제했다. **제품 API를 통한 신규 렌더·실사 영상 전체 자막 품질 검증은 미실행**이다. 8000·5173은 유지했다.
