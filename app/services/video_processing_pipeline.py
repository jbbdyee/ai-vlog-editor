from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, TypeVar
from uuid import uuid4

from app.services.audio_extractor import ExtractedAudio, extract_audio
from app.services.candidate_generator import SceneCandidate, generate_candidates
from app.services.clip_renderer import RenderedClip, render_clip
from app.services.media_probe import MediaInfo, probe_media
from app.services.memo_detector import EditMemo, detect_edit_memos
from app.services.scene_selector import (
    SceneSelectionContext,
    SceneSelectionResult,
    SceneSelector,
)
from app.services.stt_service import STTResult, transcribe_audio


class PipelineStatus(str, Enum):
    COMPLETED = "COMPLETED"
    NO_EDIT_MEMO = "NO_EDIT_MEMO"
    NO_SCENE_SELECTED = "NO_SCENE_SELECTED"


class PipelineStage(str, Enum):
    SOURCE_VALIDATION = "source_validation"
    OUTPUT_PREPARATION = "output_preparation"
    MEDIA_PROBE = "media_probe"
    AUDIO_EXTRACTION = "audio_extraction"
    STT = "stt"
    MEMO_DETECTION = "memo_detection"
    CANDIDATE_GENERATION = "candidate_generation"
    CANDIDATE_SELECTION = "candidate_selection"
    CLIP_RENDERING = "clip_rendering"
    TOTAL = "total"


class PipelineExecutionError(RuntimeError):
    """Wrap a service failure with its pipeline stage and a safe summary."""

    def __init__(
        self,
        *,
        stage: PipelineStage,
        cause_type: str,
        safe_message: str,
    ) -> None:
        super().__init__(safe_message)
        self.stage = stage
        self.cause_type = cause_type
        self.safe_message = safe_message


@dataclass(frozen=True)
class VideoProcessingInput:
    source_video_path: Path
    output_directory: Path
    keep_intermediate_audio: bool = False


@dataclass(frozen=True)
class PipelineStageTiming:
    stage: PipelineStage
    duration_seconds: float


@dataclass(frozen=True)
class MemoProcessingResult:
    memo: EditMemo
    generated_candidates: tuple[SceneCandidate, ...]
    selection: SceneSelectionResult
    rendered_clip: RenderedClip | None


@dataclass(frozen=True)
class VideoProcessingResult:
    status: PipelineStatus
    source_path: Path
    media_info: MediaInfo
    extracted_audio: ExtractedAudio | None
    transcript: STTResult
    memo_results: tuple[MemoProcessingResult, ...]
    timings: tuple[PipelineStageTiming, ...]
    warnings: tuple[str, ...]


_T = TypeVar("_T")


