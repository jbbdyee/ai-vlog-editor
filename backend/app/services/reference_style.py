"""TODO 33-1: measure the cut rhythm of a video I like (reels or vlog) and offer it as rule candidates.

FFmpeg ``scdet`` finds the moments the picture changes at once (hard cuts). From the gaps between them we keep a
few numbers (cut count, median cut, short/long share, cuts per minute) and turn them into rule sentences such as
"한 컷은 9초 넘지 않게" that the existing rule reader (``edit_rules.max_cut_seconds``) already keeps.

Shared by every project like the rules, kept in ``outputs/me/reference/`` (no database change, no AI, no paid call).
Slow dissolves are not cuts for ``scdet``, so a video full of them reads as fewer, longer cuts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import threading
import time
from typing import Sequence

SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm"}
# Scene analysis uses 10, but on my 8-minute edit 10 found 48 cuts (median 6.7s) while frame matching (TODO 29)
# found 64 (5.6s); 4~5 gives 64 cuts and 5.56s. Cuts between similar shots of one place score low.
THRESHOLD = 5.0
MIN_CUT = 0.4  # two changes closer than this are one cut (flash, fast pan)
SHORT = 2.0
LONG = 8.0
_SCDET = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+).*?lavfi\.scd\.time:\s*([0-9.]+)")


class ReferenceError(RuntimeError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def folder(project_output_root: Path) -> Path:
    """outputs/projects -> outputs/me/reference"""
    return Path(project_output_root).parent / "me" / "reference"


def saved_video(where: Path) -> Path | None:
    return next((path for path in sorted(where.glob("video.*")) if path.suffix.lower() in SUFFIXES), None)


def load_result(project_output_root: Path) -> dict | None:
    try:
        data = json.loads((folder(project_output_root) / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def probe_duration(path: Path, ffprobe: str | None = None) -> float:
    command = [ffprobe or shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0",
               "-show_entries", "stream=codec_type:format=duration", "-of", "json", str(path)]
    try:
        done = subprocess.run(command, capture_output=True, timeout=60, check=False)
        info = json.loads(done.stdout.decode("utf-8", "replace") or "{}")
        duration = float(info.get("format", {}).get("duration") or 0)
    except (OSError, subprocess.SubprocessError, ValueError, TypeError) as error:
        raise ReferenceError("REFERENCE_NOT_VIDEO") from error
    if not info.get("streams") or duration <= 0:
        raise ReferenceError("REFERENCE_NOT_VIDEO")
    return duration


def find_cuts(path: Path, ffmpeg: str | None = None) -> list[float]:
    """Times (seconds) where the picture changes at once. A small copy is read so 4K files stay quick."""
    command = [ffmpeg or shutil.which("ffmpeg") or "ffmpeg", "-hide_banner", "-nostats", "-nostdin", "-i", str(path),
               "-map", "0:v:0", "-an", "-sn", "-dn", "-vf", f"scale=480:-2,scdet=threshold={THRESHOLD}", "-f", "null", "-"]
    try:
        done = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                              timeout=1800, check=False)
    except (OSError, subprocess.SubprocessError) as error:
        raise ReferenceError("CUTS_FAILED") from error
    if done.returncode != 0:
        raise ReferenceError("CUTS_FAILED")
    return sorted(float(match.group(2)) for match in _SCDET.finditer(done.stderr))


def cut_lengths(times: Sequence[float], duration: float, min_cut: float = MIN_CUT) -> list[float]:
    edges = [0.0]
    for at in sorted(times):
        if min_cut <= at <= duration - min_cut and at - edges[-1] >= min_cut:
            edges.append(at)
    edges.append(duration)
    return [round(end - start, 3) for start, end in zip(edges, edges[1:]) if end > start]


def _percentile(values: Sequence[float], ratio: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * ratio
    low, high = math.floor(position), math.ceil(position)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def stats(lengths: Sequence[float]) -> dict:
    if not lengths:
        return {"cut_count": 0, "duration": 0.0, "median_cut": 0.0, "mean_cut": 0.0, "p90_cut": 0.0,
                "short_share": 0.0, "long_share": 0.0, "cuts_per_minute": 0.0}
    total = sum(lengths)
    return {
        "cut_count": len(lengths),
        "duration": round(total, 2),
        "median_cut": round(statistics.median(lengths), 2),
        "mean_cut": round(total / len(lengths), 2),
        "p90_cut": round(_percentile(lengths, 0.9), 2),
        "short_share": round(sum(1 for value in lengths if value < SHORT) / len(lengths), 3),
        "long_share": round(sum(1 for value in lengths if value > LONG) / len(lengths), 3),
        "cuts_per_minute": round(len(lengths) / (total / 60), 1) if total > 0 else 0.0,
    }


def _half(value: float) -> str:
    rounded = round(value * 2) / 2
    return f"{rounded:g}"


def rule_candidates(numbers: dict) -> list[dict]:
    """'N초 넘지 않게' (kept by Python) from the 90th percentile, 'M초 안팎' (read by the AI) from the median."""
    if numbers.get("cut_count", 0) < 3:
        return []
    out = []
    limit = max(2, math.ceil(numbers["p90_cut"]))
    out.append({"key": "max_cut", "text": f"한 컷은 {limit}초 넘지 않게",
                "why": f"컷 10개 중 9개가 {numbers['p90_cut']:.1f}초 이하"})
    out.append({"key": "median_cut", "text": f"한 컷은 {_half(numbers['median_cut'])}초 안팎",
                "why": f"한 컷 가운데 값 {numbers['median_cut']:.1f}초"})
    if numbers["short_share"] >= 0.3:
        out.append({"key": "short_cuts", "text": "2초 안 되는 짧은 컷을 자주 섞기",
                    "why": f"컷 {round(numbers['short_share'] * 100)}%가 2초 미만"})
    return out


def measure(path: Path, name: str, *, ffmpeg: str | None = None, ffprobe: str | None = None) -> dict:
    started = time.monotonic()
    duration = probe_duration(path, ffprobe)
    lengths = cut_lengths(find_cuts(path, ffmpeg), duration)
    numbers = stats(lengths)
    return {"filename": name, "measured_at": datetime.now(timezone.utc).isoformat(),
            "seconds_taken": round(time.monotonic() - started, 1), "video_duration": round(duration, 2),
            "stats": numbers, "lengths": lengths, "candidates": rule_candidates(numbers)}


# ---- one job at a time (in memory, like my_edit_compare) ------------------------------------------------------------

@dataclass
class Job:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    error_code: str | None = None


_job = Job()
_lock = threading.Lock()


def job_state() -> Job:
    with _lock:
        return Job(**vars(_job))


def _run(project_output_root: Path, path: Path, name: str) -> None:
    global _job
    try:
        result = measure(path, name)
        target = folder(project_output_root) / "result.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)
        state = Job("COMPLETED")
    except ReferenceError as error:
        state = Job("FAILED", error.code)
    except Exception:  # keep the job from staying RUNNING forever
        state = Job("FAILED", "REFERENCE_FAILED")
    with _lock:
        _job = state


def start(project_output_root: Path, name: str, *, background: bool = True) -> bool:
    """False when a measurement is already running."""
    global _job
    path = saved_video(folder(project_output_root))
    with _lock:
        if _job.status == "RUNNING":
            return False
        _job = Job("RUNNING")
    if path is None:
        with _lock:
            _job = Job("FAILED", "REFERENCE_MISSING")
        return True
    if background:
        threading.Thread(target=_run, args=(project_output_root, path, name), daemon=True).start()
    else:
        _run(project_output_root, path, name)
    return True
