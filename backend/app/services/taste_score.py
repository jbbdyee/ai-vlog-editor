"""TODO 32-4: score every scene by my taste — my own written description plus scenes my own edit kept or left out.

Why: the voice marks alone do not tell my choices apart (학원 하루: I kept 33~40% of every voice kind). What I keep
depends on what is said and shown, so an AI reads each scene (speech with 나/남 marks, the screen description, time of
day, length) next to my description and examples, and gives 0~3. Length fitting then leaves out low scores first.

Kept/left out comes from "내 편집과 비교" (TODO 29): a scene is kept when my edit used its source within MARGIN s.
Files: my description outputs/me/taste_brief.txt (all projects), scores outputs/projects/<id>/taste_scores.json.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Sequence
from uuid import UUID

MARGIN = 1.5
BRIEF_MAX_CHARS = 6000
CHARS_PER_TOKEN = 1.0  # Claude counts Korean about one token per character (학원 하루: 19,316 tokens, estimate at 1.5 was 12,821)
FILMED = re.compile(r"_(\d{14})_")

SYSTEM = (
    "너는 이 사용자의 브이로그 편집 취향을 아는 편집 조수다. 사용자가 직접 쓴 '내 편집 취향'이 가장 중요한 기준이다. "
    "'내 편집에서 남김/뺌' 표시가 붙은 장면은 사용자가 실제로 고른 예시이니, 설명과 함께 어떤 장면을 남기는지 파악하라. "
    "그다음 '점수 매길 장면'마다 이 사용자가 완성 영상에 남길 가능성을 0~3점으로 매겨라. "
    "3=꼭 남김, 2=남기면 좋음, 1=짧게 넣거나 빼도 됨, 0=빼야 함. why는 한국어 20자 이내로 핵심 이유만. "
    "[나]는 사용자 목소리, [남]은 다른 사람 목소리다(자동 구분이라 틀릴 수 있음). 화면 설명도 자동으로 만든 것이라 부정확할 수 있다."
)
# TODO 32-4b: with pictures, what is seen outranks the written screen description.
VISION_RULE = (
    " 장면마다 그 장면의 사진 2장(앞쪽·뒤쪽)이 함께 온다. 사진이 화면 설명보다 정확하니 사진을 믿어라. "
    "사진에서 사용자(영상 주인, 대부분의 장면에 나오는 여성)가 나오는지, 옆모습인지, 살짝 미소인지 크게 웃는지, "
    "아래에서 올려 찍었는지, 화면이 흔들리거나 하늘을 찍었는지, 사용자 없이 다른 사람만 나오는지를 보고 취향에 맞춰 판단하라."
)
CHUNK_SCENES = 40  # a request carries at most 100 pictures: 40 scenes x 2
IMAGE_TOKENS = 80  # a 320x180 picture is about (320 x 180) / 750 tokens


@dataclass(frozen=True)
class SceneRow:
    candidate_id: UUID
    source_video_id: UUID
    start: float
    end: float
    clock: str  # time of day it was filmed, "" when unknown
    speech: str  # "[나] ... / [남] ..."
    caption: str

    @property
    def seconds(self) -> float:
        return round(self.end - self.start, 1)

    def line(self, number: int, label: str = "") -> str:
        mark = f" | 내 편집에서 {label}" if label else ""
        return (f"{number}. {self.clock or '시각 모름'} 길이 {self.seconds}초 | 대사: {self.speech or '(없음)'}"
                f" | 화면: {self.caption or '(없음)'}{mark}")


def filmed_clock(filename: str, offset: float) -> str:
    found = FILMED.search(filename or "")
    if not found:
        return ""
    try:
        start = datetime.strptime(found.group(1), "%Y%m%d%H%M%S")
    except ValueError:
        return ""
    return (start + timedelta(seconds=offset)).strftime("%H:%M")


def speech_text(lines, start: float, end: float, limit: int = 160) -> str:
    parts = [f"[{'나' if line.speaker == 'me' else '남'}] {line.text}" for line in lines
             if line.end > start and line.start < end]
    text = " / ".join(parts)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def kept_by_my_edit(rows: Sequence[SceneRow], my_cuts: Sequence[dict]) -> dict[UUID, bool]:
    """Scene -> True when my own edit used its source (within MARGIN s). my_cuts: TODO 29 result.json 'cuts'."""
    spans: dict[str, list[tuple[float, float]]] = {}
    for cut in my_cuts:
        if cut.get("source_id"):
            spans.setdefault(str(cut["source_id"]), []).append((float(cut["source_start"]), float(cut["source_end"])))
    return {row.candidate_id: any(end > row.start - MARGIN and start < row.end + MARGIN
                                  for start, end in spans.get(str(row.source_video_id), ()))
            for row in rows}


def schema(count: int) -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["scores"], "properties": {"scores": {
        "type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["n", "score", "why"],
                                   "properties": {"n": {"type": "integer"},
                                                  "score": {"type": "integer", "enum": [0, 1, 2, 3]},
                                                  "why": {"type": "string"}}}}}}


def build_request(brief: str, examples: Sequence[tuple[SceneRow, bool]], rows: Sequence[SceneRow]) -> tuple[str, str]:
    parts = [f"내 편집 취향(사용자가 직접 씀):\n{brief.strip() or '(아직 없음)'}"]
    if examples:
        parts.append("내 편집에서 남김/뺌 예시:\n" + "\n".join(
            row.line(index, "남김" if kept else "뺌") for index, (row, kept) in enumerate(examples, start=1)))
    parts.append(f"점수 매길 장면(번호 1~{len(rows)}, 모두 빠짐없이):\n"
                 + "\n".join(row.line(index) for index, row in enumerate(rows, start=1)))
    return SYSTEM, "\n\n".join(parts)


def estimate_tokens(system: str, user: str, count: int, pictures: int = 0) -> tuple[int, int]:
    """(input, output) tokens, roughly: the request text (+ the header again for every extra chunk of pictures),
    the pictures, and ~25 tokens per scored scene."""
    chunks = max(1, -(-count // CHUNK_SCENES)) if pictures else 1
    header = len(system) + len(user.split("점수 매길 장면")[0])
    text = len(system) + len(user) + header * (chunks - 1)
    return int(text / CHARS_PER_TOKEN) + pictures * IMAGE_TOKENS, 25 * count + 200 * chunks


def picture_times(row: "SceneRow") -> tuple[float, float]:
    """Two moments inside the scene (a third and two thirds in), so a shaky or turning shot shows."""
    length = row.end - row.start
    return round(row.start + length / 3, 3), round(row.start + length * 2 / 3, 3)


def _image_block(path: Path) -> dict:
    import base64
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(Path(path).read_bytes()).decode("ascii")}}


def score_with_pictures(brief: str, examples: Sequence[tuple[SceneRow, bool]], rows: Sequence[SceneRow],
                        pictures: dict[UUID, Sequence[Path]], ask: "AskBlocks"
                        ) -> tuple[dict[UUID, tuple[int, str]], int, int]:
    """Like score(), but every scene comes with its pictures; sent CHUNK_SCENES scenes at a time."""
    system = SYSTEM + VISION_RULE
    _, request_text = build_request(brief, examples, [])
    header_text = request_text.split("점수 매길 장면")[0].strip()  # my description + examples, sent with every chunk
    scores: dict[UUID, tuple[int, str]] = {}
    used_in = used_out = 0
    for first in range(0, len(rows), CHUNK_SCENES):
        chunk = rows[first:first + CHUNK_SCENES]
        blocks: list[dict] = [{"type": "text", "text": f"{header_text}\n\n점수 매길 장면(번호 1~{len(chunk)}, 모두 빠짐없이):"}]
        for number, row in enumerate(chunk, start=1):
            blocks.append({"type": "text", "text": row.line(number)})
            blocks.extend(_image_block(path) for path in pictures.get(row.candidate_id, ()))
        text, input_tokens, output_tokens = ask(system, blocks, schema(len(chunk)))
        used_in, used_out = used_in + input_tokens, used_out + output_tokens
        for item in json.loads(text).get("scores", []):
            number = item.get("n")
            if isinstance(number, int) and 1 <= number <= len(chunk) and item.get("score") in (0, 1, 2, 3):
                scores[chunk[number - 1].candidate_id] = (int(item["score"]), str(item.get("why") or "")[:60])
    return scores, used_in, used_out


Ask = Callable[[str, str, dict], tuple[str, int, int]]  # (system, user, schema) -> (json text, in, out tokens)
AskBlocks = Callable[[str, list, dict], tuple[str, int, int]]  # user = content blocks (text + pictures)


def score(brief: str, examples: Sequence[tuple[SceneRow, bool]], rows: Sequence[SceneRow], ask: Ask
          ) -> tuple[dict[UUID, tuple[int, str]], int, int]:
    system, user = build_request(brief, examples, rows)
    text, input_tokens, output_tokens = ask(system, user, schema(len(rows)))
    scores: dict[UUID, tuple[int, str]] = {}
    for item in json.loads(text).get("scores", []):
        number = item.get("n")
        if isinstance(number, int) and 1 <= number <= len(rows) and item.get("score") in (0, 1, 2, 3):
            scores[rows[number - 1].candidate_id] = (int(item["score"]), str(item.get("why") or "")[:60])
    return scores, input_tokens, output_tokens


# ---- files --------------------------------------------------------------------------------------------------------

def brief_path(output_root: Path) -> Path:
    """outputs/projects -> outputs/me/taste_brief.txt (next to edit_rules.json)"""
    return Path(output_root).parent / "me" / "taste_brief.txt"


def load_brief(output_root: Path) -> str:
    try:
        return brief_path(output_root).read_text(encoding="utf-8")
    except OSError:
        return ""


def save_brief(output_root: Path, text: str) -> str:
    text = (text or "").strip()[:BRIEF_MAX_CHARS]
    path = brief_path(output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return text


def scores_path(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "taste_scores.json"


def save_scores(output_root: Path, project_id: UUID, scores: dict[UUID, tuple[int, str]], *, model: str,
                input_tokens: int, output_tokens: int, usd: float, examples: int) -> None:
    path = scores_path(output_root, project_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "made_at": datetime.now(timezone.utc).isoformat(), "model": model, "examples": examples,
        "input_tokens": input_tokens, "output_tokens": output_tokens, "usd": round(usd, 5),
        "scores": {str(key): {"score": value, "why": why} for key, (value, why) in scores.items()},
    }, ensure_ascii=False), encoding="utf-8")


def load_scores(output_root: Path, project_id: UUID) -> dict[UUID, tuple[int, str]]:
    try:
        raw = json.loads(scores_path(output_root, project_id).read_text(encoding="utf-8"))
        return {UUID(key): (int(item["score"]), str(item.get("why") or "")) for key, item in raw["scores"].items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def project_rows(session, output_root: Path, project_id: UUID) -> list[SceneRow]:
    """Every active scene of a project in filming order, with speech (나/남) and the screen description."""
    from backend.app.services import longform_chat  # local: longform_chat imports a lot

    inputs = longform_chat.load_inputs(session, output_root, project_id)
    rows = []
    for scene in inputs.scenes.values():
        rows.append(SceneRow(scene.candidate_id, scene.source_video_id, scene.found_start, scene.found_end,
                             filmed_clock(scene.filename, scene.found_start),
                             speech_text(inputs.lines.get(scene.source_video_id, ()), scene.found_start, scene.found_end),
                             (scene.caption or "")[:120]))
    rows.sort(key=lambda row: (row.clock or "99", row.start))
    return rows
