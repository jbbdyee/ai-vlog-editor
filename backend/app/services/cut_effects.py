"""TODO 40: effects on each cut of the finished video ("이 컷 확대", "여기 천천히 줌").

Effects live in ``outputs/projects/<id>/cut_effects.json`` next to the chat file (no database change), keyed by the
cut's scene id, so undo, moving cuts and "추천으로 다시 만들기" keep a scene's effect while that scene is used.
The edit-room chat reads effect sentences by rules (no AI), and the project render adds one video filter per cut.

40-1: zoom only. ``zoom`` = a fixed 1.35x close-up around the upper middle (where faces usually are),
``push`` = a slow push-in from 1.0x to 1.15x over the cut.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal, Mapping, Sequence
from uuid import UUID

Zoom = Literal["zoom", "push"]
ZOOMS: tuple[str, ...] = ("zoom", "push")
ZOOM_SCALE = 1.35
ZOOM_CENTER_Y = 0.4  # share of the frame height the close-up centres on (faces sit above the middle)
PUSH_END_SCALE = 1.15
ZOOM_LABELS = {"zoom": "확대", "push": "천천히 줌"}


# --- file ------------------------------------------------------------------------------------------------------------

def _path(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "cut_effects.json"


def load_effects(output_root: Path, project_id: UUID) -> dict[str, dict]:
    """``{candidate_id: {"zoom": "zoom" | "push"}}``; a missing or odd file means no effects."""
    try:
        data = json.loads(_path(output_root, project_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    cuts = data.get("cuts") if isinstance(data, dict) else None
    if not isinstance(cuts, dict):
        return {}
    out = {}
    for key, value in cuts.items():
        if isinstance(value, dict) and value.get("zoom") in ZOOMS:
            out[str(key)] = {"zoom": value["zoom"]}
    return out


def save_effects(output_root: Path, project_id: UUID, effects: Mapping[str, dict]) -> None:
    path = _path(output_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    kept = {key: dict(value) for key, value in effects.items() if value}
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"cuts": kept}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def set_zoom(effects: Mapping[str, dict], candidate_id: UUID, zoom: str | None) -> dict[str, dict]:
    out = {key: dict(value) for key, value in effects.items()}
    entry = out.setdefault(str(candidate_id), {})
    if zoom is None:
        entry.pop("zoom", None)
    else:
        entry["zoom"] = zoom
    if not entry:
        out.pop(str(candidate_id))
    return out


def zoom_of(effects: Mapping[str, dict], candidate_id: UUID) -> str | None:
    return (effects.get(str(candidate_id)) or {}).get("zoom")


def for_cuts(output_root: Path, project_id: UUID, candidate_ids: Sequence[UUID]) -> list[dict | None]:
    effects = load_effects(output_root, project_id)
    return [effects.get(str(candidate_id)) for candidate_id in candidate_ids]


# --- chat sentence ---------------------------------------------------------------------------------------------------

_STAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}\]\s*")
_ZOOM_WORD = re.compile(r"확대|줌|클로즈\s*업|zoom", re.IGNORECASE)
_PUSH_WORD = re.compile(r"천천히|서서히|점점|밀고|푸시|push", re.IGNORECASE)
_OFF_WORD = re.compile(r"빼|삭제|지워|지우|없애|취소|그만|원래\s*대로|말고")


def zoom_request(message: str, here: int | None) -> tuple[int | None, str | None] | Literal[False]:
    """"3번 확대" -> (3, "zoom"), "여기 천천히 줌" -> (here, "push"), "확대 빼" -> (here, None).
    False when the sentence is not about zoom (it goes on to the plan edits)."""
    text = _STAMP.sub("", message).strip()
    if not _ZOOM_WORD.search(text):
        return False
    number = re.search(r"(\d+)\s*번", text)
    target = int(number.group(1)) if number else here
    if _OFF_WORD.search(text):
        return target, None
    return target, "push" if _PUSH_WORD.search(text) else "zoom"


# --- render filter ---------------------------------------------------------------------------------------------------

def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def video_filter(effect: Mapping | None, width: int, height: int, fps: int, seconds: float) -> str:
    """Extra filters for one cut, run on the already scaled/padded ``width`` x ``height`` frame (keeps frame count)."""
    zoom = (effect or {}).get("zoom")
    if zoom == "zoom":
        crop_w, crop_h = _even(width / ZOOM_SCALE), _even(height / ZOOM_SCALE)
        x = (width - crop_w) // 2
        y = int(min(max(height * ZOOM_CENTER_Y - crop_h / 2, 0), height - crop_h))
        return f",crop={crop_w}:{crop_h}:{x}:{y},scale={width}:{height}:flags=lanczos,setsar=1"
    if zoom == "push":
        frames = max(1, int(round(seconds * fps)))
        # Worked at twice the size so the slow zoom does not wobble.
        return (f",scale={2 * width}:{2 * height}:flags=lanczos,"
                f"zoompan=z='1+{PUSH_END_SCALE - 1:.2f}*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                f"d=1:s={width}x{height}:fps={fps},setsar=1")
    return ""
