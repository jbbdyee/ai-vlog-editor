# MVP v1 Specification

## 1. 검증 질문

> 촬영 중 남긴 음성 편집 메모를 이용해 사용자가 의도한 장면을 찾고 실제 영상 파일로 추출할 수 있는가?

MVP v1은 전체 편집 서비스를 만드는 단계가 아니라 이 질문을 End-to-End로 검증하는 단계다.

## 2. 저장소에서 확인된 현재 상태

2026-09-24 현재 저장소에서 직접 확인된 상태는 다음과 같다.

- FastAPI 애플리케이션 구성
- `GET /health` 구현
- `POST /videos/upload` MOV/MP4 검증 및 안전한 로컬 저장 구현
- 로컬 파일을 대상으로 한 ffprobe 기본 미디어 정보 조회 구현
- FFmpeg 기반 16 kHz mono PCM WAV 오디오 추출 서비스 구현
- faster-whisper `small` 기반 한국어 STT Baseline 구현 — 실제 `eval_01.wav`에서 word timestamp 통합 검증 완료
- trigger 음가 정규화·제한적 유사도와 reference/action 표현군을 이용한 규칙 기반 편집 메모 탐지 구현 — Test 02 `AIA`, Test 05 `에이야 에야` 재검증 성공
- EditMemo 시작 시점 기반 5·10·15·30초 고정 구간 Scene Candidate 생성 구현
- 2.0초 초과 침묵으로 발화 block을 분리하고 가장 최근 block을 선택하는 deterministic Transcript Scene Retrieval Baseline 구현
- 의미 기반 Transcript Block 선택을 위한 Provider 독립적 입력·출력 Schema와 deterministic Candidate 검증 계층 구현
- OpenAI `gpt-6-luna` Responses API와 Structured Outputs 기반 Semantic Block Selector Spike Adapter 구현 — API key 미설정으로 실제 eval_01~05 평가는 미실행
- Gemini `gemini-3.5-flash`와 `google-genai` Structured Outputs 기반 Semantic Block Selector Spike Adapter 구현 — API key 미설정으로 실제 eval_01~05 평가는 미실행
- 선택된 TranscriptBlock 주변의 로컬 WAV RMS activity로 구간을 보정하는 deterministic Audio Boundary Refiner v0.1 구현 및 eval_01~05 평가 완료 — 일부 짧은 reaction 구간은 소폭 개선했으나 긴 발화를 여러 episode로 분절해 전체 성공 기준은 미달
- 선택된 TranscriptBlock 주변의 로컬 grayscale frame 차이로 구간을 보정하는 deterministic Visual Motion Refiner v0.1 구현 및 eval_01~05 평가 완료 — refinement yield 2/5이며 생성된 두 Candidate 모두 Raw보다 악화되어 전체 성공 기준 미달
- deterministic boundary proposal 3~6개와 대표 프레임을 로컬 Ollama `qwen3-vl:4b`에 전달해 proposal ID만 선택받는 Local VLM Proposal Selector v0.1 구현 — mock 테스트 완료, 16,384 context로 context 오류는 해소했으나 synthetic Smoke Test는 9장 이미지 처리 중 120초 timeout으로 실패했으며 eval_01~05는 미실행
- Local VLM Smoke Test 결과를 API 응답 직후 JSONL에 flush/fsync하고 같은 run ID의 중복 호출을 사전에 차단하는 영속 저장 계층 구현 — 실제 Ollama 재호출 없이 mock 검증 완료
- Local VLM Proposal Selector v0.1 eval_01~05 terminal result 기록 완료 — 4건 proposal 준비 실패, 1건 Provider 실패로 실제 선택 성능은 측정하지 못했으며 실패 원인과 Proposal Oracle을 별도 평가 문서에 기록
- Local VLM Proposal Pipeline v0.1.1 완료 — 마지막 selected block의 search end를 memo start로 처리하고 안전한 Provider 오류 메타데이터를 보존; eval_01~05 proposal preparation 5/5 성공 후 3건 timeout·2건 context 초과 기록
- Local VLM Proposal image representation v0.2 구현·평가 — 기존 10/50/90% frame을 proposal별 수평 contact sheet 한 장으로 결합하며 synthetic Smoke는 3,660 input tokens·39.3534초로 성공; eval_01~05 context 초과는 해소됐지만 5/5가 120초 timeout으로 종료
- Gemini Vision Contact Sheet feasibility adapter 구현 — 동일 synthetic contact sheet 3장으로 독립 Smoke 2회를 실행했으나 모두 Provider HTTP 503 `UNAVAILABLE`로 Structured Output 전에 종료, run별 재호출과 eval_01~05는 미실행
- Scene Candidate와 Ground Truth의 IoU·Coverage·구간 경계 오차 Evaluator 구현
- FFmpeg H.264/AAC 재인코딩 기반 Scene Candidate MP4 Clip Renderer 구현 및 실제 Test 01의 5초 Candidate 검증
- 명시적으로 주입된 `SceneSelector`를 사용하는 MVP End-to-End application service 구현 — Media Probe, 오디오 추출, word timestamp STT, 메모 탐지, 고정 Window 후보 생성, 선택 및 MP4 렌더링을 연결하고 여러 메모·중간 WAV 정리·단계 timing을 구조화된 결과로 반환
- `POST /videos/process` multipart API 구현 — 5·10·15·30초 중 필수 Window를 명시하고 lifespan에서 한 번 로드한 faster-whisper 모델을 재사용하며, semaphore로 단일 동시 실행을 제한한 Pipeline을 threadpool에서 호출
- `GET /videos/clips/{run_id}/{clip_id}` 구현 — 엄격한 UUID hex 검증과 resolve 기반 traversal·symlink escape 방어 후 API 출력 루트 아래 MP4만 제공
- Streamlit MVP 구현 — HTTP API만 사용해 MOV/MP4 업로드, 5·10·15·30초 수동 Window 선택, Transcript·EditMemo·Candidate·생성 MP4 표시
- Evaluation Dataset v0.1 시나리오 문서
- `evaluation/data/.gitkeep`

