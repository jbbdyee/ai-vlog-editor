from dataclasses import asdict
from pathlib import Path
import re

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from app.services.scene_selector import FixedWindowSceneSelector
from app.services.video_processing_pipeline import (
    PipelineExecutionError,
    PipelineStage,
    PipelineStatus,
    VideoProcessingInput,
    VideoProcessingPipeline,
    VideoProcessingResult,
)
from app.services.video_storage import VideoValidationError, save_video_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
UPLOAD_DIRECTORY = PROJECT_ROOT / "uploads"
PROCESS_OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "api"
ALLOWED_PROCESS_WINDOWS_SECONDS = frozenset({5.0, 10.0, 15.0, 30.0})
RESOURCE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")


class VideoUploadResponse(BaseModel):
    original_filename: str
    stored_filename: str
    content_type: str
    video_id: str


class MediaResponse(BaseModel):
    duration_seconds: float
    has_video_stream: bool
    has_audio_stream: bool
    video_codec: str | None
    audio_codec: str | None
    format_name: str


class SegmentResponse(BaseModel):
    start_seconds: float
    end_seconds: float
    text: str


class TranscriptResponse(BaseModel):
    text: str
    language: str
    language_probability: float | None
    segments: list[SegmentResponse]


class MemoResponse(BaseModel):
    start_seconds: float
    end_seconds: float
    transcript_text: str
    matched_trigger: str
    matched_reference: str
    matched_action: str


class CandidateResponse(BaseModel):
    window_seconds: float
    start_seconds: float
    end_seconds: float


class SelectionResponse(BaseModel):
    strategy_name: str
    selected_source_id: str | None
    reasoning_code: str
    reasoning_summary: str | None
    candidate: CandidateResponse | None


class RenderedClipResponse(BaseModel):
    clip_id: str
    filename: str
    start_seconds: float
    end_seconds: float
    duration_seconds: float
    video_codec: str | None
    audio_codec: str | None
    download_url: str


class MemoProcessingResponse(BaseModel):
    memo: MemoResponse
    generated_candidates: list[CandidateResponse]
    selection: SelectionResponse
    rendered_clip: RenderedClipResponse | None


class TimingResponse(BaseModel):
    stage: str
    duration_seconds: float


class VideoProcessResponse(BaseModel):
    video_id: str
    stored_filename: str
    status: PipelineStatus
    media: MediaResponse
    transcript: TranscriptResponse
    memos: list[MemoProcessingResponse]
    timings: list[TimingResponse]
    warnings: list[str]


router = APIRouter(
    prefix="/videos",
    tags=["videos"],
)


@router.post("/upload", response_model=VideoUploadResponse)
async def upload_video(file: UploadFile = File(...)):
    try:
        stored_video = await run_in_threadpool(
            save_video_file,
            file.file,
            file.filename,
            file.content_type,
            UPLOAD_DIRECTORY,
        )
    except VideoValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    return asdict(stored_video)


@router.post("/process", response_model=VideoProcessResponse)
async def process_video(
    request: Request,
    file: UploadFile = File(...),
    window_seconds: float = Form(...),
) -> VideoProcessResponse:
    _validate_process_window(window_seconds)

    try:
        stored_video = await run_in_threadpool(
            save_video_file,
            file.file,
            file.filename,
            file.content_type,
            UPLOAD_DIRECTORY,
        )
    except VideoValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=str(error),
        ) from error
    finally:
        await file.close()

    selector = FixedWindowSceneSelector(window_seconds=window_seconds)
    pipeline = VideoProcessingPipeline(
        selector=selector,
        stt_model=request.app.state.stt_model,
    )
    processing_input = VideoProcessingInput(
        source_video_path=UPLOAD_DIRECTORY / stored_video.stored_filename,
        output_directory=PROCESS_OUTPUT_DIRECTORY,
        keep_intermediate_audio=False,
    )

    try:
        async with request.app.state.pipeline_semaphore:
            result = await run_in_threadpool(pipeline.process, processing_input)
    except PipelineExecutionError as error:
        raise _pipeline_http_exception(error) from error

    return _to_video_process_response(
        video_id=stored_video.video_id,
        stored_filename=stored_video.stored_filename,
        result=result,
    )


@router.get("/clips/{run_id}/{clip_id:path}", response_class=FileResponse)
async def download_clip(run_id: str, clip_id: str) -> FileResponse:
    _validate_resource_id(run_id, field_name="run_id")
    _validate_resource_id(clip_id, field_name="clip_id")

    output_root = PROCESS_OUTPUT_DIRECTORY.resolve()
    clips_directory = (PROCESS_OUTPUT_DIRECTORY / run_id / "clips").resolve()
    clip_path = (clips_directory / f"{clip_id}.mp4").resolve()

    if not _is_relative_to(clips_directory, output_root):
        raise _clip_not_found()
    if not _is_relative_to(clip_path, clips_directory):
        raise _clip_not_found()
    if clip_path.parent != clips_directory or not clip_path.is_file():
        raise _clip_not_found()

    return FileResponse(
        path=clip_path,
        media_type="video/mp4",
        filename=f"{clip_id}.mp4",
        content_disposition_type="inline",
    )


