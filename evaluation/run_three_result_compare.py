"""TODO 31: compare three edits of the same day (my own edit, Cutory, another app) by where they came from in the sources.

Each result is matched to the project's sources with the TODO 29 matcher (my_edit_compare). Portrait results are read
as their middle 16:9 band only. Outputs numbers (result.json) and one picture from the middle of every cut (for
reading the captions by eye) into ``--out``. Reads the database only; no AI, no paid call.

    python evaluation/run_three_result_compare.py --project <id> --out <folder> \
        --result 기준본=<file> --result Cutory=<file> --result "블로=<file>@band"
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from backend.app.services import my_edit_compare as mec  # noqa: E402

FILMED = re.compile(r"_(\d{14})_")
BACKWARD_SECONDS = 30.0  # a cut that starts this far before the previous one (in day time) goes back in the day
NEAR_SECONDS = 3.0  # two results "used the same moment" when their source spans come this close


def filmed_at(filename: str) -> datetime | None:
    found = FILMED.search(filename)
    return datetime.strptime(found.group(1), "%Y%m%d%H%M%S") if found else None


def load_inputs(project_id: UUID) -> mec.Inputs:
    from backend.app.config import DatabaseSettings, load_environment
    from backend.app.database import create_database_engine, create_session_factory
    from backend.app.storage.source_storage import LocalSourceStorage

    load_environment()
    factory = create_session_factory(create_database_engine(DatabaseSettings.from_environment()))
    storage = LocalSourceStorage(REPO / "storage" / "originals")
    with factory() as session:  # reads only
        return mec.build_inputs(session, storage, REPO / "outputs" / "projects", project_id, "")


def expand(spans, margin):
    return mec._merge([(a - margin, b + margin) for a, b in spans])


def analyse(name: str, video: Path, band: bool, inputs: mec.Inputs, prints: dict, out: Path, ffmpeg: str) -> dict:
    cache = out / "prints" / f"{name}.npz"
    edit = mec.source_frames(video, cache, ffmpeg, fps=mec.EDIT_FPS, crop=mec.CENTER_BAND if band else None)
    order = sorted(prints)
    matches = mec.match_frames(edit, [prints[index] for index in order])
    matches = [mec.FrameMatch(order[m.source], m.time, m.score, m.flat) if m.source is not None else m
               for m in matches]
    cuts, gaps = mec.build_cuts(list(edit.times), matches)
    duration = float(edit.times[-1] + 1 / mec.EDIT_FPS) if len(edit.times) else 0.0
    day_start, position = [], 0.0
    for source in inputs.sources:
        day_start.append(position)
        position += max(source.duration, 0.0)
    rows = []
    for number, cut in enumerate(cuts, start=1):
        source = inputs.sources[cut.source]
        filmed = filmed_at(source.filename)
        clock = (filmed + timedelta(seconds=cut.source_start)).strftime("%H:%M:%S") if filmed else None
        rows.append({"number": number, "edit_start": cut.edit_start, "edit_end": cut.edit_end, "length": cut.length,
                     "source_number": source.number, "source_filename": source.filename,
                     "source_start": cut.source_start, "source_end": cut.source_end,
                     "day_start": round(day_start[cut.source] + cut.source_start, 2),
                     "day_end": round(day_start[cut.source] + cut.source_end, 2), "clock": clock, "score": cut.score})
    backward = [{"from_cut": rows[i - 1]["number"], "to_cut": rows[i]["number"], "from_clock": rows[i - 1]["clock"],
                 "to_clock": rows[i]["clock"]}
                for i in range(1, len(rows)) if rows[i]["day_start"] < rows[i - 1]["day_start"] - BACKWARD_SECONDS]
    found = sum(cut.length for cut in cuts)
    lengths = [cut.length for cut in cuts]
    frames_dir = out / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:  # one picture from the middle of each cut, for reading captions by eye
        middle = (row["edit_start"] + row["edit_end"]) / 2
        target = frames_dir / f"{row['number']:02d}.jpg"
        if not target.exists():
            subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{middle:.2f}", "-i",
                            str(video), "-frames:v", "1", "-vf", "scale=540:-2", "-q:v", "4", str(target)],
                           check=False, timeout=120)
    return {
        "name": name, "file": video.name, "duration": round(duration, 1), "band_only": band,
        "cut_count": len(cuts), "median_cut": round(statistics.median(lengths), 2) if lengths else 0.0,
        "found_seconds": round(found, 1), "found_ratio": round(found / duration, 3) if duration else 0.0,
        "not_found": [{"edit_start": g.edit_start, "edit_end": g.edit_end} for g in gaps],
        "not_found_seconds": round(sum(g.edit_end - g.edit_start for g in gaps), 1),
        "sources_used": sorted({row["source_number"] for row in rows}),
        "backward_jumps": backward, "transitions": max(len(rows) - 1, 0),
        "day_spans": mec._merge([(row["day_start"], row["day_end"]) for row in rows]),
        "cuts": rows,
    }


def pairwise(results: list[dict]) -> list[dict]:
    out = []
    for i, a in enumerate(results):
        for b in results[i + 1:]:
            exact = mec._overlap(a["day_spans"], b["day_spans"])
            a_total = sum(end - start for start, end in a["day_spans"])  # source seconds used (repeats once)
            b_total = sum(end - start for start, end in b["day_spans"])
            near_a = mec._overlap(a["day_spans"], expand(b["day_spans"], NEAR_SECONDS))
            near_b = mec._overlap(b["day_spans"], expand(a["day_spans"], NEAR_SECONDS))
            shared_sources = sorted(set(a["sources_used"]) & set(b["sources_used"]))
            out.append({"a": a["name"], "b": b["name"], "same_seconds": round(exact, 1),
                        "a_near_ratio": round(near_a / a_total, 3) if a_total else 0.0,
                        "b_near_ratio": round(near_b / b_total, 3) if b_total else 0.0,
                        "shared_sources": shared_sources})
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=UUID, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--result", action="append", required=True, help="name=path[@band]")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    inputs = load_inputs(args.project)
    prints_dir = REPO / "outputs" / "projects" / str(args.project) / "my_edit" / "prints"  # TODO 29's, reused
    prints = {}
    for index, source in enumerate(inputs.sources):
        if source.path is None or not source.path.is_file():
            continue
        try:
            prints[index] = mec.source_frames(source.path, prints_dir / f"{source.source_id.hex}.npz", args.ffmpeg)
        except mec.MyEditError:
            print(f"skip unreadable source {source.filename}", flush=True)
    results = []
    for item in args.result:
        name, _, rest = item.partition("=")
        path, _, flag = rest.partition("@")
        started = datetime.now()
        result = analyse(name, Path(path), flag == "band", inputs, prints, args.out, args.ffmpeg)
        result["seconds_taken"] = round((datetime.now() - started).total_seconds(), 1)
        results.append(result)
        print(f"{name}: {result['cut_count']} cuts, found {result['found_ratio']:.0%}, "
              f"{len(result['backward_jumps'])} backward, {result['seconds_taken']}s", flush=True)
    day = [{"number": s.number, "filename": s.filename, "duration": round(s.duration, 2),
            "filmed": (filmed_at(s.filename).strftime("%H:%M:%S") if filmed_at(s.filename) else None)}
           for s in inputs.sources]
    plan = {"cut_count": len(inputs.plan), "seconds": round(sum(c.length for c in inputs.plan), 1)}
    data = {"made_at": datetime.now().isoformat(timespec="seconds"), "sources": day, "cutory_plan": plan,
            "results": results, "pairs": pairwise(results)}
    (args.out / "result.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    for pair in data["pairs"]:
        print(pair, flush=True)


if __name__ == "__main__":
    main()
