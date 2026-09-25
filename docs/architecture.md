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
          ├─ Fixed-window Generator ────┐
          └─ Transcript-block Retriever ┤
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

현재 `app/services/media_probe.py`는 로컬 파일을 ffprobe의 JSON 출력으로 검사하고 길이, 컨테이너, 영상·음성 스트림 및 코덱 정보를 `MediaInfo`로 반환한다. subprocess는 shell 없이 인자 리스트로 실행하며, 파일 부재·실행 실패·파싱 실패는 `MediaProbeError`로 통일한다.

`app/services/audio_extractor.py`는 `MediaInfo`로 오디오 스트림을 먼저 확인한 뒤 첫 오디오 스트림을 16 kHz, mono, signed 16-bit PCM WAV로 변환한다. UUID 기반 경로를 원자적으로 선점해 기존 파일과 충돌하지 않게 하고, FFmpeg는 서비스가 선점한 파일에만 출력한다. 실패하거나 빈 결과가 생성되면 해당 출력 파일을 제거한다. 결과는 소스·오디오 경로, 소스 길이, WAV 설정을 가진 `ExtractedAudio`로 반환한다.

### STT Adapter

특정 STT 엔진을 나머지 코드에서 격리한다. 최소 출력은 시작·종료 시각과 텍스트를 가진 Segment 목록이다.

현재 `app/services/stt_service.py`는 faster-whisper `small` 모델을 CPU `int8`로 로드하고 한국어 WAV를 처리한다. 결과는 전체 텍스트, 언어 정보, segment 타임스탬프와 선택적인 word 타임스탬프를 가진 `STTResult`로 반환하며, 파일·모델 로딩·추론 오류는 `STTError`로 통일한다.

### Memo Detector

MVP에서는 결정적인 정규화와 제한적 문자열 유사도를 사용한다. `app/services/memo_detector.py`는 reference 바로 앞의 최대 2개 토큰만 trigger 후보로 보고 영문 `A/I`를 한글 음가로 정규화한 뒤 표준 호출어와 비교한다. 후보 길이 5~7자와 유사도 0.60 이상을 요구해 실제 STT 변형인 `AIA`, `에이야 에야`를 처리하면서 짧거나 무관한 표현을 제한한다. 기존과 동일하게 호출, 시간 참조(`방금`, `지금`), 행동(`살려줘`)이 순서대로 모두 있는 경우에만 `EditMemo`를 하나 생성한다. 결과에는 실제 일치 표현, match 방식과 유사도를 남기고, word timestamp에서 호출 표현을 찾으면 해당 첫 word의 시작 시각을 사용한다.

### Candidate Generator

`app/services/candidate_generator.py`는 `EditMemo.start_seconds`를 끝 시각으로 사용해 5·10·15·30초 이전의 `SceneCandidate`를 입력 순서대로 생성한다. 시작 시각은 `max(0.0, memo_start - window)`로 계산해 영상 시작보다 이전으로 내려가지 않게 한다. 이 단계는 후보를 생성할 뿐 평가하거나 선택하지 않는다.

### Transcript-block Retriever

`app/services/transcript_scene_retriever.py`는 EditMemo 이전에 완전히 끝난 TranscriptSegment만 사용하고, 인접 segment 사이 침묵이 2.0초를 초과하면 새 utterance block을 만든다. 의미 분석 없이 가장 최근 block 하나를 선택하며 block의 시작·종료 timestamp를 그대로 `SceneCandidate`로 변환한다. 입력 순서, 유효한 시간 범위와 영상 duration을 결정적으로 검증하고 검색할 이전 발화가 없으면 자동 fallback 없이 실패한다. Fixed-window Generator는 비교 Baseline으로 그대로 유지한다.

`app/services/semantic_block_selector.py`는 deterministic selector와 LLM selector가 공유할 최소 계약을 제공한다. selector 입력은 EditMemo와 선택 가능한 TranscriptBlock뿐이며 Ground Truth를 포함하지 않는다. selector 출력은 선택한 block ID, 제한된 reasoning code와 240자 이하의 짧은 summary만 가진다. Provider 출력은 신뢰하지 않고 일반 Python validator가 block 존재 여부, 메모 이전 여부, timestamp와 영상 범위를 검증한 뒤 입력 block의 기존 start/end로 `SceneCandidate`를 만든다. selector가 timestamp를 생성하거나 FFmpeg를 호출할 수 있는 필드는 제공하지 않는다.

