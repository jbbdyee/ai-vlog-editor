"""Project-level VLM pass over active scene candidates (one background run per project, in-process)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from threading import Lock
from uuid import UUID

from backend.app.models import SceneCandidate, SourceVideo
from backend.app.services.project_scene_candidates import list_active_project_candidates
from backend.app.services.vlm_scene_captioner import VLMCaptionError, caption_interval, existing_caption, store_caption, vlm_model

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cutory-vlm")
_lock = Lock()
_runs: dict[UUID, "VisionRun"] = {}


@dataclass
class VisionRun:
    status: str = "NOT_STARTED"  # QUEUED | RUNNING | COMPLETED | COMPLETED_WITH_WARNINGS | FAILED
    model: str = ""
    total: int = 0
    captioned: int = 0
    skipped: int = 0
    failed: int = 0
    error_codes: list[str] = field(default_factory=list)
    latency_seconds: list[float] = field(default_factory=list)


def vision_status(project_id: UUID) -> dict:
    with _lock:
        run = _runs.get(project_id)
        return asdict(run) if run else asdict(VisionRun())


def start_vision(project_id: UUID, session_factory, source_storage, ffmpeg: str = "ffmpeg") -> bool:
    with _lock:
        current = _runs.get(project_id)
        if current and current.status in ("QUEUED", "RUNNING"):
            return False
        _runs[project_id] = VisionRun(status="QUEUED", model=vlm_model())
    _executor.submit(_run, project_id, session_factory, source_storage, ffmpeg)
    return True


def _update(project_id: UUID, **changes) -> None:
    with _lock:
        run = _runs[project_id]
        for key, value in changes.items():
            setattr(run, key, value)


def _run(project_id: UUID, session_factory, source_storage, ffmpeg: str) -> None:
    model = vlm_model()
    try:
        with session_factory() as session:
            candidates = list_active_project_candidates(session, project_id)
            _update(project_id, status="RUNNING", total=len(candidates))
            for item in candidates:
                if existing_caption(session, item.candidate_id, model) is not None:
                    with _lock:
                        _runs[project_id].skipped += 1
                    continue
                candidate = session.get(SceneCandidate, item.candidate_id)
                source = session.get(SourceVideo, item.source_video_id)
                try:
                    path = source_storage.resolve(source.storage_reference)
                    result = caption_interval(path, float(candidate.start_seconds), float(candidate.end_seconds),
                                              model=model, ffmpeg=ffmpeg)
                    store_caption(session, candidate, result)
                    session.commit()
                    with _lock:
                        _runs[project_id].captioned += 1
                        _runs[project_id].latency_seconds.append(result.latency_seconds)
                except VLMCaptionError as error:
                    session.rollback()
                    with _lock:
                        _runs[project_id].failed += 1
                        _runs[project_id].error_codes.append(error.code)
        with _lock:
            run = _runs[project_id]
            run.status = "COMPLETED_WITH_WARNINGS" if run.failed else "COMPLETED"
    except Exception:
        _update(project_id, status="FAILED")
