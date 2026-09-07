# MVP v1 Specification

## 1. 검증 질문

> 촬영 중 남긴 음성 편집 메모를 이용해 사용자가 의도한 장면을 찾고 실제 영상 파일로 추출할 수 있는가?

MVP v1은 전체 편집 서비스를 만드는 단계가 아니라 이 질문을 End-to-End로 검증하는 단계다.

## 2. 저장소에서 확인된 현재 상태

2026-09-07 현재 저장소에서 직접 확인된 상태는 다음과 같다.

- FastAPI 애플리케이션 구성
- `GET /health` 구현
- `POST /videos/upload` 기본 엔드포인트 구현
- Evaluation Dataset v0.1 시나리오 문서
- `evaluation/data/.gitkeep`

현재 업로드 엔드포인트는 `UploadFile`을 받아 파일명과 Content-Type을 반환하는 수준이다. 실제 파일 검증과 저장은 아직 구현하지 않았다.

## 3. Test 01 기준 데이터

| 항목 | 값 |
| --- | --- |
| 파일명 | `eval_01.MOV` |
| 영상 길이 | 21초 |
| Ground Truth | 10초~15초 |
| 편집 메모 시작 | 16초 |
| 편집 메모 | “AI야 방금 장면 꼭 살려줘.” |
| 환경 | 조용한 실내 |

원본 파일은 개인정보와 용량 문제로 Git에서 제외한다.

## 4. 범위

```text
Video Input
→ Audio Extraction
→ STT with Timestamp
→ Editing Memo Detection
→ Fixed-window Candidate Generation
→ IoU Evaluation
→ FFmpeg Cut
→ Output Video and Metadata
```

### 포함

- MOV/MP4 테스트 영상 입력
- FFmpeg를 이용한 오디오 추출
- 타임스탬프가 포함된 STT 결과
- 고정된 편집 메모 탐지
- 메모 이전 5·10·15·30초 후보 생성
- Ground Truth 대비 IoU 계산
- 선택된 구간의 MP4 생성
- 단계별 실패 원인 기록

### 제외

- 자유로운 자연어 편집 요청
- LLM/VLM과 의미 기반 장면 검색
- 자동 Narrative 구성
- 사용자 장기 선호 학습
- 숏폼 자동 생성
- Agent/Multi-Agent
- 운영 DB, Vector DB, Redis, 클라우드 배포

## 5. 권장 중간 결과

파이프라인은 최소한 다음 구조의 결과를 남긴다.

```text
outputs/<video-id>/
├─ transcript.json
├─ detected_memos.json
├─ candidate_intervals.json
├─ evaluation.json
└─ clips/
   └─ memo-001-window-15s.mp4
```

정확한 스키마는 구현 시 테스트와 함께 확정한다.

## 6. Baseline

메모 시작 시각을 `t`라고 할 때 각 후보 구간은 다음과 같다.

```text
[max(0, t - window), t]
window ∈ {5, 10, 15, 30}
```

15초는 정답이 아니라 비교 대상 중 하나다. 영상 시작보다 이전으로 계산된 값은 0초로 제한한다.

## 7. 평가

### 구간 IoU

```text
IoU = prediction과 ground truth의 교집합 길이
      / prediction과 ground truth의 합집합 길이
```

### 임시 성공 기준

- 편집 메모 탐지 성공률 90% 이상
- 예측 장면과 Ground Truth IoU 0.5 이상
- 메모를 탐지한 사례의 MP4 생성 성공률 100%

이 기준은 초기 가설이며, 5개 데이터가 준비되기 전에는 일반적인 성능 주장에 사용하지 않는다.

## 8. 구현 순서

1. 현재 로컬의 `eval_01.MOV` 위치와 FFmpeg 실행 가능 여부 확인
2. 업로드 파일 검증과 안전한 로컬 저장 정책 구현
3. 업로드와 분리된 로컬 파일 처리 진입점 마련
4. FFmpeg 오디오 추출과 오류 처리
5. STT 후보를 같은 Test 01로 비교하고 선택 근거 기록
6. 편집 메모와 타임스탬프 탐지
7. 네 개 고정 Window 생성과 IoU 비교
8. 후보 클립 렌더링
9. Test 02~05 촬영 및 동일 평가 반복
10. Failure Analysis 후 Phase 2 기술 결정

## 9. MVP 완료 조건

- Test 01~05가 동일한 명령 또는 API 흐름으로 처리된다.
- 각 테스트에 Transcript, 탐지 결과, 후보 구간, 평가 결과, 실제 클립이 생성된다.
- 실패가 무시되지 않고 단계와 원인으로 기록된다.
- README 상태와 평가 문서가 실제 코드·결과와 일치한다.
- LLM/VLM 없이 Baseline 결과를 재현할 수 있다.
