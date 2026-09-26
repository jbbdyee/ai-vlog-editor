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