def _validate_process_window(window_seconds: float) -> None:
    if window_seconds not in ALLOWED_PROCESS_WINDOWS_SECONDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_WINDOW_SECONDS",
                "message": "window_seconds must be one of 5, 10, 15, or 30.",
            },
        )


def _validate_resource_id(value: str, *, field_name: str) -> None:
    if RESOURCE_ID_PATTERN.fullmatch(value) is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "INVALID_CLIP_IDENTIFIER",
                "field": field_name,
                "message": f"{field_name} must be a 32-character lowercase hexadecimal ID.",
            },
        )


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _clip_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "code": "CLIP_NOT_FOUND",
            "message": "Rendered clip was not found.",
        },
    )


def _pipeline_http_exception(error: PipelineExecutionError) -> HTTPException:
    client_error_stages = {
        PipelineStage.SOURCE_VALIDATION,
        PipelineStage.MEDIA_PROBE,
        PipelineStage.AUDIO_EXTRACTION,
    }
    status_code = (
        status.HTTP_422_UNPROCESSABLE_CONTENT
        if error.stage in client_error_stages
        else status.HTTP_500_INTERNAL_SERVER_ERROR
    )
    return HTTPException(
        status_code=status_code,
        detail={
            "code": f"PIPELINE_{error.stage.value.upper()}_FAILED",
            "stage": error.stage.value,
            "message": error.safe_message,
        },
    )


def _to_video_process_response(
    *,
    video_id: str,
    stored_filename: str,
    result: VideoProcessingResult,
) -> VideoProcessResponse:
    return VideoProcessResponse(
        video_id=video_id,
        stored_filename=stored_filename,
        status=result.status,
        media=MediaResponse(
            duration_seconds=result.media_info.duration_seconds,
            has_video_stream=result.media_info.has_video_stream,
            has_audio_stream=result.media_info.has_audio_stream,
            video_codec=result.media_info.video_codec,
            audio_codec=result.media_info.audio_codec,
            format_name=result.media_info.format_name,
        ),
        transcript=TranscriptResponse(
            text=result.transcript.text,
            language=result.transcript.language,
            language_probability=result.transcript.language_probability,
            segments=[
                SegmentResponse(
                    start_seconds=segment.start_seconds,
                    end_seconds=segment.end_seconds,
                    text=segment.text,
                )
                for segment in result.transcript.segments
            ],
        ),
        memos=[
            MemoProcessingResponse(
                memo=MemoResponse(
                    start_seconds=memo_result.memo.start_seconds,
                    end_seconds=memo_result.memo.end_seconds,
                    transcript_text=memo_result.memo.transcript_text,
                    matched_trigger=memo_result.memo.matched_trigger,
                    matched_reference=memo_result.memo.matched_reference,
                    matched_action=memo_result.memo.matched_action,
                ),
                generated_candidates=[
                    CandidateResponse(
                        window_seconds=candidate.window_seconds,
                        start_seconds=candidate.start_seconds,
                        end_seconds=candidate.end_seconds,
                    )
                    for candidate in memo_result.generated_candidates
                ],
                selection=SelectionResponse(
                    strategy_name=memo_result.selection.strategy_name,
                    selected_source_id=memo_result.selection.selected_source_id,
                    reasoning_code=memo_result.selection.reasoning_code,
                    reasoning_summary=memo_result.selection.reasoning_summary,
                    candidate=(
                        None
                        if memo_result.selection.candidate is None
                        else CandidateResponse(
                            window_seconds=memo_result.selection.candidate.window_seconds,
                            start_seconds=memo_result.selection.candidate.start_seconds,
                            end_seconds=memo_result.selection.candidate.end_seconds,
                        )
                    ),
                ),
                rendered_clip=(
                    None
                    if memo_result.rendered_clip is None
                    else RenderedClipResponse(
                        clip_id=memo_result.rendered_clip.clip_path.stem,
                        filename=memo_result.rendered_clip.clip_path.name,
                        start_seconds=memo_result.rendered_clip.start_seconds,
                        end_seconds=memo_result.rendered_clip.end_seconds,
                        duration_seconds=memo_result.rendered_clip.duration_seconds,
                        video_codec=memo_result.rendered_clip.video_codec,
                        audio_codec=memo_result.rendered_clip.audio_codec,
                        download_url=_clip_download_url(
                            memo_result.rendered_clip.clip_path
                        ),
                    )
                ),
            )
            for memo_result in result.memo_results
        ],
        timings=[
            TimingResponse(
                stage=timing.stage.value,
                duration_seconds=timing.duration_seconds,
            )
            for timing in result.timings
        ],
        warnings=list(result.warnings),
    )


def _clip_download_url(clip_path: Path) -> str:
    clip_id = clip_path.stem
    run_id = clip_path.parent.parent.name
    _validate_resource_id(run_id, field_name="run_id")
    _validate_resource_id(clip_id, field_name="clip_id")
    if clip_path.suffix.lower() != ".mp4" or clip_path.parent.name != "clips":
        raise ValueError("Rendered clip path does not follow the API output layout.")
    return f"/videos/clips/{run_id}/{clip_id}"
