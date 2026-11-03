# Cutory 현재 작업 상태

> 상태는 완료·진행·대기·보류로 표시한다. 검증 수준은 별도 열이다. 장기 작업의 상세 이력은 [루트 TODO](../TODO.md), 제품 단계는 [v2 Plan](../docs/roadmap/v2-plan.md)을 따른다.

| 작업 | 상태 | 검증 수준 | 다음 조건·근거 |
| --- | --- | --- | --- |
| React 업로드→분석→편집 계획→렌더→두 MP4 재생·다운로드 | 구현 완료 | 일부 실제 영상·Chrome E2E. 전체 영상 품질·모바일 Safari 미검증 | [WEB-04](../docs/handoff/web-04-react-e2e-validation.md), [WEB-07](../docs/handoff/web-07-render-preview-validation.md), [데모](../docs/handoff/demo-01-portfolio-edit-flow.md) |
| LLM/VLM 편집 제안과 화면 분석 | 구현 완료 | 로컬 Ollama·실사 데모 제한 검증. 정량 추천 품질 미검증 | 제안은 사용자가 적용·저장. fallback은 규칙 기반. [HANDOFF](HANDOFF.md) |
| P0 추천 이유·무음 판정·시각 조건 과포함 | **최신 코드 8000 적용 완료** | 관련 백엔드 테스트 24건·8014 격리 검증; 새 8000에서 실제 Ollama 음식 조건 2건, 기존 후보·MP4 다운로드·Vite 프록시 확인. 새 분석·렌더와 하드 자막 생성은 미검증 | 추가 시연에서 무음 표시·화면 캡처를 확인. 사용자 DB·영상·렌더 유지 |
| 포트폴리오 검은 MP4 캡처 | 완료 | 실제 Chrome에서 프레임이 보이는 자막 MP4 캡처 1건 | 재생 프레임 준비 후 캡처. [HANDOFF](HANDOFF.md) |
| 렌더 기록 영속화·SHA-256 제공 차단 | 코드 구현·현재 개발 DB 적용 완료 | WEB-08B 격리 재시작 E2E, QA-03~05 격리 무결성 검증. 현재 DB revision `e3a1c9d27b45`; 기존 MP4 다운로드·로컬 파일 해시 일치 확인. 새 실사 렌더 후 재시작 E2E는 미검증 | [WEB-08C](../docs/handoff/web-08c-production-local-rollout.md), [QA-03](../docs/handoff/qa-03-render-integrity-implementation.md), [HANDOFF](HANDOFF.md) |
| P1~P3 독립 GT 동결·SceneCandidate 정량 평가 | 대기 | freeze-ready `PENDING` 28건; 정식 평가 미실행 | 인간 독립 주석·검토·승인 및 자료 확보. [EVAL-02](../docs/handoff/eval-02-gt-freeze-preparation.md) |
| 제출 범위 밖 기능·공개 배포 | 보류 | 미검증 | 11월 14일 제출 이후 별도 우선순위 결정. 인증·소유권 검증 없이 공개 배포 금지 |

2026-11-03 격리 검증: 실제 춤 영상 오디오는 상대 기준 `LONG_SILENCE`이지만 `confirmed_silence=False`; 복제된 실사 프로젝트의 Chrome 후보 5건에는 ‘실제 무음 미확인’이 표시되고 단정적 무음 경고는 0건이었다. 기본 MP4 다운로드 해시는 복제 산출물과 일치했다. 하드 자막 파일 복제가 Windows 읽기 거부로 실패해 격리 다운로드는 미검증이다. 8014는 종료했으며 [HANDOFF](HANDOFF.md)에 범위를 기록했다.

2026-11-04 사전 점검: 기존 8000의 비밀을 제외한 환경 설정, 글꼴 해시, `.env` DB 접속과 revision을 확인했다. 명시적 로컬 Ollama 인자로 8014를 격리 기동해 health·렌더 이력 조회·음식 시각 조건 2건을 확인했다. 점검 당시 14개 프로젝트의 처리·장면 분석·렌더·VLM 활성 상태는 0건이었다. 8014는 종료했고 8000·5173은 유지했다. 재시작 직전에는 활성 상태를 다시 확인한다.

2026-11-04 적용 시도 중단: 기존 8000 PID 46708, 활성 작업 0건, DB `e3a1c9d27b45`, FFmpeg·글꼴 해시·로컬 Ollama를 재확인했다. 기존 8000 PATH에는 Docker CLI가 있지만 점검 셸은 별도 sandbox 계정·PATH라 접근 거부됐다. 8000·5173 및 데이터는 유지했다.

2026-11-04 Docker 원인 조사: 하드 자막 생성은 Docker/libass가 필수이며 기본 MP4·SRT는 로컬 FFmpeg를 사용한다. 기존 8000과 같은 `Pro` 계정의 동일 Python 자식 프로세스에서 Docker 엔진 29.9.2 접근 및 고정 FFmpeg 이미지 캐시를 확인했다. 계정·PATH 차이로 이전 접근 거부를 설명할 수 있다. **8000 교체는 설정 재현 가능으로 판단하되 이번에는 미실행**; 실제 하드 자막 새 렌더와 교체 후 검증은 남았다.

2026-11-04 8000 적용: 활성 작업 0건, DB revision `e3a1c9d27b45`, FFmpeg 9.0.2·글꼴 해시·Ollama·Docker 엔진을 재확인했다. 기존 PID 46708에만 Ctrl+C를 보내 정상 종료하고 동일 `Pro` 계정의 검증된 런처로 최신 코드 PID 13384를 기동했다. health·기존 프로젝트·VLM 화면 설명 8건·실제 Ollama 음식 조건 케이크 2건·기본 MP4 다운로드/로컬 파일 SHA-256 일치·5173 프록시를 확인했다. 5173 PID 41712 유지. 신규 하드 자막 렌더는 격리 입력 미준비로 실행하지 않았다.

2026-11-04 신규 하드 자막 최소 검증: `Pro` 계정에서 사용자 DB와 분리한 2초 합성 MP4·한국어 SRT로 기존 Docker/libass 함수를 1회 실행했다. `final-subtitled.mp4` 생성, FFprobe H.264/AAC·2.00초, 1초 프레임 한글 표시, 출력 SHA-256의 독립 계산 일치를 확인했다. 격리 산출물은 확인 후 삭제했다. **제품 API를 통한 신규 렌더·실사 영상 전체 자막 품질 검증은 미실행**이다. 8000·5173은 유지했다.
