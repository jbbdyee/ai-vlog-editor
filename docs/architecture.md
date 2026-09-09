# Architecture

## 1. 설계 원칙

- 결정적인 실행과 확률적인 모델 판단을 분리한다.
- 각 단계는 파일 또는 구조화된 데이터로 결과를 남겨 독립적으로 평가할 수 있어야 한다.
- 모델이 선택한 구간도 검증기를 거쳐야 하며 모델이 임의의 FFmpeg 명령을 실행하지 않는다.
- 원본 영상은 로컬 우선으로 처리하고 Git에 저장하지 않는다.
- MVP에서 필요한 단순한 순차 처리는 Agent가 아닌 일반 워크플로우로 구현한다.

## 2. MVP v1 데이터 흐름

```text
Video Asset
   │
   ├─ Media Probe ───────────────→ duration / codec / streams
   │
   └─ Audio Extractor
          ↓
      STT Adapter
          ↓
      Transcript Segments
          ↓
      Memo Detector
          ↓
      Edit Memo
          ↓
      Fixed-window Generator
          ↓
      Candidate Intervals
          ├─ Evaluator ──────────→ IoU / diagnostics
          └─ Clip Renderer ──────→ MP4
```

## 3. 컴포넌트 경계

### API 또는 실행 진입점

입력을 받아 처리 작업을 시작한다. HTTP 업로드는 인터페이스일 뿐 핵심 영상 처리 로직을 포함하지 않는다. 같은 파이프라인을 로컬 파일에서도 호출할 수 있게 분리한다.

현재 업로드 API는 MOV/MP4의 확장자, Content-Type, 공통 컨테이너 헤더를 검증하고 UUID 기반 파일명으로 로컬 `uploads/`에 저장한다. 검증·저장 책임은 `app/services/video_storage.py`에 두며 API 계층은 HTTP 오류 변환만 담당한다.

### Media Probe / Audio Extractor

FFmpeg/ffprobe를 사용해 미디어 정보를 읽고 STT용 오디오를 만든다. 파일명, 코덱, 길이, 스트림 오류를 명시적으로 반환한다.

### STT Adapter

특정 STT 엔진을 나머지 코드에서 격리한다. 최소 출력은 시작·종료 시각과 텍스트를 가진 Segment 목록이다. 엔진은 비교 실험 후 결정한다.

### Memo Detector

MVP에서는 고정 트리거 또는 단순 정규화 규칙을 사용한다. 자유로운 의도 분류는 후속 단계다.

### Candidate Generator

메모 타임스탬프를 기준으로 5·10·15·30초 이전 구간을 생성한다. 영상 경계를 벗어나지 않게 제한한다.

### Evaluator

예측 구간과 Ground Truth의 IoU, 탐지 여부, 렌더링 성공 여부를 계산한다. 모델 선택과 분리되어 재현 가능해야 한다.

### Clip Renderer

검증된 시작·종료 시각을 FFmpeg 작업으로 변환한다. 모델이 직접 명령 문자열을 생성하지 않는다.

## 4. 개념 데이터 모델

```text
VideoAsset
- id
- source_path
- duration_seconds
- media_type

TranscriptSegment
- start_seconds
- end_seconds
- text

EditMemo
- id
- start_seconds
- end_seconds
- transcript_text
- intent_type

CandidateInterval
- memo_id
- strategy
- start_seconds
- end_seconds

EvaluationResult
- candidate_id
- ground_truth_start
- ground_truth_end
- iou
- render_succeeded
```

이는 구현 방향을 위한 최소 개념 모델이며, 영구 저장소 도입을 의미하지 않는다.

## 5. 후속 확장 경계

### Scene Retrieval

침묵, 장면 전환, Transcript 문맥, Embedding 또는 VLM을 이용해 후보를 만들더라도 최종 출력은 동일한 `CandidateInterval` 경계를 사용한다.

### Conversational Editing

LLM은 자연어를 허용된 Edit Operation으로 구조화한다. 대상 장면 검색, 시간 검증, 실제 렌더링은 별도 컴포넌트가 담당한다.

### Narrative Planner

장면 카드 목록에서 선택·순서·역할·권장 길이를 가진 편집 계획을 만든다. 존재하지 않는 장면 ID, 중복, 목표 길이 초과는 결정적인 검증기가 차단한다.

### Short-form Repurposing

기존 편집 타임라인과 원본 장면을 함께 사용한다. VLM/LLM은 의미와 구조를 판단할 수 있지만 Auto Reframe은 컴퓨터 비전, 출력 규격과 렌더링은 플랫폼 프로필과 FFmpeg가 담당한다.

### Agent Workflow

작업 순서를 사전에 결정할 수 없고 실행 결과에 따라 도구와 계획을 반복적으로 바꿔야 하는 사례가 확인되기 전에는 도입하지 않는다.
