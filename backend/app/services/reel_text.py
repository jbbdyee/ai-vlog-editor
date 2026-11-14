"""TODO 13: text looks ("templates") for the vertical reel.

One place holds every choice the screen offers (template, accent colour, where the lines sit, size) and turns a reel
draft into an ASS subtitle file.

What the looks are based on (the user's Blo samples plus 2026 caption guides): a current typeface does most of the
work; lines are clean white with a soft shadow rather than a thick black outline; one accent colour, used on the
punch line of the title or the name tag only; coloured pills (never dark boxes) for name tags; the title is two lines (small lead-in +
big punch line) with a pill badge or pixel stars; nothing sits in the top ~15% or bottom ~25% of the frame, which the
Instagram buttons cover. Neon glows and double outlines were dropped: they read as dated.

Every line is placed by Python (``\\pos``) and wrapped by Python, so a box drawn behind a line always fits it and the
top/middle/bottom choice means the same thing in every template.

Fonts: free typefaces live in ``assets/reel-fonts`` (not in Git, about 100 MB). A missing file falls back to Malgun
Gothic, so the app still works without them. Sources, all free for video use:
- github.com/google/fonts (OFL): Gaegu, Jua, Do Hyeon, Black Han Sans, Bagel Fat One, Gowun Dodum/Batang, Nanum Pen,
  Hi Melody, Gamja Flower, Poor Story, Single Day, Dongle, Sunflower, Diphylleia
- npm ``pretendard`` and ``galmuri`` via cdn.jsdelivr.net (OFL)
- github.com/fonts-archive: Paperlogy, BM kkubulim, SUIT, Cafe24 Ssurround / Dongdong
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Sequence

WIDTH, HEIGHT, FPS = 1080, 1920, 30
TITLE_MIN_SECONDS = 2.5  # a very short hook scene still leaves the title on screen long enough to read
SYSTEM_FONT_DIR = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
PROJECT_FONT_DIR = Path(__file__).resolve().parents[3] / "assets" / "reel-fonts"
DEFAULT_FONT = SYSTEM_FONT_DIR / "malgunbd.ttf"
MAX_LINE_WIDTH = 920  # px of the 1080 wide frame a line may use
LINE_GAP = 1.3  # line height as a multiple of the font size
# Instagram covers the top and bottom of a reel with its own buttons; lines stay between these.
SAFE_TOP, SAFE_BOTTOM, MIDDLE = 300.0, 1420.0, 1060.0
# TODO 17: a wide clip is not centred but sits a little high (its top edge at y=520), like the popular reels: the
# title goes in the black band above it and the name tag and line in the band right below it.
WIDE_VIDEO_TOP = 520
BAND_GAP = 36  # px between the clip's edge and the text in a band
BAND_ROOM = 200  # px the band below should keep for text before the safe-area bottom


@dataclass(frozen=True)
class WideFrame:
    """Where a wide clip sits in the 1080x1920 frame (rows ``top`` to ``bottom``)."""
    top: int
    height: int

    @property
    def bottom(self) -> int:
        return self.top + self.height


def wide_frame(width: int | None, height: int | None) -> WideFrame | None:
    """Place of a clip of this on-screen size, or None for a portrait/square clip (it fills the frame as before)."""
    if not width or not height or width <= height:
        return None
    scaled = max(2, round(WIDTH * height / width / 2) * 2)  # even, for the video encoder
    # A taller clip (4:3) moves up so the band below still has room for the lines.
    top = min(WIDE_VIDEO_TOP, max(0, int(SAFE_BOTTOM) - BAND_ROOM - scaled))
    return WideFrame(top - top % 2, scaled)


@dataclass(frozen=True)
class Font:
    family: str
    file: str
    bold: bool = False
    width: float = 0.92  # how wide a Korean letter is, as a share of the font size


MALGUN = Font("Malgun Gothic", "malgunbd.ttf", True)
PRETENDARD = Font("Pretendard Medium", "Pretendard-Medium.otf", width=0.88)
PRETENDARD_SEMI = Font("Pretendard SemiBold", "Pretendard-SemiBold.otf", width=0.88)
PAPERLOGY = Font("Paperlogy 8 ExtraBold", "Paperlogy-8ExtraBold.ttf", width=0.88)
BLACK_HAN = Font("Black Han Sans", "BlackHanSans-Regular.ttf", width=0.86)
GALMURI = Font("Galmuri11 Bold", "Galmuri11-Bold.ttf", width=0.95)  # pixel letters (Y2K vlogs)
KKUBULIM = Font("BM kkubulim TTF", "BMKkubulim.ttf", width=0.86)  # wobbly marker hand
GAEGU = Font("Gaegu", "Gaegu-Bold.ttf", True, width=0.80)  # light pen hand
JUA = Font("Jua", "Jua-Regular.ttf", width=0.88)  # round and friendly
BATANG = Font("Gowun Batang", "GowunBatang-Bold.ttf", True, width=0.90)  # soft serif
# TODO 15: Ownglyph (온글잎) hand fonts, from ownglyph.com trial pages. Of the four downloaded, these two were the most
# readable on real footage; 류뤼체 was too thin.
OWN_PDH = Font("Ownglyph PDH Regular", "Ownglyph_ParkDaHyun.ttf", width=0.86)  # 박다현체: round diary hand
OWN_YEBIN = Font("Ownglyph Shin Yebin Regular", "OwnglyphShinYebin.ttf", width=0.88)  # 신예빈체: firm pen hand


def font_dir() -> Path:
    return Path(os.environ.get("CUTORY_REEL_FONT_DIR") or PROJECT_FONT_DIR)


def reel_font() -> Path:
    return Path(os.environ.get("CUTORY_REEL_FONT_PATH") or DEFAULT_FONT)


def _path(font: Font) -> Path | None:
    for folder in (font_dir(), SYSTEM_FONT_DIR):
        if (folder / font.file).is_file():
            return folder / font.file
    return None


def _usable(font: Font) -> Font:
    return font if _path(font) else MALGUN


@dataclass(frozen=True)
class Template:
    key: str
    label: str
    hint: str
    font: Font  # caption lines
    display: Font  # title and name tag
    caption_look: str  # shadow | soft | outline | box | thick
    accent_look: str  # look of the name tag and the title (also: glow | tint)
    accent: str  # default colour key
    position: str  # default place of the caption lines
    caption: int
    tag: int
    title_small: int
    title_big: int
    mark: str = ""  # title decoration: stars | pill | rule | sparkle
    spacing: int = 0
    title_place: str = "top"


TEMPLATES: tuple[Template, ...] = (
    Template("clean", "깔끔 감성", "얇고 깨끗한 흰 글씨, 색 번짐 이름표, 알약 배지 제목 (옷·일상·룩북)",
             PRETENDARD, KKUBULIM, "shadow", "glow", "green", "top", 70, 48, 60, 100, "pill", title_place="middle"),
    Template("pixel", "픽셀 브이로그", "픽셀 글씨에 별 장식 두 줄 제목 (브이로그·도전기·댄스)",
             GALMURI, GALMURI, "soft", "soft", "sky", "top", 62, 46, 58, 94, "stars"),
    Template("diary", "다이어리 손글씨", "온글잎 박다현체, 노란 앞말에 반짝이 장식 (맛집·여행·일상)",
             OWN_PDH, OWN_PDH, "shadow", "shadow", "yellow", "bottom", 82, 56, 64, 108, "sparkle"),
    Template("hand", "손글씨", "온글잎 신예빈체, 펜으로 쓴 듯한 글씨에 포인트 색 제목 (일상·후기·공감)",
             OWN_YEBIN, OWN_YEBIN, "soft", "soft", "yellow", "bottom", 84, 56, 64, 112),
    # TODO 15: the dark box behind the lines is gone (no popular reel used one); the coloured pill name tag stays.
    Template("box", "알약 이름표", "그림자 흰 글씨에 색 알약 이름표 (정보·리뷰·복잡한 배경)",
             PRETENDARD_SEMI, PRETENDARD_SEMI, "shadow", "box", "yellow", "middle", 62, 42, 58, 80),
    Template("hook", "굵은 후킹", "두꺼운 고딕에 얇은 테두리, 큰 색 제목 (꿀팁·정보·말하는 영상)",
             PAPERLOGY, BLACK_HAN, "outline", "outline", "yellow", "middle", 76, 50, 84, 132),
    Template("mood", "매거진", "부드러운 명조에 넓은 자간, 가는 선 제목 (감성·여행·룩북)",
             BATANG, BATANG, "shadow", "shadow", "white", "bottom", 58, 38, 48, 104, "rule", 5),
    Template("cute", "말랑 귀염", "동글동글한 글씨에 색 테두리 제목 (귀여운 일상·먹방·반려동물)",
             JUA, JUA, "soft", "tint", "pink", "bottom", 76, 50, 62, 110, "pill"),
    Template("basic", "기본", "맑은 고딕 흰 글씨에 검은 테두리", MALGUN, MALGUN, "thick", "thick", "mint", "bottom",
             74, 52, 96, 96),
)
TEMPLATE_BY_KEY = {t.key: t for t in TEMPLATES}
DEFAULT_TEMPLATE = "basic"

# key -> (label, #RRGGBB). "auto" uses the template's own colour.
COLORS: dict[str, tuple[str, str]] = {
    "green": ("연두", "#B9F29B"), "sky": ("하늘", "#6FC3FF"), "pink": ("분홍", "#FF8FC0"),
    "yellow": ("노랑", "#FFE14A"), "lavender": ("라벤더", "#C9B6FF"), "mint": ("민트", "#9FE7F2"),
    "coral": ("코랄", "#FF8A6B"), "white": ("흰색", "#FFFFFF"),
}
POSITIONS: dict[str, str] = {"top": "위", "middle": "가운데", "bottom": "아래"}
SIZES: dict[str, tuple[str, float]] = {"small": ("작게", 0.86), "normal": ("보통", 1.0), "large": ("크게", 1.16)}
# TODO 15: how the title and lines come on screen. All six popular reels checked had the title readable on the very
# first frame (it doubles as the feed preview), so every motion is finished within a quarter of a second.
MOTIONS: dict[str, str] = {"pop": "톡", "rise": "스르륵", "none": "없음"}
DEFAULT_MOTION = "pop"
AUTO = "auto"


@dataclass(frozen=True)
class TextStyle:
    template: str = DEFAULT_TEMPLATE
    color: str = AUTO
    position: str = AUTO
    size: str = "normal"
    motion: str = DEFAULT_MOTION

    def to_json(self) -> dict[str, str]:
        return {"template": self.template, "color": self.color, "position": self.position, "size": self.size,
                "motion": self.motion}


def normalize(style: TextStyle | dict | None) -> TextStyle:
    """Unknown or missing choices become the defaults, so an old request or file never breaks a render."""
    if isinstance(style, TextStyle):
        style = style.to_json()
    data = style if isinstance(style, dict) else {}
    return TextStyle(
        template=data.get("template") if data.get("template") in TEMPLATE_BY_KEY else DEFAULT_TEMPLATE,
        color=data.get("color") if data.get("color") in COLORS else AUTO,
        position=data.get("position") if data.get("position") in POSITIONS else AUTO,
        size=data.get("size") if data.get("size") in SIZES else "normal",
        motion=data.get("motion") if data.get("motion") in MOTIONS else DEFAULT_MOTION,
    )


def font_files(style: TextStyle | dict | None = None) -> list[Path]:
    """Font files the chosen template needs (plus the fallback), for the renderer to hand to FFmpeg."""
    template = TEMPLATE_BY_KEY[normalize(style).template]
    paths = {_path(_usable(font)) for font in (MALGUN, template.font, template.display)}
    return sorted(path for path in paths if path)


# Emoji, pictographs, dingbats, variation selectors and joiners; everything else (Korean, Latin, digits) stays.
_EMOJI = re.compile("[\U00010000-\U0010FFFF\u2600-\u27BF\u2B00-\u2BFF\uFE00-\uFE0F\u200D\u20E3]")


def clean_text(text: str) -> str:
    text = _EMOJI.sub("", text or "")
    text = text.replace("\\", "").replace("{", "(").replace("}", ")")
    return re.sub(r"\s+", " ", text).strip()


def frames(seconds: float) -> int:
    return max(1, round(seconds * FPS))


def ass_time(seconds: float) -> str:
    centis = max(0, round(seconds * 100))
    hours, rest = divmod(centis, 360000)
    minutes, rest = divmod(rest, 6000)
    secs, cs = divmod(rest, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _color(value: str) -> str:
    """#RRGGBB -> ASS &HBBGGRR&."""
    value = value.lstrip("#")
    return f"&H{value[4:6]}{value[2:4]}{value[0:2]}&".upper()