`app/services/openai_semantic_block_selector.py`는 위 계약을 구현하는 OpenAI Spike Adapter다. `gpt-6-luna`와 Responses API Structured Outputs를 사용하고, 외부 전송 데이터는 편집 메모 transcript와 block별 ID·시작·종료·transcript로 제한한다. 응답 저장은 끄고 reasoning effort는 `low`로 고정하며 temperature는 보내지 않는다. Provider는 ID와 제한된 근거만 반환하고 timestamp와 Candidate는 기존 deterministic validator가 만든다. Provider 호출·timeout·refusal·구조화 응답 오류는 Provider 전용 오류로, block 검증 오류는 기존 validation 오류로 구분한다. 실제 eval_01~05 API 평가는 `OPENAI_API_KEY`가 제공된 뒤 별도로 기록한다.

`app/services/gemini_semantic_block_selector.py`는 같은 계약을 구현하는 Gemini Spike Adapter다. stable GA `gemini-3.5-flash`와 `google-genai` Structured Outputs를 사용하며 외부 전송 필드와 결정적 검증 경계는 OpenAI Adapter와 동일하다. 응답 무작위성을 낮추기 위해 temperature `0.0`, 단순 선택 작업에 맞춰 thinking level `minimal`을 사용한다. 실제 eval_01~05 API 평가는 `GEMINI_API_KEY`가 제공된 뒤 동일 prompt/settings로 별도 기록한다.

### Evaluator

`app/services/candidate_evaluator.py`는 `SceneCandidate`와 `GroundTruthSegment`의 IoU, Ground Truth Coverage, 시작·종료·전체 경계 오차를 계산한다. 유효한 양의 길이 구간만 평가하며 후보를 선택하거나 순위화하지 않는다.

### Audio Boundary Refiner

`app/services/audio_boundary_refiner.py`는 선택이 끝난 `TranscriptBlock` 주변의 16 kHz mono PCM16 WAV를 20 ms frame으로 분석하는 deterministic Spike다. 인접 block과 memo 시점으로 제한한 로컬 범위에서 RMS/dBFS, 낮은 에너지 절반의 median noise floor, 공통 energy margin으로 activity episode를 만들고 선택 block과 가장 많이 겹치는 episode의 경계를 `SceneCandidate`로 변환한다. Ground Truth는 입력에 포함하지 않으며 activity 근거가 없을 때 Fixed Window로 fallback하지 않는다. v0.1 평가는 `evaluation/results/audio-boundary-v0.1.md`에 기록한다.

### Visual Motion Boundary Refiner

`app/services/visual_motion_refiner.py`는 선택된 `TranscriptBlock` 주변의 로컬 MOV/MP4를 FFmpeg로 5 FPS, 폭 160, 종횡비 유지 grayscale PGM frame stream으로 변환하고 인접 frame의 정규화된 평균 절대 pixel 차이를 계산한다. 3-frame median smoothing 후 `median + 3 × median_absolute_deviation` threshold를 사용하며 0.4초 미만 spike를 제거하고 0.6초 이하 quiet gap을 병합한다. 선택 block과 연결되는 episode가 정확히 하나일 때만 `SceneCandidate`를 만들고, 없거나 여러 개면 `NO_SIGNAL` 또는 `AMBIGUOUS_SIGNAL`로 보존한다. Ground Truth, 자동 fallback, 외부 API는 사용하지 않는다. v0.1 평가는 `evaluation/results/visual-motion-v0.1.md`에 기록한다.

### Local VLM Proposal Selector Spike

`app/services/scene_boundary_proposals.py`는 선택된 block, transcript 경계, 고정 2초 padding과 기존 audio/visual signal을 이용해 최대 6개의 설명 가능한 구간을 결정적으로 만든다. 같은 구간은 제거하고 각 proposal의 10%·50%·90% 지점에서 긴 변 512px JPEG를 FFmpeg로 로컬 추출한다.

