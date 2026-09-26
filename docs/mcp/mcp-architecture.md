# Video Editing MCP Architecture

## 목적

Agent와 실제 영상 처리 Capability 사이의 표준 계약을 제공한다.

## 역할 구분

- FastAPI: User/Frontend ↔ Product
- MCP: Agent ↔ Capability
- LangGraph: Agent workflow orchestration

이 세 경계를 섞지 않는다.

## 구성

초기 Full Design은 하나의 Video Editing MCP Server 안에 Media, Scene Analysis, Editing, Caption, Audio, Color, Validation domain을 둔다. 구현 복잡도와 독립 배포 필요가 검증되기 전에 domain별 server로 과도하게 분리하지 않는다.

## 노출 Capability 예

- `probe_video`
- `transcribe_video`
- `extract_frames`
- `analyze_video_segment`
- `render_preview`
- `render_final`
- `search_bgm`
- `validate_render`

모든 내부 Python 함수를 MCP Tool로 노출하지 않고 Agent가 독립적으로 호출할 가치가 있는 capability만 노출한다.

## 입력/출력 계약

Input은 resource ID, validated enum/config, bounded interval, request/idempotency ID를 사용한다. Output은 resource ID, metadata, status, warnings, safe error, execution reference를 사용한다. raw filesystem path, arbitrary command, secret를 Agent에게 주지 않는다.

## 주요 흐름

Agent가 MCP Client로 capability를 요청하면 Server가 schema, ownership, permission, range, resource/license를 검증한 뒤 기존 Python service/FFmpeg/STT를 호출한다. 산출물은 storage에 publish하고 resource ID로 반환한다.

## 보안/개인정보

각 Agent에게 필요한 capability와 resource scope만 제공한다. External Provider가 필요한 Tool은 전송 범위를 metadata로 기록하고 원본 MOV/WAV 전송을 기본적으로 금지한다.

## 실패 처리

Transport error, validation error, capability failure, timeout, resource missing을 구분한다. MCP Server는 Orchestrator retry policy를 대신 결정하지 않고 retryability hint와 safe failure만 반환한다.

## 하지 않는 일

- arbitrary shell/FFmpeg/file read 노출
- 모든 세부 함수의 1:1 Tool화
- MCP를 user-facing REST API나 workflow engine으로 사용

## 향후 확장

정확한 MCP schema, auth, deployment boundary, streaming/progress, capability version negotiation은 구현 단계에서 결정한다.
