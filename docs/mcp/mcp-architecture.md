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

## 현재 구현

`backend/app/mcp/`에 공식 MCP Python SDK 2.2.0 기반의 최소 Video Editing MCP Server가 구현되어 있다. 실행 entrypoint는 `python -m backend.app.mcp.server`이고 transport는 stdio다. Server process는 PostgreSQL session factory와 `LocalSourceStorage`만 구성하며 현재 공개 capability는 `probe_video` 하나다.

```text
MCP Client
→ stdio protocol/schema validation
→ probe_video MCP adapter
→ Internal probe_video Tool
→ ResourceResolver
→ existing probe_media / ffprobe
```

입력은 필수 `source_video_id: UUID`와 선택적 Project scope assertion인 `project_id: UUID | null`만 받는다. 성공 응답은 allowlist media metadata와 Tool execution metadata를, expected failure는 safe code/message와 retryability를 반환한다. raw path, storage reference, stderr, ORM object와 credential은 반환하지 않는다. Programmer error는 expected Tool failure로 변환하지 않고 MCP internal error로 sanitization한다.

현재 MCP Resources와 Prompts는 없으며 `extract_audio`, `transcribe_audio`, `detect_edit_memos`도 공개하지 않는다. MCP Server는 retry, Scene selection, WorkItem/Attempt transaction이나 workflow orchestration을 담당하지 않는다. Streamable HTTP, SSE, auth와 remote deployment도 구현하지 않았다.