`app/services/ollama_vlm_proposal_selector.py`는 호스트의 `localhost:11434` Ollama `qwen3-vl:4b`에 편집 메모, 선택 block 텍스트, 중립 proposal ID·시간과 대표 프레임만 전달한다. JSON Schema structured output은 proposal ID 또는 명시적인 abstain만 허용한다. 일반 Python validator가 ID, 기존 timestamp, 영상·memo 범위, source block과 frame manifest를 다시 검증하고 저장된 proposal 구간만 `SceneCandidate`로 변환한다. Ground Truth, 평가 지표, proposal 종류, 원본 MOV/WAV는 모델에 전달하지 않는다. synthetic Smoke Test에는 16,384 context를 사용해 기존 context 오류를 해소했지만 9장 이미지 처리가 120초 timeout을 초과해 structured output 전 단계에서 실패했으며 eval_01~05는 아직 실행하지 않았다.

`app/services/vlm_smoke_runner.py`는 Smoke Test의 `run_id`가 이미 저장됐는지 Provider 호출 전에 확인하고, 성공·abstain·validator 실패·Provider 실패를 즉시 `evaluation/tmp/local-vlm-smoke.jsonl`에 기록한다. 저장은 기존 `evaluation_result_store.py`의 JSONL 복구, 중복 보호, `flush`와 `fsync` 경로를 재사용하며 이미지 bytes/base64와 전체 prompt는 저장하지 않는다.

Local VLM eval_01~05는 같은 방식으로 `evaluation/tmp/local-vlm-proposal-run.jsonl`에 Test별 terminal result와 사후 Proposal Oracle을 저장한다. v0.1 Run에서는 네 Test가 마지막 selected block의 local search 검증에서 proposal 생성에 실패했고, proposal이 생성된 Test 02도 Provider 단계에서 실패해 실제 VLM 선택 성능은 측정하지 못했다. 상세 결과는 `evaluation/results/local-vlm-proposal-v0.1.md`에 기록한다.

v0.1.1에서는 마지막 selected block에 `next_block_start_seconds`가 없을 때 local search 종료값이 block end로 축소되던 boundary bug를 수정해 memo start를 종료 경계로 사용한다. block과 search 경계가 같은 유효 구간도 허용한다. Ollama 실패는 원문 응답이나 이미지·prompt를 저장하지 않고 HTTP status, 안전한 provider code/message, failure stage, model, image count, `num_ctx`, timeout 여부만 JSONL terminal result에 보존한다. eval_01~05 재평가에서 proposal preparation은 5/5 성공했지만 12장 입력 3건은 timeout, 18장 입력 2건은 context 초과로 Structured Output 전에 실패했다.

v0.2 image representation은 proposal별 기존 10%·50%·90% JPEG와 frame ID/timestamp manifest를 바꾸지 않고, FFmpeg `hstack`으로 왼쪽부터 early·middle·late 순서의 수평 contact sheet 한 장을 만든다. `ProposalContactSheet` validator가 proposal ID, 정확히 세 frame의 순서와 timestamp, non-empty JPEG를 검사한다. VLM은 proposal당 세 이미지 대신 contact sheet 한 장을 받지만 선택 Schema와 저장된 proposal timestamp 기반 `SceneCandidate` 변환은 동일하다. Synthetic Smoke Test에서는 3 proposals의 논리 frame 9개를 실제 이미지 3장으로 전달해 input 3,660 tokens, latency 39.3534초로 Structured Output과 validator에 성공했다. eval_01~05에서는 context 초과 없이 proposal preparation 5/5에 성공했지만 실제 이미지 4~6장 요청이 모두 120초 timeout으로 종료됐다.

