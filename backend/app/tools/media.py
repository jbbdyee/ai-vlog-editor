from __future__ import annotations

from dataclasses import dataclass
import subprocess
from typing import Callable
from uuid import UUID, uuid4

from backend.app.services.audio_extractor import (
    AudioExtractionError,
    ExtractedAudio,
    extract_audio as extract_audio_service,
)
from backend.app.services.media_probe import (
    MediaInfo,
    MediaProbeError,
    probe_media as probe_media_service,
)
from backend.app.storage.processing_workspace import (
    LocalProcessingWorkspace,
    ProcessingWorkspaceError,
)
from backend.app.tools.contracts import (
    ToolError,
    ToolErrorCode,
    ToolInvocation,
    ToolResult,
)
from backend.app.tools.resources import (
    InvalidResourceInputError,
    ResourceNotFoundError,
    ResourceOwnershipError,
    ResourceResolutionError,
    ResourceSecurityError,
    ResourceUnreadableError,
    SourceResourceResolver,
    TemporaryArtifactKind,
    TemporaryArtifactRef,
    TemporaryArtifactRegistry,
)


PROBE_VIDEO_TOOL_VERSION = "1.0"
EXTRACT_AUDIO_TOOL_VERSION = "1.0"


@dataclass(frozen=True)
class ProbeVideoInput:
    source_video_id: UUID
    expected_project_id: UUID | None = None


@dataclass(frozen=True)
class ProbeVideoData:
    duration_seconds: float
    has_video_stream: bool
    has_audio_stream: bool
    video_codec: str | None
    audio_codec: str | None
    format_name: str


@dataclass(frozen=True)
class ExtractAudioInput:
    source_video_id: UUID
    expected_project_id: UUID | None = None


@dataclass(frozen=True)
class AudioMetadata:
    duration_seconds: float
    sample_rate_hz: int
    channels: int
    codec: str


@dataclass(frozen=True)
class ExtractAudioData:
    artifact: TemporaryArtifactRef
    audio: AudioMetadata


def probe_video(
    request: ProbeVideoInput,
    *,
    resolver: SourceResourceResolver,
    probe: Callable[..., MediaInfo] = probe_media_service,
) -> ToolResult[ProbeVideoData]:
    invocation = ToolInvocation("probe_video", PROBE_VIDEO_TOOL_VERSION)
    try:
        resolved = resolver.resolve_source(
            request.source_video_id,
            expected_project_id=request.expected_project_id,
        )
    except ResourceResolutionError as exc:
        return invocation.failed(_resource_error(exc, request.source_video_id))
    try:
        media = probe(resolved.path)
    except MediaProbeError as exc:
        return invocation.failed(_execution_error(exc, request.source_video_id, "Media probe failed."))
    return invocation.succeeded(
        ProbeVideoData(
            duration_seconds=media.duration_seconds,
            has_video_stream=media.has_video_stream,
            has_audio_stream=media.has_audio_stream,
            video_codec=media.video_codec,
            audio_codec=media.audio_codec,
            format_name=media.format_name,
        )
    )


def extract_audio(
    request: ExtractAudioInput,
    *,
    resolver: SourceResourceResolver,
    workspace: LocalProcessingWorkspace,
    registry: TemporaryArtifactRegistry,
    extractor: Callable[..., ExtractedAudio] = extract_audio_service,
) -> ToolResult[ExtractAudioData]:
    invocation = ToolInvocation("extract_audio", EXTRACT_AUDIO_TOOL_VERSION)
    try:
        resolved = resolver.resolve_source(
            request.source_video_id,
            expected_project_id=request.expected_project_id,
        )
        output_directory = workspace.audio_directory(
            project_id=resolved.project_id,
            source_video_id=resolved.source_video_id,
        )
    except ResourceResolutionError as exc:
        return invocation.failed(_resource_error(exc, request.source_video_id))
    except ProcessingWorkspaceError:
        return invocation.failed(
            ToolError(
                ToolErrorCode.RESOURCE_UNREADABLE,
                "Temporary audio workspace is unavailable.",
                retryable=True,
                affected_resource_id=request.source_video_id,
            )
        )

    try:
        extracted = extractor(resolved.path, output_directory)
    except AudioExtractionError as exc:
        return invocation.failed(_execution_error(exc, request.source_video_id, "Audio extraction failed."))

    scope_id = uuid4()
    try:
        artifact = registry.register(
            extracted.audio_path,
            project_id=resolved.project_id,
            source_video_id=resolved.source_video_id,
            scope_id=scope_id,
            artifact_kind=TemporaryArtifactKind.AUDIO_WAV,
        )
    except ResourceResolutionError as exc:
        try:
            extracted.audio_path.unlink(missing_ok=True)
        except OSError:
            return invocation.failed(
                ToolError(
                    ToolErrorCode.CLEANUP_FAILED,
                    "Invalid temporary audio could not be cleaned up.",
                    retryable=False,
                    affected_resource_id=request.source_video_id,
                )
            )
        return invocation.failed(_resource_error(exc, request.source_video_id))

    return invocation.succeeded(
        ExtractAudioData(
            artifact=artifact,
            audio=AudioMetadata(
                duration_seconds=extracted.duration_seconds,
                sample_rate_hz=extracted.sample_rate_hz,
                channels=extracted.channels,
                codec=extracted.codec,
            ),
        )
    )


def _resource_error(exc: ResourceResolutionError, resource_id: UUID | None) -> ToolError:
    if isinstance(exc, InvalidResourceInputError):
        return ToolError(ToolErrorCode.INVALID_INPUT, "Resource identifier is invalid.")
    if isinstance(exc, ResourceNotFoundError):
        return ToolError(ToolErrorCode.RESOURCE_NOT_FOUND, "Resource was not found.", affected_resource_id=resource_id)
    if isinstance(exc, (ResourceOwnershipError, ResourceSecurityError)):
        return ToolError(ToolErrorCode.SECURITY_VIOLATION, "Resource access was denied.", affected_resource_id=resource_id)
    if isinstance(exc, ResourceUnreadableError):
        return ToolError(ToolErrorCode.RESOURCE_UNREADABLE, "Resource is unavailable.", retryable=True, affected_resource_id=resource_id)
    raise TypeError("Unsupported resource resolution error.")


def _execution_error(exc: Exception, resource_id: UUID, message: str) -> ToolError:
    timed_out = isinstance(exc.__cause__, subprocess.TimeoutExpired)
    return ToolError(
        ToolErrorCode.TIMEOUT if timed_out else ToolErrorCode.EXECUTION_FAILED,
        "Tool execution timed out." if timed_out else message,
        retryable=timed_out,
        affected_resource_id=resource_id,
    )