def _shade(value: str, factor: float) -> str:
    """Darker (factor < 1) version of a colour, for a glow that still shows on a bright wall."""
    value = value.lstrip("#")
    return "#" + "".join(f"{round(int(value[i:i + 2], 16) * factor):02X}" for i in (0, 2, 4))


def _is_light(value: str) -> bool:
    value = value.lstrip("#")
    red, green, blue = (int(value[i:i + 2], 16) for i in (0, 2, 4))
    return 0.299 * red + 0.587 * green + 0.114 * blue > 150


def text_width(text: str, size: float, spacing: int = 0, letter: float = 0.92) -> float:
    """Rough width in px (a Korean letter is ``letter`` x the font size wide)."""
    width = 0.0
    for char in text:
        if char == " ":
            width += size * 0.30
        elif ord(char) < 0x2E80:
            width += size * (0.34 if char in ".,!?'\":;()·-~" else 0.58)
        else:
            width += size * letter
        width += spacing
    return width


def wrap(text: str, size: float, spacing: int = 0, limit: float = MAX_LINE_WIDTH, letter: float = 0.92) -> list[str]:
    """Break at spaces so each line fits the frame; a single over-long word is cut."""
    def wide(value: str) -> float:
        return text_width(value, size, spacing, letter)

    lines: list[str] = []
    current = ""
    for word in text.split(" "):
        while wide(word) > limit:  # one very long word
            cut = max(1, int(len(word) * limit / wide(word)))
            if current:
                lines.append(current)
                current = ""
            lines.append(word[:cut])
            word = word[cut:]
        candidate = f"{current} {word}".strip()
        if current and wide(candidate) > limit:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def split_title(title: str) -> list[str]:
    """Two lines (lead-in + punch line) when the title has a space near the middle; otherwise one line."""
    words = title.split(" ")
    if len(words) < 2 or len(title) < 6:
        return [title]
    best = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(title) / 2))
    return [" ".join(words[:best]), " ".join(words[best:])]


