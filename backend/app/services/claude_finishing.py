"""TODO 41: Claude finishes the cuts Cutory picked — looks at pictures and speech, fills in TODO 40's effects.

Cutory picks the scenes (free, local); Claude only decorates them: zoom, a reaction word, a bracket narration, a
sound effect at the funny moment of a cut, plus hook titles. Every cut goes with three pictures (start, middle, end)
and its speech, next to my rules, my taste brief and the numbers measured from a video I like (TODO 33).

41-1 (this file so far): build what would be sent and estimate the bill. Nothing is called and nothing is saved.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Sequence
from uuid import UUID

from backend.app.services import cut_effects, edit_brain, sound_effects

MODEL_DEFAULT = "claude-sonnet-5-5"  # picking the funny moment needs judgement (same choice as taste scores)
PICTURE_WIDTH = 480  # big enough to see a face (320 was enough for "is it me / shaky")
PICTURES_PER_CUT = 3
PICTURE_SPOTS = (0.15, 0.5, 0.85)  # share of the cut where each picture is taken
IMAGE_TOKENS = 173  # a 480x270 picture is about (480 x 270) / 750 tokens
CHUNK_CUTS = 33  # a request carries at most 100 pictures: 33 cuts x 3
CHARS_PER_TOKEN = 1.0  # Korean is about one token per character (measured in TODO 32-4)
OUT_PER_CUT = 80  # effects + seconds + one-line reason, as JSON
OUT_PER_CHUNK = 300  # hook titles and the wrapper
THINK_PER_CUT = 150  # extra output when Claude thinks before answering (upper end of the estimate)
SPEECH_LIMIT = 200

SYSTEM = (
    "너는 이 사용자의 브이로그를 마무리 손질하는 편집자다. 컷은 이미 골라져 있고 순서도 정해져 있다. "
    "너의 일은 컷을 바꾸지 않고 꾸미는 것뿐이다: 웃긴 순간·펀치라인·리액션이 큰 순간을 찾아 확대, 리액션 큰 글자, "
    "괄호 내레이션, 효과음을 넣는다. 모든 컷에 넣지 말고 살릴 만한 순간에만 넣어라(아무것도 안 넣는 컷이 더 많아도 된다). "
    "컷마다 사진 3장(컷의 앞·가운데·뒤)과 대사가 온다. 사진이 장면 설명보다 정확하니 사진을 믿어라. "
    "[나]는 사용자 목소리, [남]은 다른 사람 목소리다(자동 구분이라 틀릴 수 있다). "
    "사용자의 규칙과 취향 글이 가장 중요한 기준이고, 좋아하는 영상에서 잰 숫자는 글자 길이·빈도의 기준이다. "
    "이미 사용자가 넣은 효과가 있는 컷은 그대로 두라. 이유는 한국어 25자 이내로 쓴다."
)


@dataclass(frozen=True)
class CutRow:
    number: int  # 1-based, as on the edit room's cut strip
    candidate_id: UUID
    source_video_id: UUID
    start: float  # seconds in the source video
    end: float
    speech: str  # "[나] ... / [남] ..."
    caption: str
    existing: str  # effects I already put in, "" when none

    @property
    def length(self) -> float:
        return round(self.end - self.start, 1)

    def line(self) -> str:
        mine = f" | 이미 넣은 효과(그대로 둘 것): {self.existing}" if self.existing else ""
        return (f"{self.number}번 컷 길이 {self.length}초 | 대사: {self.speech or '(없음)'}"
                f" | 화면 설명: {self.caption or '(없음)'}{mine}")


def picture_times(row: CutRow) -> tuple[float, ...]:
    """Source seconds of the three pictures of a cut."""
    return tuple(round(row.start + (row.end - row.start) * spot, 3) for spot in PICTURE_SPOTS)


def speech_text(lines, start: float, end: float, limit: int = SPEECH_LIMIT) -> str:
    marks = {"me": "나", "other": "남"}
    parts = [f"[{marks.get(line.speaker or '', '?')}] {line.text}" for line in lines
             if line.end > start and line.start < end]
    text = " / ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def existing_effects(effects: dict, candidate_id: UUID) -> str:
    parts = []
    zoom = cut_effects.zoom_of(effects, candidate_id)
    if zoom:
        parts.append(cut_effects.ZOOM_LABELS[zoom])
    parts += [f"글자 {cut_effects.text_label(item)}" for item in cut_effects.texts_of(effects, candidate_id)]
    parts += [f"효과음 {item['name']}" for item in cut_effects.sounds_of(effects, candidate_id)]
    return ", ".join(parts)


def cut_rows(inputs, effects: dict) -> list[CutRow]:
    """inputs: longform_chat.ChatInputs (the saved edit plan)."""
    rows = []
    for number, cut in enumerate(inputs.cuts, start=1):
        scene = inputs.scenes[cut.candidate_id]
        rows.append(CutRow(number, cut.candidate_id, scene.source_video_id, cut.start, cut.end,
                           speech_text(inputs.lines.get(scene.source_video_id, ()), cut.start, cut.end),
                           (scene.caption or "").strip(), existing_effects(effects, cut.candidate_id)))
    return rows


def reference_lines(result: dict | None) -> list[str]:
    """TODO 33 numbers measured from a video I like (outputs/me/reference/result.json)."""
    if not result:
        return []
    lines = []
    stats = result.get("stats") or {}
    if stats.get("median_cut"):
        lines.append(f"한 컷 가운데 값 {stats['median_cut']}초 (컷 {stats.get('cut_count', '?')}개, 1분에 {stats.get('cuts_per_minute', '?')}컷)")
    captions = (result.get("captions") or {}).get("stats") or {}
    if captions.get("median_gap"):
        lines.append(f"자막(화면 글자)은 {captions['median_gap']}초쯤마다 바뀜")
    if captions.get("median_chars"):
        lines.append(f"자막 한 번에 {captions['median_chars']}자 안팎")
    zones = captions.get("zone_share") or {}
    if zones:
        where, share = max(zones.items(), key=lambda item: item[1])
        lines.append(f"자막 위치는 화면 {where} {round(share * 100)}%")
    return lines


def effects_menu() -> str:
    return (
        "넣을 수 있는 효과(컷마다 글자 최대 {texts}개, 효과음 최대 {sounds}개, at은 컷 시작부터 몇 초):\n"
        "- zoom: \"zoom\"(컷 전체 {scale}배 확대, 얼굴 쪽) 또는 \"push\"(컷 동안 천천히 다가감) 또는 null\n"
        "- 리액션 큰 글자(kind \"react\"): 노란 큰 글씨가 1.2초 튀어나옴. 짧게(예: 의성어·감탄 한두 단어), 최대 {chars}자\n"
        "- 괄호 내레이션(kind \"narr\"): 화면 아래쪽에 \"(근데 갑자기)\"처럼 속마음·상황 설명, 그 시각부터 컷 끝까지. 괄호는 빼고 안쪽 글만\n"
        "- 효과음: {names} 중 하나"
    ).format(texts=cut_effects.MAX_TEXTS, sounds=cut_effects.MAX_SOUNDS, scale=cut_effects.ZOOM_SCALE,
             chars=cut_effects.MAX_TEXT_CHARS, names="·".join(sound_effects.NAMES))


def header_text(rules: Sequence[str], brief: str, reference: Sequence[str]) -> str:
    """Everything except the cuts: sent again with every chunk of pictures."""
    parts = ["내 규칙:\n" + ("\n".join(f"- {text}" for text in rules) if rules else "(없음)"),
             f"내 편집 취향(사용자가 직접 씀):\n{brief.strip() or '(없음)'}",
             "좋아하는 영상에서 잰 숫자:\n" + ("\n".join(f"- {text}" for text in reference) if reference else "(없음)"),
             effects_menu()]
    return "\n\n".join(parts)


@dataclass(frozen=True)
class Estimate:
    cuts: int
    pictures: int
    chunks: int
    input_tokens: int
    output_tokens: int  # without thinking
    output_tokens_high: int  # with thinking
    usd_low: float
    usd_high: float


def estimate(model: str, header: str, rows: Sequence[CutRow], pictures: int | None = None) -> Estimate:
    count = len(rows)
    pictures = PICTURES_PER_CUT * count if pictures is None else pictures
    chunks = max(1, -(-count // CHUNK_CUTS))
    text = len(SYSTEM) * chunks + len(header) * chunks + sum(len(row.line()) for row in rows)
    input_tokens = int(text / CHARS_PER_TOKEN) + pictures * IMAGE_TOKENS
    output_low = OUT_PER_CUT * count + OUT_PER_CHUNK * chunks
    output_high = output_low + THINK_PER_CUT * count
    return Estimate(count, pictures, chunks, input_tokens, output_low, output_high,
                    round(edit_brain.cost_usd(model, input_tokens, output_low), 4),
                    round(edit_brain.cost_usd(model, input_tokens, output_high), 4))


def model_name() -> str:
    return os.environ.get("CUTORY_FINISH_MODEL") or MODEL_DEFAULT
