# Cutory Tool Layer

## 목적

Agent의 판단을 안전하고 재현 가능한 media operation으로 변환한다.

> Agent = 판단, Tool = 실행

## Domain

1. Media: probe, audio/STT, proxy/frame extraction
2. Scene Analysis: segmentation, signal/evidence, candidate validation
3. Editing: clip, timeline, preview/final render
4. Caption: layout, burn-in, readability validation
5. Audio/BGM: search adapter, mix, ducking, fade
6. Color/Visual: approved preset/application
7. Validation: media integrity, license, resource, plan/render checks

## 입력과 출력

Tool은 `video_id`, `scene_id`, `render_id`, `font_id`, `bgm_id`, `preset_id`와 같은 resource ID와 구조화된 config를 받는다. 출력은 구조화 metadata, 새 resource ID, validation result, warning, safe error이다. raw local path는 capability 경계 밖으로 노출하지 않는다.

## 주요 원칙

- deterministic/idempotent operation을 우선한다.
- 모든 interval, resource ownership, video duration, catalog/license를 실행 전 검증한다.
- shell string 대신 argument list/안전한 wrapper를 사용한다.
- output은 temp file을 완성한 후 atomic publish한다.
- Agent 출력의 숫자/path를 검증 없이 실행하지 않는다.

## 기존 코드 매핑

| Current service | Full Product mapping |
| --- | --- |
| `media_probe` | Media Tool |
| `audio_extractor`, `stt_service` | Media Tool |
| `memo_detector`, `transcript_scene_retriever` | Scene Tool |
| `candidate_generator` | Scene Baseline/Tool |
| `semantic_block_selector` | Scene capability |
| audio/visual boundary refiners | Experimental Scene Evidence |
| scene boundary proposals | Scene Tool |
| Ollama/Gemini VLM selectors | Experimental Scene Agent research |
| `clip_renderer` | Editing/Render Tool |
| `candidate_evaluator` | Evaluation only; product execution 제외 |
| `VideoProcessingPipeline` | Baseline orchestration |

## 실패 처리

Tool error는 domain, stage, retryability, safe message, affected resource ID를 반환한다. Partial output을 final resource로 publish하지 않고 소유한 temporary artifact cleanup을 시도한다. Cleanup failure는 본 실패와 구분한다.

## 하지 않는 일

`arbitrary_ffmpeg`, `arbitrary_shell`, `arbitrary_file_read`를 Agent capability로 제공하지 않고, 편집 의미/스토리를 Tool이 판단하지 않는다.

## 향후 확장

Tool schema/versioning, idempotency key, sandbox/resource quota, execution metrics는 MCP/API 구현에서 구체화한다.

## 현재 구현

`backend/app/tools/`에 MCP와 독립적인 내부 Tool Layer가 구현되어 있다.

- `probe_video`: UUID SourceVideo를 검증된 original로 해석하고 기존 `probe_media()` 결과를 path 없이 반환한다.
- `extract_audio`: 기존 `extract_audio()`가 만든 WAV를 workspace registry에 등록하고 opaque temporary artifact ID와 audio metadata만 반환한다.
- `transcribe_audio`: registry가 ownership/scope를 확인한 WAV와 caller가 미리 로드한 STT model로 기존 `transcribe_audio()`를 호출한다.
- `detect_edit_memos`: 구조화 Transcript DTO를 기존 `detect_edit_memos()`에 매핑하며 memo 0개도 정상 결과다.

공통 `ToolResult`는 `SUCCEEDED` data와 `FAILED` error가 동시에 존재하지 못하게 하고 invocation ID, Tool 이름/version, 시작·종료 시각과 duration을 기록한다. 예상 가능한 오류만 안전한 code/message로 변환하며 traceback, stderr, provider 원문, credential과 로컬 path는 반환하지 않는다. 이 결과는 한 번의 호출 계약이고 Scene WorkItem/Attempt persistence가 아니다.

Temporary artifact 수명과 Tool 간 연결은 application 책임이고 Tool 내부 business retry는 없다. 현재 MCP SDK, MCP Server/Client와 Scene Discovery Tool은 구현하지 않았다.
