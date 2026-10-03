from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from uuid import UUID


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.app.services.shot_structure import (  # noqa: E402
    ShotDetectionConfig,
    detect_shot_structure,
)


SOURCE_ID = UUID("00000000-0000-0000-0000-000000000901")
TOLERANCE_SECONDS = 0.15
CONFIG = ShotDetectionConfig(threshold_percent=10.0, minimum_shot_duration_seconds=0.5)


def main() -> int:
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print(json.dumps({"status": "ENVIRONMENT_BLOCKED_FFMPEG_NOT_FOUND"}))
        return 2
    with TemporaryDirectory(prefix="cutory-shot-eval-") as directory:
        root = Path(directory)
        fixtures = _fixtures(root, ffmpeg)
        results = []
        started = time.perf_counter()
        for name, path, duration, ground_truth in fixtures:
            call_started = time.perf_counter()
            detected = detect_shot_structure(
                path,
                source_video_id=SOURCE_ID,
                duration_seconds=duration,
                config=CONFIG,
                ffmpeg_executable=ffmpeg,
            )
            timestamps = tuple(item.timestamp_seconds for item in detected.boundaries)
            true_positive, errors = _match(ground_truth, timestamps)
            results.append(
                {
                    "fixture": name,
                    "duration_seconds": duration,
                    "ground_truth": ground_truth,
                    "detected": timestamps,
                    "true_positives": true_positive,
                    "false_positives": len(timestamps) - true_positive,
                    "false_negatives": len(ground_truth) - true_positive,
                    "absolute_errors": errors,
                    "runtime_seconds": time.perf_counter() - call_started,
                }
            )
        runtime = time.perf_counter() - started
    tp = sum(item["true_positives"] for item in results)
    fp = sum(item["false_positives"] for item in results)
    fn = sum(item["false_negatives"] for item in results)
    precision = tp / (tp + fp) if tp + fp else 1.0
    recall = tp / (tp + fn) if tp + fn else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    total_duration = sum(item["duration_seconds"] for item in results)
    report = {
        "status": "COMPLETED",
        "dataset_type": "SYNTHETIC_SHOT_FOCUSED",
        "fixtures": len(results),
        "threshold_percent": CONFIG.threshold_percent,
        "minimum_shot_duration_seconds": CONFIG.minimum_shot_duration_seconds,
        "tolerance_seconds": TOLERANCE_SECONDS,
        "ground_truth_boundaries": tp + fn,
        "detected_boundaries": tp + fp,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "mean_absolute_error_seconds": (
            sum(error for item in results for error in item["absolute_errors"]) / tp
            if tp
            else None
        ),
        "runtime_seconds": runtime,
        "runtime_per_source_minute_seconds": runtime / (total_duration / 60),
        "llm_calls": 0,
        "vlm_calls": 0,
        "results": results,
    }
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


def _fixtures(root: Path, ffmpeg: str):
    fixtures = []
    fixtures.append(("single_static", _solid(root, ffmpeg, "single", ("black",), 4), 4.0, ()))
    fixtures.append(("hard_cut", _solid(root, ffmpeg, "hard", ("black", "white"), 2), 4.0, (2.0,)))
    fixtures.append(("multiple_hard_cuts", _solid(root, ffmpeg, "multi", ("black", "white", "red", "blue"), 1), 4.0, (1.0, 2.0, 3.0)))
    motion = root / "continuous-motion.mp4"
    _run(
        [ffmpeg, "-v", "error", "-nostdin", "-f", "lavfi", "-i", "testsrc2=duration=4:size=160x90:rate=20", "-pix_fmt", "yuv420p", "-y", str(motion)]
    )
    fixtures.append(("continuous_motion", motion, 4.0, ()))
    return tuple(fixtures)


def _solid(root: Path, ffmpeg: str, name: str, colors: tuple[str, ...], segment_duration: int) -> Path:
    output = root / f"{name}.mp4"
    command = [ffmpeg, "-v", "error", "-nostdin"]
    for color in colors:
        command.extend(["-f", "lavfi", "-i", f"color=c={color}:s=160x90:d={segment_duration}:r=20"])
    if len(colors) > 1:
        inputs = "".join(f"[{index}:v]" for index in range(len(colors)))
        command.extend(["-filter_complex", f"{inputs}concat=n={len(colors)}:v=1:a=0[out]", "-map", "[out]"])
    command.extend(["-pix_fmt", "yuv420p", "-y", str(output)])
    _run(command)
    return output


def _run(command: list[str]) -> None:
    completed = subprocess.run(command, capture_output=True, check=False, timeout=60)
    if completed.returncode != 0:
        raise RuntimeError("Synthetic FFmpeg fixture generation failed.")


def _match(expected: tuple[float, ...], actual: tuple[float, ...]) -> tuple[int, tuple[float, ...]]:
    unused = set(range(len(actual)))
    errors = []
    for boundary in expected:
        matches = sorted(
            ((abs(boundary - actual[index]), index) for index in unused),
            key=lambda item: (item[0], item[1]),
        )
        if matches and matches[0][0] <= TOLERANCE_SECONDS:
            error, index = matches[0]
            unused.remove(index)
            errors.append(error)
    return len(errors), tuple(errors)


if __name__ == "__main__":
    raise SystemExit(main())
