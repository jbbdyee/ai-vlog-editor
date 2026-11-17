"""TODO 29: find where my own edited video came from in the project's sources and compare it with the Cutory plan.

Every frame is shrunk to a 32x18 grey picture and normalised (mean 0, length 1), so colour grading and brightness
changes do not matter; two pictures "look alike" when their dot product is high. Sources are read at their key frames
only (DJI cameras store one every 0.5 s, so this is fast) and the pictures are kept under
``outputs/projects/<id>/my_edit/prints/`` for next time. The edited video is read 4 times a second.

Each edited frame takes the most alike source frame; a run of frames from the same source whose time moves along with
the edit is one cut. Frames alike to nothing are "원본에 없음" (another day, title cards). No AI, no database change.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import statistics
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID

import numpy as np

from backend.app.services import taste_log

log = logging.getLogger(__name__)

PRINT_VERSION = 1
SIG_W, SIG_H = 32, 18
EDIT_FPS = 4.0
MATCH_MIN = 0.80  # a frame "comes from" a source frame at or above this
KEEP_MARGIN = 0.04  # stay on the current cut when its frame is this close to the best one (similar classroom shots)
JUMP_SECONDS = 1.5  # the source time may drift this much from the edit's time and still be the same cut
FLAT_STD = 4.0  # an (almost) single-colour picture: black / white transition, not compared
MIN_NOT_FOUND = 1.0  # shorter unfound bits are transitions
SOURCE_WORKERS = 3
TIMEOUT_SECONDS = 3600

_PTS = re.compile(r"pts_time:\s*(-?[0-9.]+)")


class MyEditError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


# --- pictures --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Frames:
    times: np.ndarray  # (n,) seconds
    sigs: np.ndarray  # (n, SIG_W*SIG_H) float32, mean 0 length 1; all zeros for a flat picture

    @property
    def flat(self) -> np.ndarray:
        return ~self.sigs.any(axis=1)


def normalise(raw: np.ndarray) -> np.ndarray:
    """(n, pixels) uint8 -> mean 0, length 1 rows; flat pictures become zeros."""
    values = raw.astype(np.float32)
    values -= values.mean(axis=1, keepdims=True)
    std = values.std(axis=1, keepdims=True)
    norms = np.linalg.norm(values, axis=1, keepdims=True)
    out = np.where(std >= FLAT_STD, values / np.maximum(norms, 1e-6), 0.0)
    return out.astype(np.float32)


def _frames_command(path: Path, keyframes_only: bool, fps: float | None, ffmpeg: str | None, hardware: bool) -> list[str]:
    command = [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info"]
    if hardware:  # the graphics card decodes 4K HEVC about 1.7x faster (25-minute source: 2m54s -> 1m42s)
        command += ["-hwaccel", "auto"]
    if keyframes_only:
        command += ["-skip_frame", "nokey"]
    filters = ([f"fps={fps:g}"] if fps else []) + [f"scale={SIG_W}:{SIG_H}:flags=area", "format=gray", "showinfo"]
    command += ["-i", str(path), "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", ",".join(filters)]
    if keyframes_only:
        command += ["-fps_mode", "passthrough"]
    return command + ["-f", "rawvideo", "-"]


def read_frames(path: Path, *, keyframes_only: bool, fps: float | None = None, ffmpeg: str | None = None) -> Frames:
    done = None
    for hardware in (True, False):
        try:
            done = subprocess.run(_frames_command(path, keyframes_only, fps, ffmpeg, hardware),
                                  capture_output=True, timeout=TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.SubprocessError) as error:
            raise MyEditError("FRAMES_FAILED") from error
        if done.returncode == 0 and done.stdout:
            break
    size = SIG_W * SIG_H
    count = len(done.stdout) // size
    times = [float(match.group(1)) for match in _PTS.finditer(done.stderr.decode("utf-8", "replace"))]
    if done.returncode != 0 or count == 0:
        raise MyEditError("FRAMES_FAILED")
    count = min(count, len(times))
    raw = np.frombuffer(done.stdout[:count * size], dtype=np.uint8).reshape(count, size)
    return Frames(np.asarray(times[:count], dtype=np.float64), normalise(raw))


def source_frames(path: Path, cache: Path, ffmpeg: str | None = None, *, fps: float | None = None) -> Frames:
    """Pictures of one video (key frames, or ``fps`` a second), kept in ``cache`` (re-made when the file changes)."""
    stat = path.stat()
    stamp = f"{PRINT_VERSION}:{fps}:{stat.st_size}:{int(stat.st_mtime)}"
    try:
        with np.load(cache) as saved:
            if str(saved["stamp"]) == stamp:
                return Frames(saved["times"], saved["sigs"])
    except (OSError, ValueError, KeyError):
        pass
    frames = read_frames(path, keyframes_only=fps is None, fps=fps, ffmpeg=ffmpeg)
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(".tmp.npz")
    np.savez(temporary, stamp=np.asarray(stamp), times=frames.times, sigs=frames.sigs)
    temporary.replace(cache)
    return frames


# --- matching --------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Source:
    source_id: UUID
    number: int  # filmed order (by file name, like the chat screen)
    filename: str
    duration: float
    path: Path | None = None


@dataclass(frozen=True)
class FrameMatch:
    source: int | None  # index into the sources list; None = not found
    time: float  # source seconds
    score: float
    flat: bool = False


def match_frames(edit: Frames, sources: Sequence[Frames], top: int = 8, chunk: int = 512) -> list[FrameMatch]:
    if not sources:
        return [FrameMatch(None, 0.0, 0.0, bool(flat)) for flat in edit.flat]
    sigs = np.concatenate([frames.sigs for frames in sources])
    owner = np.concatenate([np.full(len(frames.times), index) for index, frames in enumerate(sources)])
    when = np.concatenate([frames.times for frames in sources])
    if len(sigs) == 0:
        return [FrameMatch(None, 0.0, 0.0, bool(flat)) for flat in edit.flat]
    top = min(top, len(sigs))
    out: list[FrameMatch] = []
    previous: tuple[int, float] | None = None  # (source, source time - edit time) of the cut so far
    for begin in range(0, len(edit.times), chunk):
        scores = edit.sigs[begin:begin + chunk] @ sigs.T
        best = np.argpartition(-scores, top - 1, axis=1)[:, :top]
        for row in range(scores.shape[0]):
            index = begin + row
            if not edit.sigs[index].any():
                out.append(FrameMatch(None, 0.0, 0.0, True))
                continue
            ranked = sorted(best[row], key=lambda column: -scores[row, column])
            first = ranked[0]
            pick = first
            if previous is not None:
                for column in ranked:
                    if scores[row, column] < max(MATCH_MIN, scores[row, first] - KEEP_MARGIN):
                        break
                    if owner[column] == previous[0] and abs(when[column] - edit.times[index] - previous[1]) <= JUMP_SECONDS:
                        pick = column
                        break
            score = float(scores[row, pick])
            if score < MATCH_MIN:
                out.append(FrameMatch(None, 0.0, score))
                continue
            out.append(FrameMatch(int(owner[pick]), float(when[pick]), score))
            previous = (int(owner[pick]), float(when[pick] - edit.times[index]))
    return out


@dataclass(frozen=True)
class MyCut:
    edit_start: float
    edit_end: float
    source: int
    source_start: float
    source_end: float
    score: float

    @property
    def length(self) -> float:
        return round(self.edit_end - self.edit_start, 3)


@dataclass(frozen=True)
class Gap:
    edit_start: float
    edit_end: float


def build_cuts(times: Sequence[float], matches: Sequence[FrameMatch], step: float = 1 / EDIT_FPS
               ) -> tuple[list[MyCut], list[Gap]]:
    """Runs of frames from the same source moving along with the edit -> cuts; long unfound runs -> gaps."""
    runs: list[list[int]] = []
    current: list[int] = []
    for index, match in enumerate(matches):
        if match.source is None:
            continue
        if current:
            last = matches[current[-1]]
            offset_now = match.time - times[index]
            offset_then = last.time - times[current[-1]]
            if (match.source == last.source and abs(offset_now - offset_then) <= JUMP_SECONDS
                    and times[index] - times[current[-1]] <= 1.0 + 1e-6):
                current.append(index)
                continue
            runs.append(current)
        current = [index]
    if current:
        runs.append(current)
    cuts = []
    for run in runs:
        scores = [matches[index].score for index in run]
        if len(run) == 1 and scores[0] < 0.92:  # one lone frame is usually a wrong look-alike
            continue
        first, last = matches[run[0]], matches[run[-1]]
        cuts.append(MyCut(round(times[run[0]], 3), round(times[run[-1]] + step, 3), first.source,
                          round(first.time, 3), round(max(last.time, first.time) + step, 3),
                          round(float(np.mean(scores)), 3)))
    covered = np.zeros(len(times), dtype=bool)
    for cut in cuts:
        covered |= (np.asarray(times) >= cut.edit_start - 1e-6) & (np.asarray(times) < cut.edit_end - 1e-6)
    gaps: list[Gap] = []
    start = None
    for index, time in enumerate(times):
        missing = not covered[index] and not matches[index].flat
        if missing and start is None:
            start = time
        if not missing and start is not None:
            gaps.append(Gap(round(start, 3), round(time, 3)))
            start = None
    if start is not None:
        gaps.append(Gap(round(start, 3), round(times[-1] + step, 3)))
    return cuts, [gap for gap in gaps if gap.edit_end - gap.edit_start >= MIN_NOT_FOUND]


# --- comparing -------------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class PlanCut:
    """One cut of the Cutory plan (source time)."""
    candidate_id: str
    source: int
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for start, end in sorted(spans):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return [(a, b) for a, b in out]


def _overlap(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(e1, e2) - max(s1, s2)) for s1, e1 in a for s2, e2 in b)


def _stats(lengths: Sequence[float]) -> dict:
    return {"cut_count": len(lengths), "total_seconds": round(sum(lengths), 1),
            "median_cut": round(statistics.median(lengths), 2) if lengths else 0.0,
            "mean_cut": round(statistics.fmean(lengths), 2) if lengths else 0.0}


TagFn = Callable[[int, float, float], list[str]]


def compare(sources: Sequence[Source], cuts: Sequence[MyCut], gaps: Sequence[Gap], plan: Sequence[PlanCut],
            edit_duration: float, tags: TagFn) -> dict:
    """The numbers the card shows. ``tags(source, start, end)`` gives the scene's taste tags."""
    day_start, position = [], 0.0
    for source in sources:
        day_start.append(position)
        position += max(source.duration, 0.0)
    mine_spans = {index: _merge([(cut.source_start, cut.source_end) for cut in cuts if cut.source == index])
                  for index in range(len(sources))}
    plan_spans = {index: _merge([(cut.start, cut.end) for cut in plan if cut.source == index])
                  for index in range(len(sources))}
    overlap = sum(_overlap(mine_spans[index], plan_spans[index]) for index in range(len(sources)))
    tag_seconds: dict[str, dict[str, float]] = {}
    my_rows = []
    for number, cut in enumerate(cuts, start=1):
        cut_tags = tags(cut.source, cut.source_start, cut.source_end)
        for tag in cut_tags:
            tag_seconds.setdefault(tag, {"mine": 0.0, "cutory": 0.0})["mine"] += cut.length
        shared = _overlap([(cut.source_start, cut.source_end)], plan_spans[cut.source])
        source = sources[cut.source]
        my_rows.append({"number": number, "edit_start": cut.edit_start, "edit_end": cut.edit_end,
                        "length": cut.length, "source_id": str(source.source_id), "source_number": source.number,
                        "source_filename": source.filename, "source_start": cut.source_start,
                        "source_end": cut.source_end, "score": cut.score, "tags": cut_tags,
                        "in_cutory": bool(shared >= min(0.5, cut.length * 0.3))})
    for cut in plan:
        for tag in tags(cut.source, cut.start, cut.end):
            tag_seconds.setdefault(tag, {"mine": 0.0, "cutory": 0.0})["cutory"] += cut.length
    found = sum(cut.length for cut in cuts)
    return {
        "edit_duration": round(edit_duration, 1),
        "found_seconds": round(found, 1),
        "mine": _stats([cut.length for cut in cuts]),
        "cutory": _stats([cut.length for cut in plan]),
        "overlap_seconds": round(overlap, 1),
        "not_found": [{"edit_start": gap.edit_start, "edit_end": gap.edit_end} for gap in gaps],
        "not_found_seconds": round(sum(gap.edit_end - gap.edit_start for gap in gaps), 1),
        "day_seconds": round(position, 1),
        "sources": [{"number": source.number, "filename": source.filename, "day_start": round(day_start[index], 2),
                     "duration": round(source.duration, 2)} for index, source in enumerate(sources)],
        "mine_spans": [[round(day_start[index] + a, 2), round(day_start[index] + b, 2)]
                       for index, spans in mine_spans.items() for a, b in spans],
        "cutory_spans": [[round(day_start[index] + a, 2), round(day_start[index] + b, 2)]
                         for index, spans in plan_spans.items() for a, b in spans],
        "tags": {tag: {key: round(value, 1) for key, value in seconds.items()} for tag, seconds in tag_seconds.items()},
        "cuts": my_rows,
    }


