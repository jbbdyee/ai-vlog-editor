# Cutory 현재 작업 색인

범위와 완료 기준의 Source of Truth는 [v2 Detailed Plan](docs/roadmap/v2-plan.md)이다. 이 표는 다음 작업과 검증 근거를 찾기 위한 색인이며 평가 계약이나 GT를 정의하지 않는다. **작업 상태**(완료·진행 중·예정·구현됐지만 미검증·보류)와 **검증 수준**(분석·합성·제한된 실제 영상·정량 품질)은 별개다. 미실행·건너뜀은 통과가 아니다.

| 작업명 | 작업 상태 | 검증 수준 | 차단 사항 | 완료 조건 | 상세 계획·검증 근거 |
| --- | --- | --- | --- | --- | --- |
| MVP-07A 실제 영상 API 통합 검증 | 완료(한 건 범위) | P1-S01 제한된 실제 영상 API 검증; 품질 미평가 | 없음; UI·품질은 별도 작업 | MP4·SRT·하드 자막 MP4 생성, FFprobe·프레임·두 다운로드 확인 | [v2 Plan](docs/roadmap/v2-plan.md), [07A 기록](docs/handoff/mvp-07a-real-video-validation.md) |
| MVP-07B 원인 분석 | 완료(분석) | 실제 실행 재현·DB·코드 추적; 수정 검증 아님 | 없음; 수정은 후속 승인 범위 | STT 호환성·후보 경계·SRT 공백 원인과 미검증 사항 기록 | [v2 Plan](docs/roadmap/v2-plan.md), [07B 기록](docs/handoff/mvp-07b-root-cause-analysis.md) |
| MVP-07C STT 의존성 문제 해결 | 완료(로컬 Windows) | 깨끗한 설치·pip check·실제 WAV·P1-S01 소스 API·단위 회귀; 다른 OS 미검증 | 없음; 다른 OS·장시간 영상은 후속 검증 | `av==18.1.0` 설치 재현, 실제 STT·소스 처리 및 주요 오류 경로 확인 | [v2 Plan](docs/roadmap/v2-plan.md), [07B STT 분석](docs/handoff/mvp-07b-root-cause-analysis.md), [07C 검증](docs/handoff/mvp-07c-stt-dependency-validation.md) |
| MVP-07D SRT 공백 손실 수정 | 완료(로컬 Windows) | 77개 관련 테스트 통과·1개 권한 건너뜀; P1-S01 저장 전사·격리 SRT/하드 자막 프레임 확인 | 없음; 부분 단어 포함 정책·UI 실제 조작은 별도 검증 | 기존 DB·신규 STT의 원문 공백 복원, 시각·삽입 방어·기본 렌더/다운로드 회귀 확인 | [v2 Plan](docs/roadmap/v2-plan.md), [07B 자막 분석](docs/handoff/mvp-07b-root-cause-analysis.md), [07D 검증](docs/handoff/mvp-07d-subtitle-spacing-validation.md) |
| MVP-08A SceneCandidate 사건 단위 실험 설계 | 완료(분석·설계) | P1-S01 저장 Evidence·후보 기준선 재구성; 개선 실험·품질 평가는 미실행 | 없음; 구현은 별도 작업 | 현 규칙과 A~D 대안·사전 평가 지표·실험 순서·진입 조건 기록 | [v2 Plan](docs/roadmap/v2-plan.md), [08A 설계](docs/handoff/mvp-08a-scene-candidate-experiment-design.md) |
| MVP-08B SceneCandidate 로컬 사건 그룹화 실험 | 완료(오프라인 탐색) | P1-S01 저장 Evidence·후보 재생 및 D/C 비교; 전용 10건·관련 제품 22건 통과; P2·P3·정식 품질 미검증 | 제품 반영 전 독립 사건·부정 사례·동결 GT 필요 | 원본 후보 계보와 지지 공백을 보존한 EventProposal 생성, 위험·한계 보고 | [08A 설계](docs/handoff/mvp-08a-scene-candidate-experiment-design.md), [08B 실험](docs/handoff/mvp-08b-event-grouping-experiment.md) |
| MVP-08C SceneCandidate 로컬 그룹화 독립 평가 준비 | 완료(자료 조사·프로토콜) | P1~P3 미디어·GT·DB 현황 확인; 독립 D/C 품질 평가는 미실행 | P2·P3 영상·GT·분석 결과 부재, P1 미동결, 블라인드 주석 필요 | 사례 분리·주석 절차·false merge/split 지표·차단 요인과 진입 조건 기록 | [08B 실험](docs/handoff/mvp-08b-event-grouping-experiment.md), [08C 준비](docs/handoff/mvp-08c-independent-evaluation-readiness.md) |
| SceneCandidate 사건 단위 제품 개선 검토 | 예정 | 오프라인 탐색·독립 평가 설계만 완료; 제품 반영·정량 품질 검증 미실행 | GT 미동결, P2·P3 영상·독립 주석·부정 사례 준비 필요 | 사전 규칙으로 사건 포착·비지지 구간·false merge를 비교하고 제품 반영 여부 결정 | [v2 Plan](docs/roadmap/v2-plan.md), [08A 설계](docs/handoff/mvp-08a-scene-candidate-experiment-design.md), [08B 실험](docs/handoff/mvp-08b-event-grouping-experiment.md), [08C 준비](docs/handoff/mvp-08c-independent-evaluation-readiness.md) |
| Streamlit 실제 사용자 조작 검증 | 예정 | 기존 프론트엔드 테스트만; 실제 클릭 미실행 | 로컬 API·UI 실행과 검증 시나리오 준비 | 기본·자막 MP4 버튼 상태와 실제 클릭·다운로드 확인 | [v2 Plan](docs/roadmap/v2-plan.md), [06D 기록](docs/handoff/mvp-06d-subtitle-download-validation.md), [07A 기록](docs/handoff/mvp-07a-real-video-validation.md) |
| P1~P3 평가 데이터 및 GT 준비 | 진행 중(미완료) | 일부 P1 미동결 초안; 정량 품질 미평가 | P2·P3 주석, 인간 검토·GT freeze, 제안 ID 연결 | 기존 계약에 따른 데이터 확인·주석·동결 및 별도 평가 실행 | [v2 Plan](docs/roadmap/v2-plan.md), [focused dataset](evaluation/datasets/cutory-v2-focused-eval-v0.1/README.md) |

07A에서 선택한 5.54~6.12초 후보는 촬영자 확인 구간 4.00~6.22초와의 겹침을 기준으로 **검증 스크립트가 고른 것**이다. 자동 추천 품질 합격으로 집계하지 않는다. GT·Manifest·평가 계약은 결과에 맞춰 변경하지 않는다.
