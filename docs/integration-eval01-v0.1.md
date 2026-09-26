# VideoProcessingPipeline eval_01 Integration Verification v0.1

## 1. 검증 목적

이 문서는 `VideoProcessingPipeline.process()` 단일 호출이 실제 `eval_01.MOV`를 입력받아 미디어 검사부터 MP4 생성과 중간 파일 정리까지 완료할 수 있는지 확인한 End-to-End integration verification 기록이다.

성능 평가 문서가 아니며 Ground Truth, IoU, Oracle을 사용하지 않았다. 선택한 5초 Window도 가장 좋은 후보를 자동 판단한 결과가 아니라 호출자가 통합 검증 조건으로 명시한 deterministic 선택값이다.

## 2. 실제 Pipeline 흐름

```text
evaluation/data/eval_01.MOV
→ Media Probe
→ WAV Audio Extraction
→ faster-whisper STT with word timestamps
→ EditMemo Detection
→ 5/10/15/30초 Candidate Generation
→ FixedWindowSceneSelector(window_seconds=5.0)
→ FFmpeg Clip Renderer
→ Rendered MP4
→ Intermediate WAV Cleanup
```

`VideoProcessingPipeline.process()`는 정확히 한 번 실행했으며 자동 재시도나 selector fallback은 사용하지 않았다.

## 3. 실행 환경과 조건

| 항목 | 값 |
| --- | --- |
| Source | `evaluation/data/eval_01.MOV` |
| Output root | `outputs/e2e` |
| Selector | `FixedWindowSceneSelector(window_seconds=5.0)` |
| STT | 기존 `load_model()` 및 faster-whisper 기본 설정 |
| Word timestamps | `True` |
| Intermediate audio 보존 | `False` |
| Pipeline status | `COMPLETED` |
| Pipeline total | 약 13.2224초 |

Gemini, Ollama, Evaluator는 호출하지 않았다.

## 4. Source Media

| 항목 | 결과 |
| --- | --- |
| Duration | 20.95초 |
| Video stream | 있음 |
| Audio stream | 있음 |
| Video codec | HEVC |
| Audio codec | AAC |
| Format | `mov,mp4,m4a,3gp,3g2,mj2` |

Source 파일은 실행 전후 모두 존재했고 파일 크기도 `143,712,075 bytes`로 동일했다.

## 5. STT 결과

| 항목 | 결과 |
| --- | --- |
| Language | `ko` |
| Language probability | 1.0 |
| Segment 수 | 5 |
| Word timestamp 수 | 21 |

Transcript:

> 안녕하세요. 저는 김사과입니다. 지금은 간단한 동영상 테스트를 해보고 있습니다. 제가 물건을 하나 떨어뜨려 볼게요. 아 뭐야. 에이아이아 지금 장면 꼭 살려줘.

## 6. EditMemo 결과

탐지된 EditMemo는 1개다.

| 필드 | 결과 |
| --- | --- |
| Start | 15.8초 |
| End | 18.72초 |
| Transcript | `에이아이아 지금 장면 꼭 살려줘.` |
| Matched trigger | `에이아이아` |
| Matched reference | `지금` |
| Matched action | `살려줘` |
| Trigger match type | `similarity` |
| Trigger similarity | 0.8 |

## 7. 생성 Candidate

| Window | Start | End |
| ---: | ---: | ---: |
| 5초 | 10.8 | 15.8 |
| 10초 | 5.8 | 15.8 |
| 15초 | 0.8 | 15.8 |
| 30초 | 0.0 | 15.8 |

## 8. FixedWindow 선택 결과

| 필드 | 결과 |
| --- | --- |
| Strategy | `fixed_window` |
| Selected source | `window:5.0` |
| Reasoning code | `FIXED_WINDOW_SELECTED` |
| Selected interval | 10.8~15.8초 |

