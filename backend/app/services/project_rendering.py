"""Render a persisted user scene order into one MP4; no user-facing API here."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from typing import Callable
from uuid import UUID, uuid4

from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models import SceneCandidate as StoredSceneCandidate, SourceVideo
from backend.app.services.candidate_generator import SceneCandidate as ClipSceneCandidate
from backend.app.services.clip_renderer import ClipRenderError, RenderedClip, render_clip
from backend.app.services.media_probe import MediaInfo, MediaProbeError, probe_media
from backend.app.services.project_scene_candidates import SceneProjectNotFoundError
from backend.app.services.project_scene_edit_plan import get_scene_edit_plan
from backend.app.storage.source_storage import SourceStorage, SourceStorageError


OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720
OUTPUT_FPS = 30
OUTPUT_AUDIO_RATE = 48_000


class ProjectRenderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class _Segment:
    candidate_id: UUID
    source_reference: str
    start_seconds: float
    end_seconds: float


@dataclass(frozen=True)
class ProjectRenderResult:
    project_id: UUID
    render_id: UUID
    output_path: Path
    candidate_ids: tuple[UUID, ...]
    duration_seconds: float
    video_codec: str | None
    audio_codec: str | None
    file_size_bytes: int


def render_project_edit_plan(
    *,
    session_factory: sessionmaker[Session],
    source_storage: SourceStorage,
    project_id: UUID,
    output_root: Path,
    render_one: Callable[..., RenderedClip] = render_clip,
    inspect_media: Callable[[Path], MediaInfo] = probe_media,
    run_ffmpeg: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ffmpeg_executable: str = "ffmpeg",
) -> ProjectRenderResult:
    """Validate a saved plan, render each exact interval, normalize and concatenate.

    The caller owns ``output_root``. Only a successful final MP4 is retained;
    intermediate clips and partial output are always removed.
    """
    if not isinstance(project_id, UUID):
        raise ProjectRenderError("INVALID_PROJECT_ID", "Project ID is invalid.")
    try:
        with session_factory() as session:
            segments = _load_segments(session, project_id)
    except SceneProjectNotFoundError as error:
        raise ProjectRenderError("PROJECT_NOT_FOUND", "Project was not found.") from error

    root = Path(output_root).resolve()
    render_id = uuid4()
    run_directory = root / "projects" / project_id.hex / "renders" / render_id.hex
    try:
        if not run_directory.parent.resolve().is_relative_to(root):
            raise ProjectRenderError("OUTPUT_PATH_INVALID", "Render output path is invalid.")
        run_directory.mkdir(parents=True, exist_ok=False)
        if not run_directory.resolve().is_relative_to(root):
            raise ProjectRenderError("OUTPUT_PATH_INVALID", "Render output path is invalid.")
    except OSError as error:
        raise ProjectRenderError("OUTPUT_PREPARATION_FAILED", "Could not prepare render output.") from error

    final_path = run_directory / "final.mp4"
    succeeded = False
    try:
        with TemporaryDirectory(prefix="segments-", dir=run_directory) as temporary:
            rendered: list[RenderedClip] = []
            has_audio: list[bool] = []
            for segment in segments:
                try:
                    source_path = source_storage.resolve(segment.source_reference)
                    if not source_path.is_file():
                        raise ProjectRenderError("SOURCE_MISSING", "A selected SourceVideo is missing.")
                    source_info = inspect_media(source_path)
                    if not source_info.has_video_stream:
                        raise ProjectRenderError("SOURCE_INVALID", "A selected SourceVideo has no video stream.")
                    if segment.end_seconds > source_info.duration_seconds + 1e-3:
                        raise ProjectRenderError("INTERVAL_INVALID", "A selected interval exceeds its SourceVideo duration.")
                    candidate = ClipSceneCandidate(
                        window_seconds=segment.end_seconds - segment.start_seconds,
                        start_seconds=segment.start_seconds,
                        end_seconds=segment.end_seconds,
                    )
                    clip = render_one(source_path, candidate, Path(temporary), ffmpeg_executable=ffmpeg_executable)
                    if not clip.clip_path.resolve().is_relative_to(Path(temporary).resolve()):
                        raise ProjectRenderError("CLIP_PATH_INVALID", "A rendered segment escaped its workspace.")
                    if (not clip.clip_path.is_file() or clip.clip_path.stat().st_size == 0
                        or not isfinite(clip.duration_seconds) or clip.duration_seconds <= 0):
                        raise ProjectRenderError("CLIP_OUTPUT_MISSING", "A rendered segment is missing.")
                    rendered.append(clip)
                    has_audio.append(inspect_media(clip.clip_path).has_audio_stream)
                except ProjectRenderError:
                    raise
                except (SourceStorageError, ClipRenderError, MediaProbeError, OSError) as error:
                    raise ProjectRenderError("SEGMENT_RENDER_FAILED", "A selected segment could not be rendered.") from error

            # A plan or active-result change during a long render must not silently
            # publish a video based on a now-invalid or reordered selection.
            _assert_plan_current(session_factory, project_id, segments)

            command = _concat_command(rendered, has_audio, final_path, ffmpeg_executable)
            try:
                result = run_ffmpeg(
                    command, capture_output=True, text=True, encoding="utf-8",
                    errors="replace", check=False,
                )
            except OSError as error:
                raise ProjectRenderError("CONCAT_START_FAILED", "Could not start video concatenation.") from error
            if result.returncode != 0:
                raise ProjectRenderError("CONCAT_FAILED", "Video concatenation failed.")
            if not final_path.is_file() or final_path.stat().st_size == 0:
                raise ProjectRenderError("OUTPUT_MISSING", "Final MP4 was not created.")
            try:
                info = inspect_media(final_path)
            except MediaProbeError as error:
                raise ProjectRenderError("OUTPUT_INVALID", "Final MP4 could not be inspected.") from error
            if (not info.has_video_stream or not info.has_audio_stream
                or not isfinite(info.duration_seconds) or info.duration_seconds <= 0):
                raise ProjectRenderError("OUTPUT_INVALID", "Final MP4 is missing a required stream.")
            _assert_plan_current(session_factory, project_id, segments)
            output = ProjectRenderResult(
                project_id=project_id, render_id=render_id, output_path=final_path,
                candidate_ids=tuple(segment.candidate_id for segment in segments),
                duration_seconds=info.duration_seconds, video_codec=info.video_codec,
                audio_codec=info.audio_codec, file_size_bytes=final_path.stat().st_size,
            )
            succeeded = True
            return output
    finally:
        if not succeeded:
            final_path.unlink(missing_ok=True)
            try:
                run_directory.rmdir()
            except OSError:
                # Only remove our partial final MP4; never recursively delete an
                # unexpected file in the output directory.
                pass


def validate_project_render_request(
    session_factory: sessionmaker[Session], project_id: UUID
) -> tuple[UUID, ...]:
    """Fast read-only preflight for the API; the engine revalidates when it runs."""
    try:
        with session_factory() as session:
            return tuple(segment.candidate_id for segment in _load_segments(session, project_id))
    except SceneProjectNotFoundError as error:
        raise ProjectRenderError("PROJECT_NOT_FOUND", "Project was not found.") from error


def _load_segments(session: Session, project_id: UUID) -> tuple[_Segment, ...]:
    plan = get_scene_edit_plan(session, project_id)
    if not plan.candidate_ids:
        raise ProjectRenderError("EMPTY_EDIT_PLAN", "The project edit plan is empty.")
    if plan.invalid_candidate_ids:
        raise ProjectRenderError("PLAN_CANDIDATE_CONFLICT", "The edit plan contains a candidate that is no longer active.")
    segments = []
    for candidate_id in plan.candidate_ids:
        candidate = session.get(StoredSceneCandidate, candidate_id)
        if candidate is None:
            raise ProjectRenderError("PLAN_CANDIDATE_CONFLICT", "A selected candidate no longer exists.")
        source = session.get(SourceVideo, candidate.source_video_id)
        if source is None or source.project_id != project_id:
            raise ProjectRenderError("SOURCE_MISSING", "A selected SourceVideo is missing or outside this Project.")
        start, end = float(candidate.start_seconds), float(candidate.end_seconds)
        duration = float(source.duration_seconds) if source.duration_seconds is not None else None
        if (not isfinite(start) or not isfinite(end) or start < 0 or end <= start
            or duration is None or not isfinite(duration) or end > duration + 1e-3):
            raise ProjectRenderError("INTERVAL_INVALID", "A selected interval is invalid.")
        segments.append(_Segment(candidate_id, source.storage_reference, start, end))
    return tuple(segments)


def _assert_plan_current(
    session_factory: sessionmaker[Session], project_id: UUID, expected: tuple[_Segment, ...]
) -> None:
    try:
        with session_factory() as session:
            current = _load_segments(session, project_id)
    except (SceneProjectNotFoundError, ProjectRenderError) as error:
        raise ProjectRenderError("PLAN_CHANGED", "The edit plan changed during rendering.") from error
    except SQLAlchemyError as error:
        raise ProjectRenderError("PLAN_STATE_UNAVAILABLE", "Could not verify the edit plan during rendering.") from error
    if current != expected:
        raise ProjectRenderError("PLAN_CHANGED", "The edit plan changed during rendering.")


def _concat_command(
    clips: list[RenderedClip], has_audio: list[bool], destination: Path, executable: str
) -> list[str]:
    command = [executable, "-v", "error", "-nostdin", "-y"]
    for clip in clips:
        command.extend(["-i", str(clip.clip_path)])
    silence_index: dict[int, int] = {}
    for index, audio in enumerate(has_audio):
        if not audio:
            silence_index[index] = len(clips) + len(silence_index)
            command.extend(["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"])
    filters = []
    for index, clip in enumerate(clips):
        filters.append(
            f"[{index}:v:0]fps={OUTPUT_FPS},scale={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:"
            "force_original_aspect_ratio=decrease,"
            f"pad={OUTPUT_WIDTH}:{OUTPUT_HEIGHT}:(ow-iw)/2:(oh-ih)/2,"
            f"setsar=1,format=yuv420p,setpts=PTS-STARTPTS[v{index}]"
        )
        audio_input = f"{index}:a:0" if has_audio[index] else str(silence_index[index])
        filters.append(
            f"[{audio_input}]aresample={OUTPUT_AUDIO_RATE},"
            "aformat=sample_fmts=fltp:channel_layouts=stereo,"
            f"asetpts=PTS-STARTPTS,apad,atrim=duration={clip.duration_seconds:.6f}[a{index}]"
        )
    filters.append("".join(f"[v{i}][a{i}]" for i in range(len(clips))) +
                   f"concat=n={len(clips)}:v=1:a=1[v][a]")
    command.extend([
        "-filter_complex", ";".join(filters), "-map", "[v]", "-map", "[a]",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart", str(destination),
    ])
    return command