`app/services/gemini_vlm_proposal_selector.py`는 동일한 contact sheet input, selection prompt 의미, `VLMProposalSelection` Schema와 deterministic validator를 Gemini `gemini-3.5-flash`에 연결하는 feasibility adapter다. `response_mime_type="application/json"`과 `response_json_schema`를 사용하고 synthetic 이미지와 텍스트만 외부 전송한다. 독립된 synthetic Smoke 2회가 모두 HTTP 503 `UNAVAILABLE`로 Structured Output 전에 종료됐으며 각 run을 재호출하지 않아 latency·token·선택 품질 feasibility는 아직 확인되지 않았다.

### Clip Renderer

`app/services/clip_renderer.py`는 검증된 `SceneCandidate` 하나의 시작·종료 시각을 FFmpeg 인자 목록으로 변환한다. 키프레임에 제한되는 stream copy 대신 시간 경계 정확성과 일반적인 MP4 재생 호환성을 위해 H.264 `yuv420p` video와 AAC audio로 재인코딩한다. UUID 기반 출력 경로를 선점하고 실패·빈 출력·ffprobe 검증 실패 시 파일을 제거한다. 모델이 직접 명령 문자열을 생성하지 않는다.

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
- start_seconds
- end_seconds
- transcript_text
- matched_trigger
- matched_reference
- matched_action
- trigger_match_type
- trigger_similarity

SceneCandidate
- window_seconds
- start_seconds
- end_seconds

TranscriptBlock
- block_id
- start_seconds
- end_seconds
- segment_ids
- transcript_text

TranscriptRetrievalResult
- blocks
- selected_block
- candidate

SemanticBlockSelectionInput
- memo
- blocks

SemanticBlockSelection
- selected_block_id
- reasoning_code
- reasoning_summary

ValidatedSemanticBlockSelection
- selection
- selected_block
- candidate

AudioActivityInterval
- start_seconds
- end_seconds
- peak_dbfs
- mean_dbfs
- overlaps_selected_block

RefinedSceneCandidate
- source_block_id
- original_start_seconds / original_end_seconds
- start_seconds / end_seconds / duration_seconds
- start_adjustment_seconds / end_adjustment_seconds
- start_evidence / end_evidence
- refinement_method / config_version

VisualBoundarySignal
- timestamp_seconds / score / signal_type

VisualActivityInterval
- start_seconds / end_seconds
- peak_score / mean_score
- overlaps_selected_block

VisualBoundaryRefinementResult
- status / source_block_id
- search_start_seconds / search_end_seconds
- original_start_seconds / original_end_seconds
- refined_start_seconds / refined_end_seconds
- motion score statistics / visual signals / activity intervals
- selected_interval / failure_reason
- refinement_method / config_version

GroundTruthSegment
- start_seconds
- end_seconds

CandidateEvaluation
- window_seconds
- iou
- coverage
- start_boundary_error
- end_boundary_error
- total_boundary_error

RenderedClip
- source_path
- clip_path
- start_seconds
- end_seconds
- duration_seconds
- video_codec
- audio_codec
```

이는 구현 방향을 위한 최소 개념 모델이며, 영구 저장소 도입을 의미하지 않는다.

## 5. 후속 확장 경계

### Scene Retrieval

침묵, 장면 전환, Transcript 문맥, Embedding 또는 VLM을 이용해 후보를 만들더라도 최종 출력은 동일한 `SceneCandidate` 경계를 사용한다.

### Conversational Editing

LLM은 자연어를 허용된 Edit Operation으로 구조화한다. 대상 장면 검색, 시간 검증, 실제 렌더링은 별도 컴포넌트가 담당한다.

### Narrative Planner

장면 카드 목록에서 선택·순서·역할·권장 길이를 가진 편집 계획을 만든다. 존재하지 않는 장면 ID, 중복, 목표 길이 초과는 결정적인 검증기가 차단한다.

### Short-form Repurposing

기존 편집 타임라인과 원본 장면을 함께 사용한다. VLM/LLM은 의미와 구조를 판단할 수 있지만 Auto Reframe은 컴퓨터 비전, 출력 규격과 렌더링은 플랫폼 프로필과 FFmpeg가 담당한다.

### Agent Workflow

작업 순서를 사전에 결정할 수 없고 실행 결과에 따라 도구와 계획을 반복적으로 바꿔야 하는 사례가 확인되기 전에는 도입하지 않는다.