현재 업로드 엔드포인트는 확장자, Content-Type, 컨테이너 헤더를 검증하고 원본 파일명 대신 UUID 기반 파일명으로 `uploads/`에 저장한다. 업로드와 분리된 미디어 조회 서비스는 ffprobe JSON 결과에서 길이, 컨테이너, 영상·음성 스트림 및 코덱을 읽는다.

사용자 실행 Pipeline은 Ground Truth나 Evaluator를 호출하지 않는다. 고정 Window selector도 기본 Window를 자동 선택하지 않으며 호출자가 `window_seconds`를 반드시 지정한다. 실제 `eval_01.MOV` End-to-End 통합 실행 결과는 `docs/integration-eval01-v0.1.md`에 기록했다.

처리 API는 Pipeline 결과를 로컬 경로 없는 Pydantic DTO로 변환하고, 렌더링 결과에 clip 다운로드 endpoint를 가리키는 상대 URL을 포함한다. Streamlit은 이 API 응답과 MP4 bytes만 사용하며 backend service나 로컬 파일 경로를 직접 참조하지 않는다. 현재 Window는 사용자가 직접 선택하며 AI 기반 최적 Window 선택과 실시간 progress는 구현하지 않았다.

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

Evaluator는 Ground Truth 길이 중 후보가 포함한 비율인 Coverage와 후보·정답의 시작 및 종료 시각 절대 오차도 함께 계산한다. 이 단계에서는 지표를 이용해 후보를 선택하거나 순위화하지 않는다.

### 임시 성공 기준

- 편집 메모 탐지 성공률 90% 이상
- 예측 장면과 Ground Truth IoU 0.5 이상
- 메모를 탐지한 사례의 MP4 생성 성공률 100%

이 기준은 초기 가설이며, 5개 데이터가 준비되기 전에는 일반적인 성능 주장에 사용하지 않는다.

## 8. 구현 순서

1. 현재 로컬의 `eval_01.MOV` 위치와 FFmpeg 실행 가능 여부 확인
2. 업로드 파일 검증과 안전한 로컬 저장 정책 구현 — 완료
3. 업로드와 분리된 로컬 파일 ffprobe 조회 서비스 구현 — 완료
4. FFmpeg 오디오 추출과 오류 처리 — 완료
5. faster-whisper `small` 기반 첫 STT Baseline 구현 — 완료
6. 편집 메모와 타임스탬프 탐지 — 완료
7. 네 개 고정 Window 생성과 Ground Truth 대비 지표 계산 — 완료
8. 후보 클립 렌더링 — 완료
9. Test 02~05 촬영 및 동일 평가 반복
10. Failure Analysis 후 Phase 2 기술 결정

## 9. MVP 완료 조건

- Test 01~05가 동일한 명령 또는 API 흐름으로 처리된다.
- 각 테스트에 Transcript, 탐지 결과, 후보 구간, 평가 결과, 실제 클립이 생성된다.
- 실패가 무시되지 않고 단계와 원인으로 기록된다.
- README 상태와 평가 문서가 실제 코드·결과와 일치한다.
- LLM/VLM 없이 Baseline 결과를 재현할 수 있다.