def taste_choices(sources: Sequence[Source], cuts: Sequence[MyCut], plan: Sequence[PlanCut], tags: TagFn
                  ) -> list[taste_log.Choice]:
    """What my edit says about taste: plan cuts I also used (keep) or left out (drop), and my cuts Cutory missed (keep).
    Parts of the day neither of us used are not counted (most of any day is left out)."""
    mine = {index: _merge([(cut.source_start, cut.source_end) for cut in cuts if cut.source == index])
            for index in range(len(sources))}
    plan_spans = {index: _merge([(cut.start, cut.end) for cut in plan if cut.source == index])
                  for index in range(len(sources))}
    out = []
    for cut in plan:
        used = _overlap([(cut.start, cut.end)], mine[cut.source]) >= min(0.5, cut.length * 0.3)
        out.append(taste_log.Choice("my_edit_used" if used else "my_edit_unused", cut.candidate_id,
                                    tuple(tags(cut.source, cut.start, cut.end)), cut.length))
    for cut in cuts:
        if _overlap([(cut.source_start, cut.source_end)], plan_spans[cut.source]) < min(0.5, cut.length * 0.3):
            out.append(taste_log.Choice("my_edit_used", f"{sources[cut.source].source_id}@{cut.source_start:g}",
                                        tuple(tags(cut.source, cut.source_start, cut.source_end)), cut.length))
    return out


