"""Rule-based natural-language edit request -> suggested scene selection (no LLM, no DB writes).

The suggestion only proposes an ordered list of active candidate IDs with reasons. The user applies
it to the editable draft and saves through the existing scene-edit-plan endpoint, so the stored
plan, render and evaluation contracts are unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Sequence
from uuid import UUID

from backend.app.services.project_scene_candidates import ActiveCandidateSummary

MAX_REQUEST_LENGTH = 300
CATEGORIES = {
    "reaction": (("리액션", "반응", "웃", "감탄", "놀라", "신나", "재밌", "재미"), {"TRANSCRIPT_REACTION_CUE"}, "리액션"),
    "motion": (("움직", "춤", "댄스", "액션", "활동", "동작", "역동"), {"VISUAL_ACTIVITY"}, "움직임"),
    "talk": (("말하", "대화", "설명", "이야기", "멘트", "토크", "목소리"), {"TRANSCRIPT_STRUCTURE"}, "대화"),
}
STOPWORDS = {
    "장면", "영상", "부분", "구간", "편집", "넣어", "넣어줘", "넣고", "만들어", "만들어줘", "해줘", "줘", "주세요", "위주", "위주로",
    "중심", "중심으로", "정도", "이내", "이내로", "안으로", "짧게", "길게", "최대", "최소", "전부", "모두", "다", "시간순", "순서대로",
    "역순", "거꾸로", "나오는", "들어간", "포함", "포함해서", "포함해줘", "있는", "제외", "빼고", "없이", "말고", "그리고", "좀",
    "하이라이트", "브이로그", "골라", "골라줘", "선택", "선택해줘", "앞부분", "뒷부분", "처음", "마지막", "개", "초", "분",
    "먼저", "그다음", "다음", "보여줘", "보여", "나오는", "장면만", "영상만", "잔잔하게", "신나게", "감성적으로",
    "보이는", "보이게", "보인", "많은", "많이", "나온", "나오게", "있게",
}
JOSA = ("에서는", "으로는", "이랑", "에서", "으로", "부터", "까지", "하고", "랑", "은", "는", "이", "가", "을", "를", "에", "로", "와", "과", "만", "도", "의")


@dataclass(frozen=True)
class EditRequestIntent:
    target_seconds: float | None = None
    max_count: int | None = None
    keywords: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    order: str = "chronological"
    select_all: bool = False


@dataclass(frozen=True)
class SuggestedScene:
    candidate_id: UUID
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class EditSuggestion:
    intent: EditRequestIntent
    scenes: tuple[SuggestedScene, ...]
    total_seconds: float
    notes: tuple[str, ...] = field(default_factory=tuple)


def _stem(token: str) -> str:
    for suffix in JOSA:
        if token.endswith(suffix) and len(token) - len(suffix) >= 2:
            return token[: -len(suffix)]
    return token


SHORT_JOSA = set("이가은는을를에도만랑")


def _matches(word: str, speech: str) -> bool:
    """Raw token or its josa-stripped stem appears in the scene's speech (or visual caption/tags).

    One-syllable nouns ("물이" → "물") only match at a word start, so "물" does not match "건물".
    """
    if not word:
        return False
    if word in speech or _stem(word) in speech:
        return True
    if len(word) == 2 and word[1] in SHORT_JOSA:
        return re.search(rf"(?<![가-힣]){re.escape(word[0])}", speech) is not None
    return False


def _has_cue(text: str, cue: str) -> bool:
    return bool(re.search("(?<!리)액션", text)) if cue == "액션" else cue in text


def parse_edit_request(text: str) -> EditRequestIntent:
    text = " ".join(text.split())[:MAX_REQUEST_LENGTH]
    target = None
    if minutes := re.search(r"(\d+(?:\.\d+)?)\s*분", text):
        target = float(minutes.group(1)) * 60
    if seconds := re.search(r"(\d+(?:\.\d+)?)\s*초", text):
        target = (target or 0) + float(seconds.group(1))
    count = re.search(r"(\d+)\s*(?:개|컷|장면)", text)
    excluded: list[str] = []
    for match in re.finditer(r"([가-힣A-Za-z0-9]+)\s*(?:은|는|이|가|을|를)?\s*(?:빼고|제외|없이|말고)", text):
        excluded.append(_stem(match.group(1)))
    # "동물이 나오는 장면 빼고" → exclude "동물", not the word "장면".
    for match in re.finditer(r"([가-힣A-Za-z0-9]+?)(?:이|가|은|는|을|를)?\s+(?:나오는|보이는|있는|들어간)\s+장면\S*\s*(?:빼고|제외|없이|말고)", text):
        excluded.append(_stem(match.group(1)))
    excluded = [word for word in excluded if word not in STOPWORDS]
    quoted = re.findall(r"[\"'“‘]([^\"'”’]+)[\"'”’]", text)
    keywords: list[str] = [item.strip() for item in quoted if item.strip()]
    categories = [name for name, (cues, _, _) in CATEGORIES.items() if any(_has_cue(text, cue) for cue in cues)]
    category_cues = {cue for cues, _, _ in CATEGORIES.values() for cue in cues}
    unquoted = re.sub(r"[\"'“‘][^\"'”’]+[\"'”’]", " ", text)
    for raw in re.findall(r"[가-힣A-Za-z]{2,}", unquoted):
        token = _stem(raw)
        if (token in STOPWORDS or raw in STOPWORDS or token in excluded or len(token) < 2
                or any(token.startswith(cue) or cue.startswith(token) for cue in category_cues)):
            continue
        if all(_stem(existing) != token for existing in keywords):
            keywords.append(raw)
    order = "reverse" if re.search(r"역순|거꾸로", text) else "chronological"
    return EditRequestIntent(
        target_seconds=target if target and target > 0 else None,
        max_count=int(count.group(1)) if count and int(count.group(1)) > 0 else None,
        keywords=tuple(keywords[:8]), excluded=tuple(excluded[:8]), categories=tuple(categories),
        order=order, select_all=bool(re.search(r"전부|모두|전체|다 넣", text)),
    )


def suggest_edit(text: str, candidates: Sequence[ActiveCandidateSummary]) -> EditSuggestion:
    intent = parse_edit_request(text)
    notes: list[str] = []
    scored = []
    for candidate in candidates:
        speech = candidate.transcript_text or ""
        if any(_matches(word, speech) for word in intent.excluded):
            continue
        types = {item.evidence_type for item in candidate.evidence}
        reasons: list[str] = []
        score = 0.0
        for word in intent.keywords:
            if _matches(word, speech):
                score += 3; reasons.append(f"'{_stem(word) if _stem(word) in speech else word}' 언급")
        for name in intent.categories:
            _, evidence_types, label = CATEGORIES[name]
            if types & evidence_types:
                score += 2; reasons.append(f"{label} 근거")
        scored.append((score, candidate, reasons))
    if intent.excluded:
        notes.append("제외 조건: " + ", ".join(intent.excluded))
    filtering = bool(intent.keywords or intent.categories) and not intent.select_all
    pool = [item for item in scored if item[0] > 0] if filtering else scored
    if filtering and not pool:
        notes.append("요청과 일치하는 장면을 찾지 못해 전체 후보에서 골랐습니다.")
        pool = scored
    unmatched = [word for word in intent.keywords if not any(_matches(word, c.transcript_text or "") for _, c, _ in scored)]
    if unmatched:
        notes.append("전사에서 찾지 못한 단어: " + ", ".join(unmatched))
    # Highest score first, then earlier scenes; length/count limits are applied in that order.
    pool.sort(key=lambda item: (-item[0], str(item[1].source_video_id), float(item[1].start_seconds)))
    chosen, total = [], 0.0
    for score, candidate, reasons in pool:
        length = float(candidate.end_seconds) - float(candidate.start_seconds)
        if intent.max_count is not None and len(chosen) >= intent.max_count:
            break
        if intent.target_seconds is not None and chosen and total + length > intent.target_seconds:
            continue
        chosen.append((candidate, reasons or ["요청 조건과 무관 · 길이·개수 기준으로 포함"]))
        total += length
    if intent.target_seconds is not None and total > intent.target_seconds:
        notes.append(f"가장 짧은 조합도 목표 {intent.target_seconds:g}초를 넘습니다.")
    chosen.sort(key=lambda item: (str(item[0].source_video_id), float(item[0].start_seconds)),
                reverse=intent.order == "reverse")
    return EditSuggestion(intent, tuple(SuggestedScene(c.candidate_id, tuple(r)) for c, r in chosen), round(total, 3), tuple(notes))
