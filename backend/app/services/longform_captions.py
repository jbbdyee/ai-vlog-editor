"""TODO 21: put what was said on the long-form video as captions, plus a small "inner thought" now and then.

Modelled on the user's channel (다요이어리): the spoken line sits at the bottom centre in bold white letters with a dark
outline, and every minute or so a short hand-written thought (a self-talk aside, not the line itself) sits a little
higher on the right.

The spoken lines come from the render's own SRT (speech recognition). The thoughts come from the local AI only
(Ollama); when it is off or answers badly, the video gets the spoken lines alone. Burning uses the same FFmpeg ``ass``
filter and fonts as the reels, so no Docker or verified font file is needed. One video per project is kept as a file
(no database change), like the reel video.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import shutil
import subprocess
import threading
from tempfile import TemporaryDirectory
from typing import Callable, Sequence
from uuid import UUID

from pydantic import BaseModel, Field

from backend.app.services import reel_text
from backend.app.services.llm_edit_interpreter import Completion
from backend.app.services.media_probe import MediaProbeError, probe_media

VIDEO_NAME, INFO_NAME = "vlog-captioned.mp4", "vlog-captioned.json"
LINE_FONT, THOUGHT_FONT = reel_text.PRETENDARD_SEMI, reel_text.OWN_PDH
THOUGHT_COLOR = "#FFE14A"
THOUGHTS_PER_MINUTE = 1.5
MAX_THOUGHTS = 40
MIN_THOUGHT_GAP = 20.0  # seconds between two thoughts, so they stay a small accent
THOUGHT_MIN_SECONDS = 2.5
MAX_THOUGHT_CHARS = 14
MAX_LINES_TO_AI = 80

Progress = Callable[[str, int, int], None]
log = logging.getLogger(__name__)


class CaptionError(RuntimeError):
    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Thought:
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class CaptionedVideo:
    path: Path
    render_id: str
    duration_seconds: float
    file_size_bytes: int
    line_count: int
    thoughts: tuple[str, ...]
    thought_engine: str  # "ollama/gemma3:4b" or "" when no thoughts were written


# ---- spoken lines -------------------------------------------------------------------------------------------------

_SRT_TIME = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _seconds(h: str, m: str, s: str, ms: str) -> float:
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms.ljust(3, "0")[:3]) / 1000


def clean_line(text: str) -> str:
    """Speech recognition sometimes glues Latin letters onto a Korean word ("거ikan"); those are dropped."""
    text = re.sub(r"(?<=[가-힣])[A-Za-z]+", "", text or "")
    text = re.sub(r"[A-Za-z]+(?=[가-힣])", "", text)
    text = re.sub(r"[Ͱ-ϿЀ-ӿ֐-ۿ฀-๿぀-ヿ一-鿿]+", "", text)
    return reel_text.clean_text(text)


_FILLER = re.compile(r"^(?:[음어아흠네응]+[\s.,…~!?]*)+$")
# Speech recognition invents these over music or silence (seen on the dance lesson: "구독과 힘이").
_HALLUCINATION = re.compile(r"구독|좋아요|시청해\s*주셔서|알림\s*설정")


def is_noise(text: str, previous: str = "") -> bool:
    """Lines that are not worth showing: no Korean, only "음...", made-up outros, or the same line again."""
    hangul = re.findall(r"[가-힣]", text)
    return (len(hangul) < 2 or bool(_FILLER.match(text)) or bool(_HALLUCINATION.search(text))
            or _norm(text) == _norm(previous))


def parse_srt(text: str) -> list[Cue]:
    """Spoken lines worth showing (see ``is_noise``); foreign-script letters (Cyrillic etc.) are dropped too."""
    cues: list[Cue] = []
    for block in re.split(r"\r?\n\s*\r?\n", (text or "").strip()):
        lines = block.strip().splitlines()
        for index, line in enumerate(lines):
            match = _SRT_TIME.search(line)
            if match:
                start, end = _seconds(*match.groups()[:4]), _seconds(*match.groups()[4:])
                body = clean_line(" ".join(lines[index + 1:]))
                if body and end > start and not is_noise(body, cues[-1].text if cues else ""):
                    cues.append(Cue(start, end, body))
                break
    return cues


# ---- inner thoughts -----------------------------------------------------------------------------------------------

THOUGHT_SYSTEM_PROMPT = (
    "너는 한국 일상 브이로그 편집자다. 영상 주인이 말한 대사 목록을 보고, 몇 줄을 골라 "
    "그 순간 영상 주인의 속마음을 화면 구석에 작게 띄울 한마디로 써라. "
    "반말 혼잣말로 2~12자. 대사를 그대로 옮기거나 요약하지 말고, 그 말 뒤에 숨은 기분이나 딴생각을 쓴다. "
    "틀 예시: '○○ 실화냐', '벌써 ○○', '○○ 하고 싶다', '나만 ○○?' (○○는 대사에 맞게 채운다). "
    "마침표·이모지·괄호 없이. JSON만 출력하라."
)


class _AIThought(BaseModel):
    line: int
    thought: str = Field(max_length=30)


class _AIThoughts(BaseModel):
    thoughts: list[_AIThought]


def thought_budget(duration_seconds: float) -> int:
    return max(1, min(MAX_THOUGHTS, round(duration_seconds / 60 * THOUGHTS_PER_MINUTE)))


def _norm(text: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", text)


def _usable_thought(text: str, cue: Cue) -> str:
    text = reel_text.clean_text(text).strip("()[]\"'.,!~ ")
    text = re.sub(r"[()\[\]]", "", text)
    if not 2 <= len(_norm(text)) or len(text) > MAX_THOUGHT_CHARS:
        return ""
    if _norm(text) in _norm(cue.text) or _norm(cue.text) in _norm(text):
        return ""  # a copy of the spoken line is not a thought
    return text


def write_thoughts(cues: Sequence[Cue], duration_seconds: float, complete: Completion | None) -> list[Thought]:
    if complete is None or not cues:
        return []
    budget = thought_budget(duration_seconds)
    step = max(1, -(-len(cues) // MAX_LINES_TO_AI))
    shown = list(range(0, len(cues), step))
    rows = "\n".join(f"[{i}] {int(cues[i].start // 60):02d}:{int(cues[i].start % 60):02d} {cues[i].text}" for i in shown)
    prompt = (f"영상 길이: {int(duration_seconds // 60)}분 {int(duration_seconds % 60)}초\n"
              f"속마음은 {budget}개 이하로, 영상 전체에 고르게 골라라.\n대사:\n{rows}")
    schema = _AIThoughts.model_json_schema()
    item = schema["$defs"]["_AIThought"]
    item["properties"]["line"] = {"type": "integer", "enum": shown}
    item["properties"]["thought"] = {"type": "string", "minLength": 2, "maxLength": MAX_THOUGHT_CHARS}
    item["required"] = ["line", "thought"]
    schema["properties"]["thoughts"]["minItems"] = 1
    schema["properties"]["thoughts"]["maxItems"] = budget
    try:
        answer = _AIThoughts.model_validate_json(complete(THOUGHT_SYSTEM_PROMPT, prompt, schema))
    except Exception as error:  # noqa: BLE001 - thoughts are a bonus; the spoken lines go on without them
        log.warning("inner thoughts skipped: %s", error)
        return []
    picked: list[Thought] = []
    seen: set[str] = set()
    for item in sorted(answer.thoughts, key=lambda t: t.line):
        if not 0 <= item.line < len(cues):
            continue
        cue = cues[item.line]
        text = _usable_thought(item.thought, cue)
        if not text or _norm(text) in seen or (picked and cue.start - picked[-1].start < MIN_THOUGHT_GAP):
            continue
        seen.add(_norm(text))
        end = min(duration_seconds, max(cue.end, cue.start + THOUGHT_MIN_SECONDS))
        picked.append(Thought(cue.start, end, text))
        if len(picked) >= budget:
            break
    return picked


# ---- subtitle file ------------------------------------------------------------------------------------------------

def _ass_color(hex_color: str, alpha: int = 0) -> str:
    value = hex_color.lstrip("#")
    return f"&H{alpha:02X}{value[4:6]}{value[2:4]}{value[0:2]}".upper()


def build_ass(cues: Sequence[Cue], thoughts: Sequence[Thought], width: int, height: int) -> str:
    """Spoken lines bottom centre; thoughts smaller, hand-written and yellow, right side just above the lines."""
    line_font, thought_font = reel_text._usable(LINE_FONT), reel_text._usable(THOUGHT_FONT)
    scale = height / 1080
    line_size, thought_size = round(58 * scale), round(50 * scale)
    margin_v, side = round(56 * scale), round(width * 0.08)
    thought_x, thought_y = round(width * 0.93), round(height - margin_v - line_size * 1.6)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Line,{line_font.family},{line_size},&H00FFFFFF,&H00FFFFFF,&H00141414,&H96000000,{-1 if line_font.bold else 0},0,0,0,100,100,0,0,1,{max(2, round(3.2 * scale))},{max(1, round(1.5 * scale))},2,{side},{side},{margin_v},1
Style: Thought,{thought_font.family},{thought_size},{_ass_color(THOUGHT_COLOR)},&H00FFFFFF,&H00202A3B,&H64000000,{-1 if thought_font.bold else 0},0,0,0,100,100,0,0,1,{max(2, round(2.6 * scale))},0,3,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = [f"Dialogue: 0,{reel_text.ass_time(c.start)},{reel_text.ass_time(c.end)},Line,,0,0,0,,{c.text}"
              for c in cues]
    events += [f"Dialogue: 1,{reel_text.ass_time(t.start)},{reel_text.ass_time(t.end)},Thought,,0,0,0,,"
               f"{{\\pos({thought_x},{thought_y})\\frz4\\fad(150,150)}}{t.text}" for t in thoughts]
    return header + "\n".join(events) + "\n"


# ---- burning ------------------------------------------------------------------------------------------------------

def _run(command: list[str], cwd: Path, code: str) -> None:
    try:
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                timeout=3600, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CaptionError(code, str(error)) from error
    if result.returncode != 0:
        raise CaptionError(code, result.stderr.strip()[-800:])


def burn_captions(video: Path, srt: Path, output_dir: Path, render_id: str, *,
                  engine: tuple[str, str, Completion] | None = None, ffmpeg: str = "ffmpeg",
                  on_progress: Progress | None = None) -> CaptionedVideo:
    """Write ``output_dir/vlog-captioned.mp4`` (the old one is replaced only after the new one is checked)."""
    progress = on_progress or (lambda step, done, total: None)
    if not Path(video).is_file():
        raise CaptionError("CAPTION_VIDEO_MISSING")
    try:
        cues = parse_srt(Path(srt).read_text(encoding="utf-8-sig")) if srt and Path(srt).is_file() else []
    except (OSError, UnicodeError) as error:
        raise CaptionError("CAPTION_SRT_INVALID") from error
    if not cues:
        raise CaptionError("CAPTION_NO_LINES")
    try:
        info = probe_media(Path(video))
    except MediaProbeError as error:
        raise CaptionError("CAPTION_VIDEO_INVALID") from error
    width, height = info.display_width or 1920, info.display_height or 1080
    progress("속마음 한마디 쓰기", 0, 2)
    thoughts = write_thoughts(cues, info.duration_seconds, engine[2] if engine else None)
    progress("자막 입히기", 1, 2)
    output_dir.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="captions-", dir=output_dir) as directory:
        stage = Path(directory)
        shutil.copyfile(video, stage / "input.mp4")
        (stage / "captions.ass").write_text(build_ass(cues, thoughts, width, height), encoding="utf-8")
        for font in {reel_text._usable(LINE_FONT), reel_text._usable(THOUGHT_FONT)}:
            path = reel_text._path(font)
            if path:
                shutil.copyfile(path, stage / path.name.lower())
        # Relative names only: Windows drive letters ("C:") break FFmpeg's filter syntax.
        _run([ffmpeg, "-v", "error", "-nostdin", "-y", "-i", "input.mp4", "-vf", "ass=captions.ass:fontsdir=.",
              "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p", "-c:a", "copy",
              "-movflags", "+faststart", "output.mp4"], stage, "CAPTION_BURN_FAILED")
        output = stage / "output.mp4"
        try:
            result = probe_media(output)
        except MediaProbeError as error:
            raise CaptionError("CAPTION_OUTPUT_INVALID") from error
        if not result.has_video_stream or abs(result.duration_seconds - info.duration_seconds) > 0.25:
            raise CaptionError("CAPTION_OUTPUT_INVALID", f"{result.duration_seconds} vs {info.duration_seconds}")
        destination = output_dir / VIDEO_NAME
        output.replace(destination)
    progress("완료", 2, 2)
    done = CaptionedVideo(destination, render_id, round(result.duration_seconds, 2), destination.stat().st_size,
                          len(cues), tuple(t.text for t in thoughts), f"{engine[0]}/{engine[1]}" if thoughts and engine else "")
    (output_dir / INFO_NAME).write_text(json.dumps({
        "render_id": done.render_id, "duration_seconds": done.duration_seconds, "line_count": done.line_count,
        "thoughts": list(done.thoughts), "thought_engine": done.thought_engine}, ensure_ascii=False), encoding="utf-8")
    return done


def output_dir(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "captioned"


def saved_video(directory: Path) -> CaptionedVideo | None:
    path, info = directory / VIDEO_NAME, directory / INFO_NAME
    if not path.is_file() or not info.is_file():
        return None
    try:
        data = json.loads(info.read_text(encoding="utf-8"))
        return CaptionedVideo(path, str(data["render_id"]), float(data["duration_seconds"]), path.stat().st_size,
                              int(data["line_count"]), tuple(str(t) for t in data.get("thoughts", [])),
                              str(data.get("thought_engine", "")))
    except (OSError, ValueError, KeyError, TypeError):
        return None


# ---- background job -----------------------------------------------------------------------------------------------

@dataclass
class CaptionJob:
    status: str = "IDLE"  # IDLE | RUNNING | COMPLETED | FAILED
    step: str = ""
    done: int = 0
    total: int = 0
    error_code: str | None = None


_jobs: dict[UUID, CaptionJob] = {}
_lock = threading.Lock()


def job_state(project_id: UUID) -> CaptionJob:
    with _lock:
        job = _jobs.get(project_id)
        return CaptionJob(**vars(job)) if job else CaptionJob()


def local_engine() -> tuple[str, str, Completion] | None:
    """Only the local AI writes thoughts; a paid provider is never called from here."""
    from backend.app.services.llm_edit_interpreter import configured_engine

    engine = configured_engine()
    return engine if engine and engine[0] == "ollama" else None


def start_captioning(project_id: UUID, video: Path, srt: Path | None, render_id: str, output_root: Path, *,
                     burn=None, engine=..., background: bool = True) -> str | None:
    """None when started, otherwise a reason code."""
    with _lock:
        if project_id in _jobs and _jobs[project_id].status == "RUNNING":
            return "CAPTION_RUNNING"
        _jobs[project_id] = CaptionJob(status="RUNNING", step="준비", total=2)

    def update(**changes) -> None:
        with _lock:
            for key, value in changes.items():
                setattr(_jobs[project_id], key, value)

    def work() -> None:
        try:
            (burn or burn_captions)(video, srt, output_dir(output_root, project_id), render_id,
                                    engine=local_engine() if engine is ... else engine,
                                    on_progress=lambda step, done, total: update(step=step, done=done, total=total))
            update(status="COMPLETED", step="완료")
        except CaptionError as error:
            log.warning("long-form captions failed: %s", error)
            update(status="FAILED", error_code=error.code)
        except Exception:  # noqa: BLE001 - the screen shows a safe code; details stay in the server log
            log.exception("long-form captions failed")
            update(status="FAILED", error_code="CAPTION_FAILED")

    if background:
        threading.Thread(target=work, name=f"captions-{project_id}", daemon=True).start()
    else:
        work()
    return None