# --- files and the background job ------------------------------------------------------------------------------------

def output_dir(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "my_edit"


def saved_video(folder: Path) -> Path | None:
    for path in sorted(folder.glob("edit.*")):
        if path.is_file() and path.stat().st_size > 0 and not path.name.endswith(".tmp"):
            return path
    return None


def load_result(output_root: Path, project_id: UUID) -> dict | None:
    try:
        data = json.loads((output_dir(output_root, project_id) / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def probe_duration(path: Path, ffprobe: str | None = None) -> float:
    command = [ffprobe or shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=60, check=False)
        info = json.loads(done.stdout.decode("utf-8", "replace") or "{}")
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        raise MyEditError("MY_EDIT_NOT_VIDEO") from error
    if not info.get("streams"):
        raise MyEditError("MY_EDIT_NOT_VIDEO")
    try:
        duration = float(info.get("format", {}).get("duration"))
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        raise MyEditError("MY_EDIT_NOT_VIDEO")
    return duration


@dataclass
class Job:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    step: str = ""  # sources | edit | match
    done: int = 0
    total: int = 0
    error_code: str | None = None


_jobs: dict[UUID, Job] = {}
_jobs_lock = threading.Lock()


def job_state(project_id: UUID) -> Job:
    with _jobs_lock:
        job = _jobs.get(project_id)
        return Job(**vars(job)) if job else Job()


def any_running() -> bool:
    with _jobs_lock:
        return any(job.status == "RUNNING" for job in _jobs.values())


@dataclass(frozen=True)
class Inputs:
    """Everything read from the database before the job starts (the job itself never touches it)."""
    sources: tuple[Source, ...]
    plan: tuple[PlanCut, ...]
    tags: TagFn
    filename: str


def build_inputs(session, storage, output_root: Path, project_id: UUID, filename: str) -> Inputs:
    """Sources in filmed order with their files, the saved Cutory plan and the speech tags (read before the job)."""
    from sqlalchemy import select

    from backend.app.models import SourceVideo
    from backend.app.services import longform_chat
    from backend.app.storage.source_storage import SourceStorageError

    chat = longform_chat.load_inputs(session, output_root, project_id)
    rows = session.scalars(select(SourceVideo).where(SourceVideo.project_id == project_id)).all()
    rows = sorted(rows, key=lambda row: (row.original_filename or "", str(row.id)))
    sources = []
    for number, row in enumerate(rows, start=1):
        try:
            path = storage.resolve(row.storage_reference)
        except (SourceStorageError, AttributeError, ValueError):
            path = None
        sources.append(Source(row.id, number, row.original_filename or str(row.id),
                              float(row.duration_seconds or 0.0), path))
    position = {source.source_id: index for index, source in enumerate(sources)}
    plan = []
    for cut in chat.cuts:
        scene = chat.scenes[cut.candidate_id]
        if scene.source_video_id in position:
            plan.append(PlanCut(str(cut.candidate_id), position[scene.source_video_id], cut.start, cut.end))
    lines = {position[source_id]: value for source_id, value in chat.lines.items() if source_id in position}

    def tags(source: int, start: float, end: float) -> list[str]:
        return taste_log.scene_tags(lines.get(source, ()), start, end)

    return Inputs(tuple(sources), tuple(plan), tags, filename)


def run(output_root: Path, project_id: UUID, inputs: Inputs, *, on_progress: Callable[..., None] = lambda **_: None,
        ffmpeg: str | None = None) -> dict:
    folder = output_dir(output_root, project_id)
    video = saved_video(folder)
    if video is None:
        raise MyEditError("MY_EDIT_MISSING")
    started = datetime.now(timezone.utc)
    usable = [source for source in inputs.sources if source.path is not None and source.path.is_file()]
    on_progress(step="sources", done=0, total=len(usable))
    prints: dict[int, Frames] = {}
    done_count = 0
    lock = threading.Lock()
    skipped: list[str] = []

    def one(position: int) -> None:
        nonlocal done_count
        source = inputs.sources[position]
        try:
            prints[position] = source_frames(source.path, folder / "prints" / f"{source.source_id.hex}.npz", ffmpeg)
        except MyEditError:  # one unreadable source (a broken file) should not stop the rest
            log.warning("my edit: could not read source %s", source.filename)
            with lock:
                skipped.append(source.filename)
        with lock:
            done_count += 1
            on_progress(step="sources", done=done_count, total=len(usable))

    positions = [index for index, source in enumerate(inputs.sources) if source in usable]
    with ThreadPoolExecutor(max_workers=SOURCE_WORKERS) as pool:
        list(pool.map(one, positions))
    on_progress(step="edit", done=0, total=1)
    edit = source_frames(video, folder / "edit_prints.npz", ffmpeg, fps=EDIT_FPS)  # "다시 비교" reuses it
    on_progress(step="match", done=0, total=1)
    order = sorted(prints)
    matches = match_frames(edit, [prints[index] for index in order])
    matches = [FrameMatch(order[m.source], m.time, m.score, m.flat) if m.source is not None else m for m in matches]
    cuts, gaps = build_cuts(list(edit.times), matches)
    duration = float(edit.times[-1] + 1 / EDIT_FPS) if len(edit.times) else 0.0
    result = compare(inputs.sources, cuts, gaps, inputs.plan, duration, inputs.tags)
    result.update({"filename": inputs.filename, "compared_at": started.isoformat(),
                   "seconds_taken": round((datetime.now(timezone.utc) - started).total_seconds(), 1),
                   "frames": len(edit.times), "found_frames": sum(1 for m in matches if m.source is not None),
                   "skipped_sources": sorted(skipped)})
    choices = taste_choices(inputs.sources, cuts, inputs.plan, inputs.tags)
    taste_log.record_my_edit(output_root, project_id, choices, result["mine"], result["cutory"])
    temporary = folder / "result.tmp"
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    temporary.replace(folder / "result.json")
    return result


def start(output_root: Path, project_id: UUID, inputs: Inputs, *, background: bool = True) -> str | None:
    """None when started, otherwise a reason code."""
    with _jobs_lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return "MY_EDIT_RUNNING"
        _jobs[project_id] = Job(status="RUNNING")

    def update(**changes) -> None:
        with _jobs_lock:
            for key, value in changes.items():
                setattr(_jobs[project_id], key, value)

    def work() -> None:
        try:
            run(output_root, project_id, inputs, on_progress=update)
            update(status="COMPLETED", error_code=None)
        except MyEditError as error:
            log.warning("my edit compare failed: %s", error.code)
            update(status="FAILED", error_code=error.code)
        except Exception:  # noqa: BLE001 - the screen shows a safe code; details stay in the server log
            log.exception("my edit compare failed")
            update(status="FAILED", error_code="MY_EDIT_FAILED")

    if background:
        threading.Thread(target=work, name=f"my-edit-{project_id}", daemon=True).start()
    else:
        work()
    return None