class VideoProcessingPipeline:
    """Run the local MVP workflow without depending on HTTP or evaluation data."""

    def __init__(self, *, selector: SceneSelector, stt_model: Any | None = None) -> None:
        if selector is None or not callable(getattr(selector, "select", None)):
            raise ValueError("A SceneSelector must be provided.")
        self._selector = selector
        self._stt_model = stt_model

    def process(self, processing_input: VideoProcessingInput) -> VideoProcessingResult:
        total_started = perf_counter()
        timings: list[PipelineStageTiming] = []
        warnings: list[str] = []
        extracted_audio: ExtractedAudio | None = None

        processing_input = self._validate_input(processing_input)
        source_path = processing_input.source_video_path

        run_directory = self._run_stage(
            PipelineStage.OUTPUT_PREPARATION,
            timings,
            lambda: self._prepare_run_directory(processing_input.output_directory),
        )
        audio_directory = run_directory / "audio"
        clip_directory = run_directory / "clips"

        try:
            media_info = self._run_stage(
                PipelineStage.MEDIA_PROBE,
                timings,
                lambda: self._probe_and_validate(source_path),
            )
            extracted_audio = self._run_stage(
                PipelineStage.AUDIO_EXTRACTION,
                timings,
                lambda: extract_audio(source_path, audio_directory),
            )
            transcript = self._run_stage(
                PipelineStage.STT,
                timings,
                lambda: transcribe_audio(
                    extracted_audio.audio_path,
                    model=self._stt_model,
                    word_timestamps=True,
                ),
            )
            memos = self._run_stage(
                PipelineStage.MEMO_DETECTION,
                timings,
                lambda: detect_edit_memos(transcript),
            )

            memo_results: list[MemoProcessingResult] = []
            rendered_count = 0
            for memo in memos:
                candidates = self._run_stage(
                    PipelineStage.CANDIDATE_GENERATION,
                    timings,
                    lambda memo=memo: generate_candidates(memo),
                )
                context = SceneSelectionContext(
                    source_video_path=source_path,
                    extracted_audio=extracted_audio,
                    media_info=media_info,
                    transcript=transcript,
                    memo=memo,
                    fixed_candidates=candidates,
                )
                selection = self._run_stage(
                    PipelineStage.CANDIDATE_SELECTION,
                    timings,
                    lambda context=context: self._select(context),
                )
                rendered = None
                if selection.candidate is not None:
                    rendered = self._run_stage(
                        PipelineStage.CLIP_RENDERING,
                        timings,
                        lambda candidate=selection.candidate: render_clip(
                            source_path, candidate, clip_directory
                        ),
                    )
                    rendered_count += 1
                memo_results.append(
                    MemoProcessingResult(
                        memo=memo,
                        generated_candidates=candidates,
                        selection=selection,
                        rendered_clip=rendered,
                    )
                )

            if not memos:
                status = PipelineStatus.NO_EDIT_MEMO
            elif rendered_count == 0:
                status = PipelineStatus.NO_SCENE_SELECTED
            else:
                status = PipelineStatus.COMPLETED
        finally:
            if (
                extracted_audio is not None
                and not processing_input.keep_intermediate_audio
            ):
                try:
                    _remove_intermediate_audio(extracted_audio.audio_path)
                except OSError:
                    warnings.append("Could not remove the intermediate audio file.")

        timings.append(
            PipelineStageTiming(
                stage=PipelineStage.TOTAL,
                duration_seconds=perf_counter() - total_started,
            )
        )
        return VideoProcessingResult(
            status=status,
            source_path=source_path,
            media_info=media_info,
            extracted_audio=(
                extracted_audio if processing_input.keep_intermediate_audio else None
            ),
            transcript=transcript,
            memo_results=tuple(memo_results),
            timings=tuple(timings),
            warnings=tuple(warnings),
        )

    def _validate_input(
        self, processing_input: VideoProcessingInput
    ) -> VideoProcessingInput:
        try:
            if not isinstance(processing_input, VideoProcessingInput):
                raise TypeError("Input must be a VideoProcessingInput.")
            if not isinstance(processing_input.source_video_path, Path):
                raise TypeError("Source video path must be a Path.")
            if not processing_input.source_video_path.is_file():
                raise FileNotFoundError("Source video does not exist.")
            if not isinstance(processing_input.output_directory, Path):
                raise TypeError("Output directory must be a Path.")
            if not isinstance(processing_input.keep_intermediate_audio, bool):
                raise TypeError("keep_intermediate_audio must be a boolean.")
        except Exception as exc:
            raise self._pipeline_error(PipelineStage.SOURCE_VALIDATION, exc) from exc
        return processing_input

    def _prepare_run_directory(self, output_directory: Path) -> Path:
        run_directory = output_directory / uuid4().hex
        run_directory.mkdir(parents=True, exist_ok=False)
        return run_directory

    @staticmethod
    def _probe_and_validate(source_path: Path) -> MediaInfo:
        media_info = probe_media(source_path)
        if not media_info.has_video_stream:
            raise ValueError("Source media has no video stream.")
        if not media_info.has_audio_stream:
            raise ValueError("Source media has no audio stream.")
        return media_info

    def _select(self, context: SceneSelectionContext) -> SceneSelectionResult:
        selection = self._selector.select(context)
        if not isinstance(selection, SceneSelectionResult):
            raise TypeError("Scene selector returned an invalid result.")
        if selection.candidate is not None and not isinstance(
            selection.candidate, SceneCandidate
        ):
            raise TypeError("Scene selector returned an invalid candidate.")
        return selection

    def _run_stage(
        self,
        stage: PipelineStage,
        timings: list[PipelineStageTiming],
        operation: Callable[[], _T],
    ) -> _T:
        started = perf_counter()
        try:
            return operation()
        except PipelineExecutionError:
            raise
        except Exception as exc:
            raise self._pipeline_error(stage, exc) from exc
        finally:
            timings.append(
                PipelineStageTiming(
                    stage=stage,
                    duration_seconds=perf_counter() - started,
                )
            )

    @staticmethod
    def _pipeline_error(
        stage: PipelineStage, cause: Exception
    ) -> PipelineExecutionError:
        return PipelineExecutionError(
            stage=stage,
            cause_type=type(cause).__name__,
            safe_message=f"Video processing failed during {stage.value}.",
        )


def _remove_intermediate_audio(audio_path: Path) -> None:
    audio_path.unlink(missing_ok=True)