선택된 객체는 Pipeline이 생성한 5초 `SceneCandidate`와 동일 객체이자 동일 구간이었다. 이 결과는 후보 품질 비교나 자동 최적화 결과가 아니다.

## 9. Rendered MP4

| 항목 | 결과 |
| --- | --- |
| Start | 10.8초 |
| End | 15.8초 |
| Duration | 5.0초 |
| Video codec | H.264 |
| Audio codec | AAC |
| File size | 7,078,377 bytes, 약 7.08 MB |

실행 당시 파일은 UUID run directory 아래 UUID 기반 MP4 이름으로 생성됐다. Runtime output은 Git에서 제외한다.

## 10. ffprobe 재검증

생성된 MP4를 Pipeline 완료 후 다시 `ffprobe`로 검사했다.

| 항목 | 결과 |
| --- | --- |
| Format | `mov,mp4,m4a,3gp,3g2,mj2` |
| Duration | 5.0초 |
| Video stream | 있음 |
| Audio stream | 있음 |
| Video codec | H.264 |
| Audio codec | AAC |

재검증 결과는 `RenderedClip`의 duration 및 codec 정보와 일치했다.

## 11. File Lifecycle

```text
outputs/e2e/<run-uuid>/
├─ audio/       # Pipeline 종료 후 비어 있음
└─ clips/
   └─ <clip-uuid>.mp4
```

- Source MOV 보존
- STT 입력용 WAV 실제 생성 및 사용
- `keep_intermediate_audio=False`에 따라 WAV 삭제
- 최종 `result.extracted_audio=None`
- 완성 MP4 보존
- Cleanup warning 없음

## 12. Stage Timing

| Stage | 시간 |
| --- | ---: |
| `output_preparation` | 약 0.0001초 |
| `media_probe` | 약 0.3312초 |
| `audio_extraction` | 약 0.0810초 |
| `stt` | 약 2.2101초 |
| `memo_detection` | 약 0.0001초 |
| `candidate_generation` | 약 0.00002초 |
| `candidate_selection` | 약 0.00001초 |
| `clip_rendering` | 약 10.5996초 |
| `total` | 약 13.2224초 |

모델 로드는 Pipeline 호출 전에 약 0.657초가 걸렸으며 위 Pipeline total에는 포함되지 않는다.

## 13. 현재 병목

이번 한 번의 실행에서 가장 오래 걸린 단계는 약 10.5996초의 `clip_rendering`이었다. 이는 관찰 결과일 뿐 이번 검증에서는 codec, preset, FFmpeg 명령이나 Pipeline을 최적화하지 않았다.

## 14. 이번 검증에서 확인한 것

- 실제 MOV를 `VideoProcessingPipeline.process()` 한 번으로 끝까지 처리할 수 있다.
- 실제 ffprobe, FFmpeg, faster-whisper와 기존 memo/candidate/selector 서비스가 application service 경계에서 연결된다.
- word timestamp 기반 EditMemo 시각이 Pipeline 결과에 반영된다.
- 명시된 fixed Window 후보가 수정 없이 renderer로 전달된다.
- 생성 MP4는 video/audio stream을 가진 H.264/AAC 파일이다.
- Source와 완성 clip은 보존하고 중간 WAV는 정리한다.
- 실패를 숨기는 Provider 또는 selector fallback 없이 기본 MVP backend 흐름이 완료된다.

## 15. 이번 검증에서 확인하지 않은 것

- 어떤 Candidate가 사용자 의도에 가장 가까운지
- Ground Truth 대비 IoU, Coverage, Boundary Error
- 5초 Window가 다른 Window보다 좋은지
- 여러 EditMemo가 있는 실제 영상의 통합 동작
- API 동시 요청, timeout, 취소 및 서버 재시작 동작
- FastAPI 또는 Frontend에서의 파일 전달
- Gemini, Ollama, semantic/VLM selector
- FFmpeg 렌더링 성능 최적화
- 운영 환경의 저장 공간 관리와 장기 보존 정책
