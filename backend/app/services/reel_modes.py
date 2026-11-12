"""TODO 10: short-form (reels/shorts) settings in one place: modes, pace and lengths.

Add or change a mode here only. ``order`` decides how the draft is arranged:
- ``timeline``: the hook shot first, then the rest in filmed order (vlog, practice, travel, cafe, workout)
- ``items``: the hook shot first, then numbered items in filmed order with a small label per item (haul, review)
- ``steps``: the finished result first, then every step in filmed order (recipe)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ReelOrder = Literal["timeline", "items", "steps"]


@dataclass(frozen=True)
class ReelMode:
    key: str
    label: str
    order: ReelOrder
    title_example: str  # shows the AI what a hook title looks like for this mode
    caption_style: str  # tone of the per-shot line


MODES: tuple[ReelMode, ...] = (
    ReelMode("daily_vlog", "일상 브이로그", "timeline", "평범한 화요일 브이로그",
             "그 순간 상황을 친구에게 말하듯 짧게. 장난스러운 혼잣말도 좋다"),
    ReelMode("challenge", "도전기·연습 기록", "timeline", "첫 댄스곡 도전기",
             "연습 과정과 감정을 짧게. 어려움, 칭찬, 성공 같은 변화가 보이게"),
    ReelMode("try_on", "옷 입어보기·하울", "items", "직접 입어본 추천템 3가지",
             "옷의 특징(핏, 색, 소재)과 솔직한 느낌을 짧게"),
    ReelMode("review", "꿀템·제품 리뷰", "items", "요즘 매일 쓰는 꿀템",
             "제품의 쓸모와 장단점을 솔직하게 짧게"),
    ReelMode("recipe", "요리 레시피", "steps", "10분 완성 간장계란밥",
             "지금 하는 조리 단계를 명령형으로 짧게 (예: 버터 녹이기)"),
    ReelMode("cafe", "맛집·카페", "timeline", "줄 서서 먹는 소금빵 맛집",
             "메뉴, 맛, 분위기를 감탄하듯 짧게"),
    ReelMode("travel", "여행", "timeline", "부산 1박 2일",
             "장소와 그때의 느낌을 짧게"),
    ReelMode("workout", "운동·루틴", "timeline", "퇴근 후 30분 홈트",
             "운동 이름이나 루틴 단계, 힘든 정도를 짧게"),
)
MODE_BY_KEY = {mode.key: mode for mode in MODES}
AUTO_MODE = "auto"

# Average seconds per shot. Blo's reels measured about 2 s per shot and felt too fast to the user.
PACES: dict[str, tuple[str, float]] = {
    "relaxed": ("여유있게", 4.0),
    "normal": ("보통", 2.5),
    "fast": ("빠르게", 1.8),
}
DEFAULT_PACE = "normal"

SHORT_LENGTHS = (15, 30, 45, 60, 90)
DEFAULT_SHORT_SECONDS = 30
MIN_SHOT_SECONDS = 1.0
