"""TODO 10/11: short-form (reels/shorts) settings in one place: modes, pace, lengths and what the screen-reading
AI may answer about a shot.

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
    title_example: str  # "lead / title" pattern; ○○ = words from the video, N = item count (TODO 14: gemma3:4b copied full example titles word for word)
    caption_style: str  # tone of the per-shot line
    caption_examples: tuple[str, ...] = ()  # good on-screen lines (TODO 11: modelled on the user's Blo reels)


MODES: tuple[ReelMode, ...] = (
    ReelMode("daily_vlog", "일상 브이로그", "timeline", "○○한 ○요일의 / ○○ 브이로그",
             "그 순간 상황을 친구에게 말하듯 짧게. 장난스러운 혼잣말도 좋다",
             ("오늘은 집콕 데이", "커피 수혈 완료", "이거 완전 내 스타일", "하루 끝!")),
    ReelMode("challenge", "도전기·연습 기록", "timeline", "○○의 / 첫 ○○ 도전기",
             "연습 과정과 감정을 짧게. 어려움, 칭찬, 성공 같은 변화가 보이게",
             ("처음 뵙겠습니다", "동작 바로잡기", "손끝 디테일 살려요", "성공해서 신남ㅎㅎ", "폭풍 칭찬 받았어요", "연습 끝!")),
    ReelMode("try_on", "옷 입어보기·하울", "items", "직접 입어본 / ○○ N가지",
             "옷의 특징(핏, 색, 소재)과 솔직한 느낌을 짧게",
             ("핏이 탄탄해요", "뒤태 라인까지", "살랑이는 실루엣 최고", "솔직히 좀 작았어요", "완전 힙하고 예뻐요")),
    ReelMode("review", "꿀템·제품 리뷰", "items", "요즘 매일 쓰는 / ○○ N가지",
             "제품의 쓸모와 장단점을 솔직하게 짧게",
             ("이거 하나면 끝", "생각보다 가벼워요", "단점은 소리가 커요", "재구매 각")),
    ReelMode("recipe", "요리 레시피", "steps", "○분 완성 / ○○ 레시피",
             "지금 하는 조리 단계를 명령형으로 짧게 (예: 버터 녹이기)",
             ("버터 녹이기", "계란 두 개 투하", "간장 한 숟갈", "완성!")),
    ReelMode("cafe", "맛집·카페", "timeline", "줄 서서 먹는 / ○○ 맛집",
             "메뉴, 맛, 분위기를 감탄하듯 짧게",
             ("겉바속촉 그 자체", "창가 자리 명당", "이건 꼭 시키세요", "재방문 확정")),
    ReelMode("travel", "여행", "timeline", "○○ 떠난 / ○○ 여행",
             "장소와 그때의 느낌을 짧게",
             ("드디어 도착", "바다 색 미쳤다", "여기 노을 맛집", "벌써 아쉬워")),
    ReelMode("workout", "운동·루틴", "timeline", "퇴근 후 ○분 / ○○ 루틴",
             "운동 이름이나 루틴 단계, 힘든 정도를 짧게",
             ("스쿼트 3세트", "하체 불타는 중", "마지막 한 개!", "오늘도 해냄")),
)
MODE_BY_KEY = {mode.key: mode for mode in MODES}
AUTO_MODE = "auto"

# What the screen-reading AI may say a shot is doing (TODO 11). "자동" mode counts these instead of letting the
# small AI guess the mode for the whole video (it called a try-on haul a daily vlog).
ACTIVITY_MODE: dict[str, str | None] = {
    "옷 보여주기": "try_on",
    "물건 보여주기": "review",
    "춤": "challenge",
    "운동": "workout",
    "요리": "recipe",
    "먹기·마시기": "cafe",
    "이동·풍경": "travel",
    "이야기·셀카": "daily_vlog",
    "기타": None,
}
ACTIVITIES = tuple(ACTIVITY_MODE)

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
