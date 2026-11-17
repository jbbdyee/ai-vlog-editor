"""TODO 28: what the user chose in the chat ("내 선택 기록") and rule candidates found in it.

Every chat change (a picked picture, [그대로 두기], a removed / shortened / lengthened / inserted cut) is written as
one line per scene, with plain tags from the scene's speech (다른 사람 목소리 / 내 목소리 / 말 없음). When the same
direction keeps coming back, a candidate sentence ("다른 사람 목소리가 나오는 장면(친구 수다)은 살린다") is offered;
it becomes a "내 규칙" (edit_rules) only when the user accepts it. Shared by every project, stored next to the rules in
``outputs/me/taste_log.json`` (no database change, no AI).
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence
from uuid import uuid4

MAX_EVENTS = 500
MIN_COUNT = 3  # the same direction at least this many times
RATIO = 3  # ... and at least this many times the other direction
# A picture shown but not picked ("passed") is recorded but not counted: the pictures are usually the same kind of
# scene as the one picked, so passing them says little about taste.
LONG_MIN_CUT = 2.0

# how -> direction ("keep" | "drop" | "pass")
_KEEP = {"picked", "kept", "inserted", "longer"}
_DROP = {"removed", "replaced", "shortened"}
_HOW_LABEL = {"picked": "사진에서 고름", "kept": "그대로 두기", "inserted": "넣음", "longer": "늘림",
              "removed": "뺌", "replaced": "다른 장면으로 바꿈", "shortened": "줄임", "passed": "사진에서 안 고름"}

TAG_TEXT = {
    "other_voice": ("다른 사람 목소리가 나오는 장면(친구 수다)은 살린다", "다른 사람 목소리가 나오는 장면(친구 수다)은 줄이거나 뺀다",
                    "다른 사람 목소리가 나오는 장면"),
    "my_voice": ("내가 말하는 장면은 살린다", "내가 말하는 장면은 줄이거나 뺀다", "내가 말하는 장면"),
    "talk": ("대화가 있는 장면은 살린다", "대화가 있는 장면은 줄이거나 뺀다", "대화가 있는 장면"),
    "quiet": ("말 없는 분위기 장면도 살린다", "말 없는 장면은 뺀다", "말 없는 장면"),
}


def _path(project_output_root: Path) -> Path:
    """outputs/projects -> outputs/me/taste_log.json (next to edit_rules.json)"""
    return Path(project_output_root).parent / "me" / "taste_log.json"


def load_log(project_output_root: Path) -> dict:
    try:
        data = json.loads(_path(project_output_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    if not isinstance(data.get("events"), list):
        data["events"] = []
    if not isinstance(data.get("answered"), dict):
        data["answered"] = {}
    return data


def _save(project_output_root: Path, data: dict) -> None:
    path = _path(project_output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data["events"] = data["events"][-MAX_EVENTS:]
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def scene_tags(lines: Iterable, start: float, end: float) -> list[str]:
    """Plain tags from the speech lines (objects with .start/.end/.speaker) that overlap start..end."""
    speakers = [line.speaker for line in lines if line.end > start + 0.05 and line.start < end - 0.05]
    if not speakers:
        return ["quiet"]
    tags = []
    if "other" in speakers:
        tags.append("other_voice")
    if "me" in speakers:
        tags.append("my_voice")
    return tags or ["talk"]  # speech, but the voice step was not run


@dataclass(frozen=True)
class Choice:
    """One scene the user acted on."""
    how: str  # picked | kept | inserted | longer | removed | replaced | shortened | passed
    candidate_id: str
    tags: tuple[str, ...]
    seconds: float  # the cut's length after the change (before, for removed / replaced / passed)
    from_seconds: float | None = None  # shortened / longer: the length before


def record(project_output_root: Path, project_id, mark: str | None, choices: Sequence[Choice]) -> None:
    """mark = the chat message the change belongs to, so 되돌리기 can take these lines back."""
    if not choices:
        return
    data = load_log(project_output_root)
    now = datetime.now(timezone.utc).isoformat()
    for choice in choices:
        data["events"].append({"id": uuid4().hex[:12], "project_id": str(project_id), "mark": mark, "at": now,
                               "how": choice.how, "candidate_id": choice.candidate_id, "tags": list(choice.tags),
                               "seconds": round(choice.seconds, 2),
                               "from_seconds": None if choice.from_seconds is None else round(choice.from_seconds, 2)})
    _save(project_output_root, data)


def mark_undone(project_output_root: Path, marks: Iterable[str]) -> None:
    marks = {mark for mark in marks if mark}
    if not marks:
        return
    data = load_log(project_output_root)
    hit = False
    for event in data["events"]:
        if event.get("mark") in marks and not event.get("undone"):
            event["undone"] = True
            hit = True
    if hit:
        _save(project_output_root, data)


@dataclass(frozen=True)
class Candidate:
    key: str
    text: str
    why: str


def _why(counts: dict[str, int], keep: bool, other: int, noun: str) -> str:
    detail = ", ".join(f"{_HOW_LABEL[how]} {count}" for how, count in sorted(counts.items(), key=lambda pair: -pair[1]))
    total = sum(counts.values())
    if keep:
        return f"{noun}을 {total}번 살렸고({detail}), 뺀 건 {other}번"
    return f"{noun}을 {total}번 뺐고({detail}), 살린 건 {other}번"


def candidates(project_output_root: Path, rule_texts: Sequence[str] = (), max_cut_rule: float | None = None) -> list[Candidate]:
    data = load_log(project_output_root)
    answered = data["answered"]
    rules = set(rule_texts)
    events = [event for event in data["events"] if not event.get("undone")]
    out: list[Candidate] = []
    for tag, (keep_text, drop_text, noun) in TAG_TEXT.items():
        keep_counts: dict[str, int] = {}
        drop_counts: dict[str, int] = {}
        for event in events:
            if tag not in (event.get("tags") or ()):
                continue
            how = event.get("how")
            if how in _KEEP:
                keep_counts[how] = keep_counts.get(how, 0) + 1
            elif how in _DROP:
                drop_counts[how] = drop_counts.get(how, 0) + 1
        keep = sum(keep_counts.values())
        drop = sum(drop_counts.values())
        if keep >= MIN_COUNT and keep >= RATIO * drop:
            key = f"{tag}:keep"
            if key not in answered and keep_text not in rules:
                out.append(Candidate(key, keep_text, _why(keep_counts, True, drop, noun)))
        elif drop >= MIN_COUNT and drop >= RATIO * keep:
            key = f"{tag}:drop"
            if key not in answered and drop_text not in rules:
                out.append(Candidate(key, drop_text, _why(drop_counts, False, keep, noun)))
    shortened = [event for event in events if event.get("how") == "shortened"]
    longer = sum(1 for event in events if event.get("how") == "longer")
    if len(shortened) >= MIN_COUNT and len(shortened) >= RATIO * longer and "max_cut" not in answered:
        limit = max(LONG_MIN_CUT, round(statistics.median(float(event["seconds"]) for event in shortened)))
        text = f"한 컷은 {limit:g}초 넘지 않게"
        if text not in rules and (max_cut_rule is None or limit < max_cut_rule):
            out.append(Candidate("max_cut", text, f"컷을 {len(shortened)}번 줄였고(줄인 뒤 길이 가운데 값 {limit:g}초), 늘린 건 {longer}번"))
    return out


def answer(project_output_root: Path, key: str, accepted: bool) -> None:
    data = load_log(project_output_root)
    data["answered"][key] = {"accepted": accepted, "at": datetime.now(timezone.utc).isoformat()}
    _save(project_output_root, data)
