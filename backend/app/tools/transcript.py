from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable
from uuid import UUID

from backend.app.services.memo_detector import (
    EditMemo,
    MemoDetectionError,
    detect_edit_memos as detect_edit_memos_service,
)
from backend.app.services.stt_service import (
    STTError,
    STTResult,
    TranscriptSegment,
    TranscriptWord,
    transcribe_audio as transcribe_audio_service,
)
from backend.app.tools.contracts import ToolError, ToolErrorCode, ToolInvocation, ToolResult
from backend.app.tools.media import _resource_error
from backend.app.tools.resources import (
    ResourceResolutionError,
    TemporaryArtifactKind,
    TemporaryArtifactRegistry,
)


TRANSCRIBE_AUDIO_TOOL_VERSION = "1.0"
DETECT_EDIT_MEMOS_TOOL_VERSION = "1.0"


@dataclass(frozen=True)
class TranscriptWordData:
    start_seconds: float
    end_seconds: float
    text: str
    probability: float | None


@dataclass(frozen=True)
class TranscriptSegmentData:
    start_seconds: float
    end_seconds: float
    text: str
    words: tuple[TranscriptWordData, ...] = ()


@dataclass(frozen=True)
class TranscriptData:
    text: str
    segments: tuple[TranscriptSegmentData, ...]
    language: str
    language_probability: float | None


@dataclass(frozen=True)
class TranscribeAudioInput:
    temporary_audio_id: UUID
    expected_project_id: UUID | None = None
    expected_source_video_id: UUID | None = None
    expected_scope_id: UUID | None = None
    word_timestamps: bool = True


@dataclass(frozen=True)
class DetectEditMemosInput:
    transcript: TranscriptData


@dataclass(frozen=True)
class DetectedMemoData:
    start_seconds: float
    end_seconds: float
    transcript_text: str
    matched_trigger: str
    matched_reference: str
    matched_action: str
    trigger_match_type: str
    trigger_similarity: float


@dataclass(frozen=True)
class DetectedMemosData:
    memos: tuple[DetectedMemoData, ...]


def transcribe_audio(
    request: TranscribeAudioInput,
    *,
    registry: TemporaryArtifactRegistry,
    model: Any,
    transcriber: Callable[..., STTResult] = transcribe_audio_service,
) -> ToolResult[TranscriptData]:
    if model is None:
        raise TypeError("A preloaded STT model is required.")
    invocation = ToolInvocation("transcribe_audio", TRANSCRIBE_AUDIO_TOOL_VERSION)
    try:
        path = registry.resolve(
            request.temporary_audio_id,
            expected_project_id=request.expected_project_id,
            expected_source_video_id=request.expected_source_video_id,
            expected_scope_id=request.expected_scope_id,
            expected_kind=TemporaryArtifactKind.AUDIO_WAV,
        )
    except ResourceResolutionError as exc:
        return invocation.failed(_resource_error(exc, request.temporary_audio_id))
    try:
        result = transcriber(path, model=model, word_timestamps=request.word_timestamps)
    except STTError:
        return invocation.failed(
            ToolError(
                ToolErrorCode.EXECUTION_FAILED,
                "Audio transcription failed.",
                retryable=False,
                affected_resource_id=request.temporary_audio_id,
            )
        )
    return invocation.succeeded(_to_transcript_data(result))


def detect_edit_memos(
    request: DetectEditMemosInput,
    *,
    detector: Callable[..., tuple[EditMemo, ...]] = detect_edit_memos_service,
) -> ToolResult[DetectedMemosData]:
    invocation = ToolInvocation("detect_edit_memos", DETECT_EDIT_MEMOS_TOOL_VERSION)
    try:
        memos = detector(_to_stt_result(request.transcript))
    except MemoDetectionError:
        return invocation.failed(
            ToolError(ToolErrorCode.INVALID_INPUT, "Transcript data is invalid.")
        )
    return invocation.succeeded(
        DetectedMemosData(
            memos=tuple(
                DetectedMemoData(
                    start_seconds=memo.start_seconds,
                    end_seconds=memo.end_seconds,
                    transcript_text=memo.transcript_text,
                    matched_trigger=memo.matched_trigger,
                    matched_reference=memo.matched_reference,
                    matched_action=memo.matched_action,
                    trigger_match_type=memo.trigger_match_type,
                    trigger_similarity=memo.trigger_similarity,
                )
                for memo in memos
            )
        )
    )


def _to_transcript_data(result: STTResult) -> TranscriptData:
    return TranscriptData(
        text=result.text,
        language=result.language,
        language_probability=result.language_probability,
        segments=tuple(
            TranscriptSegmentData(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=segment.text,
                words=tuple(
                    TranscriptWordData(
                        start_seconds=word.start_seconds,
                        end_seconds=word.end_seconds,
                        text=word.text,
                        probability=word.probability,
                    )
                    for word in segment.words
                ),
            )
            for segment in result.segments
        ),
    )


def _to_stt_result(data: TranscriptData) -> STTResult:
    if not isinstance(data, TranscriptData):
        raise MemoDetectionError("Transcript input is invalid.")
    return STTResult(
        text=data.text,
        language=data.language,
        language_probability=data.language_probability,
        segments=tuple(
            TranscriptSegment(
                start_seconds=segment.start_seconds,
                end_seconds=segment.end_seconds,
                text=segment.text,
                words=tuple(
                    TranscriptWord(
                        start_seconds=word.start_seconds,
                        end_seconds=word.end_seconds,
                        text=word.text,
                        probability=word.probability,
                    )
                    for word in segment.words
                ),
            )
            for segment in data.segments
        ),
    )