@dataclass(frozen=True)
class _Line:
    text: str
    size: int
    role: str  # caption | tag | title_small | title_big | mark
    font: Font

    @property
    def width(self) -> float:
        return text_width(self.text, self.size, letter=_usable(self.font).width)


@dataclass(frozen=True)
class _Motion:
    """How the lines drawn next come on screen (TODO 15). Times are in ms from the start of each line's event."""
    kind: str  # pop | rise
    length: int  # how long the event lasts
    caption: bool = False  # scene lines: a small, quick rise; they leave with the cut
    fade_out: bool = False  # the title fades out over its last 0.2 s


# Within the title the lead-in comes first, the big line a beat later, decorations last.
_DELAY = {"title_big": 80, "mark": 160}


class _Writer:
    """Collects Dialogue lines for one template with the user's colour and size applied."""

    def __init__(self, template: Template, accent: str, scale: float) -> None:
        self.t, self.accent, self.scale = template, accent, scale
        self.events: list[str] = []
        self.motion: _Motion | None = None

    def px(self, value: float) -> int:
        return max(1, round(value * self.scale))

    def _event(self, layer: int, start: str, end: str, tags: str, text: str) -> None:
        self.events.append(f"Dialogue: {layer},{start},{end},Base,,0,0,0,,{{{tags}}}{text}")

    def _place(self, x: float, y: float, role: str) -> str:
        """\\pos, or with motion \\move from a little lower plus a fade (and a scale bounce for "pop" titles).

        \\fade multiplies every layer's own transparency, so the hollow shadow layers stay hollow.
        """
        x, y = round(x), round(y)
        m = self.motion
        if m is None:
            return f"\\pos({x},{y})"
        delay = 0 if m.caption else _DELAY.get(role, 0)
        come = 150 if m.caption else (120 if m.kind == "pop" else 250)
        out = (m.length - 200, m.length) if m.fade_out and m.length > delay + come + 200 else (m.length, m.length)
        tags = f"\\fade(255,0,{255 if m.fade_out else 0},{delay},{delay + come},{out[0]},{out[1]})"
        if m.caption or m.kind == "rise":
            rise = self.px(24 if m.caption else 40)
            return f"\\move({x},{y + rise},{x},{y},{delay},{delay + (150 if m.caption else 250)})" + tags
        return (f"\\pos({x},{y})" + tags + f"\\fscx70\\fscy70\\t({delay},{delay + 150},\\fscx106\\fscy106)"
                f"\\t({delay + 150},{delay + 250},\\fscx100\\fscy100)")

    def text(self, layer, start, end, y, line: _Line, fill, *, x=WIDTH // 2, border=0.0, border_color="#000000",
             shadow=0.0, blur=0.0, hollow=False, border_alpha="00", shadow_alpha="70") -> None:
        font = _usable(line.font)
        spacing = self.t.spacing if line.role in ("caption", "tag", "title_small") else 0
        tags = (f"\\an8{self._place(x, y, line.role)}\\fn{font.family}\\fs{line.size}\\b{1 if font.bold else 0}"
                f"\\1c{_color(fill)}\\3c{_color(border_color)}\\4c&H000000&\\1a&H{'FF' if hollow else '00'}&"
                f"\\3a&H{border_alpha}&\\4a&H{shadow_alpha}&\\bord{border:g}\\shad{shadow:g}\\blur{blur:g}"
                f"\\fsp{spacing}")
        self._event(layer, start, end, tags, line.text)

    def pill(self, layer, start, end, center_x, top, width, height, fill, alpha="00", role="title_small") -> None:
        """Rounded box drawn behind a line (anchored at its top centre, so a "pop" grows it evenly)."""
        w, h = round(width), round(height)
        r = min(h // 2, round(height * 0.42))
        path = (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
                f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")
        tags = (f"\\an8{self._place(center_x, top, role)}\\1c{_color(fill)}\\1a&H{alpha}&\\bord0\\shad0"
                f"\\blur0.6\\p1")
        self._event(layer, start, end, tags, path)

    def halo(self, start, end, y, line: _Line, strength: str = "70") -> None:
        """Soft dark cloud behind the letters: keeps white text readable on a bright wall without an outline."""
        self.text(0, start, end, y, line, "#000000", border=max(2.0, line.size * 0.035),
                  blur=max(5.0, line.size * 0.11), hollow=True, border_alpha=strength)

    def line(self, start: str, end: str, y: float, line: _Line) -> None:
        """Draw one line of text in this template's look."""
        size, accent = line.size, self.accent
        emphasized = line.role in ("title_big", "tag")
        look = self.t.caption_look if line.role == "caption" else self.t.accent_look
        if look == "thick":  # the first look this app had
            fill = accent if line.role == "tag" else "#FFFFFF"
            self.text(1, start, end, y, line, fill, border=round(size * 0.08, 1), shadow=2)
        elif look == "outline":  # heavy letters, hairline edge
            fill = accent if line.role == "title_big" else "#FFFFFF"
            self.halo(start, end, y, line, "88")
            self.text(1, start, end, y, line, fill, border=round(max(2.0, size * 0.035), 1), border_color="#141416",
                      shadow=round(size * 0.035, 1), shadow_alpha="50")
        elif look == "glow":  # white letters in a soft cloud of the accent colour
            glow = _shade(accent, 0.55)
            self.text(0, start, end, y, line, glow, border=size * 0.08, border_color=glow, blur=size * 0.12,
                      hollow=True, border_alpha="28")
            self.text(0, start, end, y, line, glow, border=size * 0.04, border_color=glow, blur=size * 0.05,
                      hollow=True, border_alpha="40")
            self.text(2, start, end, y, line, "#FFFFFF")
        elif look in ("soft", "tint"):  # letters with a faint edge; "tint" colours the emphasized lines' edge
            tinted = look == "tint" and emphasized
            fill = accent if line.role == "title_big" and look == "soft" else "#FFFFFF"
            self.halo(start, end, y, line, "80" if tinted else "60")
            self.text(1, start, end, y, line, fill, border=round(size * (0.06 if tinted else 0.03), 1),
                      border_color=_shade(accent, 0.6) if tinted else "#17171B",
                      border_alpha="10" if tinted else "40", blur=0.8)
        elif look == "box" and emphasized:  # coloured pill behind the name tag and the big title line
            pad_x, pad_y = size * 0.46, size * 0.22
            self.pill(0, start, end, WIDTH / 2, y - pad_y, line.width + pad_x * 2, size * 1.14 + pad_y * 2, accent,
                      "00", role=line.role)
            self.text(1, start, end, y, line, "#111114" if _is_light(accent) else "#FFFFFF")
        else:  # shadow: clean letters, no edge (TODO 15: also the plain lines of the pill template, no dark box)
            accented = line.role == "tag" or (line.role == "title_small" and self.t.mark == "sparkle")
            self.halo(start, end, y, line, "68")
            self.text(1, start, end, y, line, accent if accented else "#FFFFFF", shadow=2, shadow_alpha="90", blur=0.4)

    def advance(self, line: _Line) -> float:
        look = self.t.caption_look if line.role == "caption" else self.t.accent_look
        pill = look == "box" and line.role in ("title_big", "tag")
        return line.size * (LINE_GAP + (0.36 if pill else 0.0))  # pills need air between them

    def height(self, lines: Sequence[_Line]) -> float:
        return sum(self.advance(line) for line in lines)

    def block(self, start: str, end: str, lines: Sequence[_Line], place: str, below: float = 0.0,
              at: float | None = None) -> tuple[float, float]:
        """Stack lines at the top, middle or bottom of the frame; returns the block's top and bottom.

        ``below``: keep the block under this y (the title, while it shares the top of the frame with the lines).
        ``at``: put the block's top exactly here (the black bands around a wide clip).
        """
        height = self.height(lines)
        top = at if at is not None else {"top": SAFE_TOP, "middle": MIDDLE - height / 2,
                                         "bottom": SAFE_BOTTOM - height, "title_top": 250.0,
                                         "title_middle": 820.0 - height / 2}[place]
        top = max(top, below)
        y = top
        for line in lines:
            self.line(start, end, y, line)
            y += self.advance(line)
        return top, y


def _band_top(height: float, band: WideFrame) -> float:
    """Top of a block that ends just above a wide clip, never above the safe area."""
    return max(SAFE_TOP, band.top - BAND_GAP - height)


def _title(writer: _Writer, template: Template, title: str, start: str, end: str, place: str, lead: str = "",
           band: WideFrame | None = None) -> float:
    """Draw the title; returns the y where it ends. ``band``: the first scene is wide, so the title sits above it.

    TODO 14: when the draft has a lead-in, it and the title are two separate text boxes (as in Blo), never one
    sentence cut in two. Older drafts without a lead-in are still split at a space near the middle.
    """
    if lead:
        parts = [lead, title]
    else:
        parts = split_title(title) if template.key != "basic" else [title]
    letter = _usable(template.display).width
    lines: list[_Line] = []
    for index, part in enumerate(parts):
        big = index == len(parts) - 1
        size = writer.px(template.title_big if big else template.title_small)
        role = "title_big" if big else "title_small"
        rows = wrap(part, size, letter=letter, limit=MAX_LINE_WIDTH - (size * 1.4 if not big and template.mark == "sparkle" else 0))
        if not big and template.mark == "sparkle":  # ✦ lead-in ✦, like the hand-written food reels
            rows = [f"✦ {row} ✦" for row in rows]
        lines += [_Line(text, size, role, template.display) for text in rows]
    mark, accent = template.mark, writer.accent
    if mark == "pill" and len(lines) > 1:  # first line becomes a rounded badge above the big line
        badge, rest = lines[0], lines[1:]
        badge = _Line(badge.text, writer.px(template.title_small * 0.74), "title_small", template.display)
        height = badge.size * 1.9 + writer.height(rest)
        top = (_band_top(height, band) if band else (820.0 - height / 2) if place == "title_middle" else 250.0)
        writer.pill(0, start, end, WIDTH / 2, top, badge.width + badge.size * 1.4, badge.size * 1.56, accent, "10",
                    role="title_small")
        writer.text(1, start, end, top + badge.size * 0.2, badge, "#2A2A2E" if _is_light(accent) else "#FFFFFF")
        y = top + badge.size * 1.9
        for line in rest:
            writer.line(start, end, y, line)
            y += writer.advance(line)
        return y
    top, bottom = writer.block(start, end, lines, place,
                               at=_band_top(writer.height(lines) + (writer.px(40) if mark == "stars" else 0), band)
                               if band else None)
    widest = max(line.width for line in lines)
    if mark == "stars":
        left, right = WIDTH / 2 - widest / 2, WIDTH / 2 + widest / 2
        spots = [(left - 70, top - 4, 56, "#FFFFFF"), (right + 34, top - 30, 64, accent),
                 (left - 96, bottom - 104, 50, accent), (right + 60, bottom - 90, 54, "#FFFFFF"),
                 (left + 24, bottom + 4, 46, accent)]
        for x, y, size, color in spots:
            star = _Line("★", writer.px(size), "mark", template.display)
            writer.text(1, start, end, y, star, color, x=min(WIDTH - 50, max(50, x)), border=1.5,
                        border_color="#17171B", border_alpha="50", blur=0.8)
    elif mark == "rule" and len(lines) > 1:  # a hairline between the small line and the big line
        y = top + writer.advance(lines[0]) - lines[0].size * 0.10
        writer.pill(1, start, end, WIDTH / 2, y, min(widest, 420), 3, "#FFFFFF", "20", role="title_big")
    return bottom + (writer.px(40) if mark == "stars" else 0)


def _ms(end: float, begin: float = 0.0) -> int:
    """Event length in ms as the subtitle file holds it (start and end are each rounded to centiseconds)."""
    return (max(0, round(end * 100)) - max(0, round(begin * 100))) * 10


def build_ass(draft, style: TextStyle | dict | None = None,
              wide: Sequence[WideFrame | None] | None = None) -> str:
    """Times follow the frame-snapped scene lengths, the same ones used to cut the video.

    ``wide``: per scene, where its wide clip sits (None for a portrait scene). A wide scene's name tag and line go in
    the band right under the clip whatever position was chosen; the title goes above the first scene's clip.
    """
    boxes = list(wide or [])
    boxes += [None] * (len(draft.scenes) - len(boxes))
    style = normalize(style)
    template = TEMPLATE_BY_KEY[style.template]
    accent = COLORS[style.color if style.color != AUTO else template.accent][1]
    place = style.position if style.position != AUTO else template.position
    writer = _Writer(template, accent, SIZES[style.size][1])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {WIDTH}
PlayResY: {HEIGHT}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Base,{MALGUN.family},74,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    # Most titles sit at the top. A template whose title sits mid-frame (like the pill badge) moves it up when the
    # lines are mid-frame too; when a top title meets top lines, the lines wait right under it.
    title_place = template.title_place
    if title_place == "middle" and place == "middle":
        title_place = "top"
    title_band = boxes[0] if boxes else None
    if title_band:
        title_place = "top"  # above the clip, in the top band
    t, title_end, title_bottom = 0.0, 0.0, 0.0
    total = sum(frames(s.end_seconds - s.start_seconds) for s in draft.scenes) / FPS
    for index, scene in enumerate(draft.scenes):
        length = frames(scene.end_seconds - scene.start_seconds) / FPS
        start, end = ass_time(t), ass_time(t + length)
        caption, label, title = clean_text(scene.caption), clean_text(scene.label), clean_text(draft.title)
        if index == 0 and title:
            title_end = min(total, max(length, TITLE_MIN_SECONDS))
            writer.motion = (None if style.motion == "none"
                             else _Motion(style.motion, _ms(title_end), fade_out=title_end < total - 0.001))
            title_bottom = _title(writer, template, title, start, ass_time(title_end), f"title_{title_place}",
                                  clean_text(getattr(draft, "title_lead", "")), band=title_band)
        writer.motion = None if style.motion == "none" else _Motion(style.motion, _ms(t + length, t), caption=True)
        lines: list[_Line] = []
        if label:
            size, font = writer.px(template.tag), template.display
            lines += [_Line(text, size, "tag", font)
                      for text in wrap(label, size, template.spacing, letter=_usable(font).width)]
        if caption:
            size, font = writer.px(template.caption), template.font
            lines += [_Line(text, size, "caption", font)
                      for text in wrap(caption, size, template.spacing, letter=_usable(font).width)]
        box = boxes[index]
        if lines and box:  # wide clip: right under it, kept inside the safe area
            writer.block(start, end, lines, place,
                         at=min(box.bottom + BAND_GAP, SAFE_BOTTOM - writer.height(lines)))
        elif lines:
            # While the title is up and shares the top of the frame, the lines sit right under it.
            under = title_place == place == "top" and t < title_end - 0.001
            writer.block(start, end, lines, place, below=title_bottom + writer.px(24) if under else 0.0)
        t += length
    return header + "\n".join(writer.events) + "\n"


def options() -> dict:
    """Choices for the screen, so it never keeps its own copy."""
    return {
        "templates": [{"key": t.key, "label": t.label, "hint": t.hint} for t in TEMPLATES],
        "colors": [{"key": AUTO, "label": "템플릿 기본"}] + [{"key": k, "label": v[0]} for k, v in COLORS.items()],
        "positions": [{"key": AUTO, "label": "템플릿 기본"}] + [{"key": k, "label": v} for k, v in POSITIONS.items()],
        "sizes": [{"key": k, "label": v[0]} for k, v in SIZES.items()],
        "motions": [{"key": k, "label": v} for k, v in MOTIONS.items()],
    }
