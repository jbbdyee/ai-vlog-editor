from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
import re

from app.services.stt_service import STTResult, TranscriptSegment


@dataclass(frozen=True)
class MemoDetectionRules:
    triggers: tuple[str, ...]
    references: tuple[str, ...]
    actions: tuple[str, ...]


DEFAULT_MEMO_RULES = MemoDetectionRules(
    triggers=("AI야", "에이아이야"),
    references=("방금", "지금"),
    actions=("살려줘",),
)

TRIGGER_SIMILARITY_THRESHOLD = 0.60
MIN_TRIGGER_KEY_LENGTH = 5
MAX_TRIGGER_KEY_LENGTH = 7
MAX_TRIGGER_TOKENS = 2
TOKEN_PATTERN = re.compile(r"[0-9A-Za-z가-힣]+")


class MemoDetectionError(ValueError):
    """Raised when transcript input cannot be evaluated safely."""


@dataclass(frozen=True)
class EditMemo:
    start_seconds: float
    end_seconds: float
    transcript_text: str
    matched_trigger: str
    matched_reference: str
    matched_action: str
    trigger_match_type: str = "normalized_exact"
    trigger_similarity: float = 1.0


@dataclass(frozen=True)
class _TextToken:
    text: str
    normalized: str
    start: int
    end: int


@dataclass(frozen=True)
class _TriggerMatch:
    position: int
    text: str
    match_type: str
    similarity: float
    token_count: int


def detect_edit_memos(
    transcript: STTResult | Iterable[TranscriptSegment],
    *,
    rules: MemoDetectionRules = DEFAULT_MEMO_RULES,
) -> tuple[EditMemo, ...]:
    """Detect at most one rule-based edit memo from each transcript segment."""
    if isinstance(transcript, STTResult):
        segments = transcript.segments
    else:
        try:
            segments = tuple(transcript)
        except TypeError as exc:
            raise MemoDetectionError(
                "Transcript input must be an STTResult or transcript segments."
            ) from exc

    detected: list[EditMemo] = []
    for segment in segments:
        if not isinstance(segment, TranscriptSegment):
            raise MemoDetectionError(
                "Transcript input contains an invalid transcript segment."
            )

        memo = _detect_segment(segment, rules)
        if memo is not None:
            detected.append(memo)

    return tuple(detected)


def _detect_segment(
    segment: TranscriptSegment,
    rules: MemoDetectionRules,
) -> EditMemo | None:
    normalized_text = _normalize_text(segment.text)
    reference = _first_ordered_match(normalized_text, rules.references)
    action = _first_ordered_match(normalized_text, rules.actions)

    if reference is None or action is None:
        return None

    reference_position, matched_reference = reference
    action_position, matched_action = action
    trigger = _match_trigger(segment.text, reference_position, rules.triggers)
    if trigger is None or not trigger.position < reference_position < action_position:
        return None

    return EditMemo(
        start_seconds=_trigger_start_seconds(segment, trigger.text),
        end_seconds=segment.end_seconds,
        transcript_text=segment.text,
        matched_trigger=trigger.text,
        matched_reference=matched_reference,
        matched_action=matched_action,
        trigger_match_type=trigger.match_type,
        trigger_similarity=trigger.similarity,
    )


def _match_trigger(
    text: str,
    reference_position: int,
    trigger_phrases: tuple[str, ...],
) -> _TriggerMatch | None:
    tokens = [token for token in _tokenize(text) if token.end <= reference_position]
    canonical_keys = tuple(_trigger_key(phrase) for phrase in trigger_phrases)
    matches: list[_TriggerMatch] = []

    for token_count in range(1, min(MAX_TRIGGER_TOKENS, len(tokens)) + 1):
        candidate_tokens = tokens[-token_count:]
        candidate_text = " ".join(token.text for token in candidate_tokens)
        candidate_key = _trigger_key(candidate_text)
        if not MIN_TRIGGER_KEY_LENGTH <= len(candidate_key) <= MAX_TRIGGER_KEY_LENGTH:
            continue

        similarity = max(
            SequenceMatcher(None, canonical_key, candidate_key).ratio()
            for canonical_key in canonical_keys
        )
        if similarity < TRIGGER_SIMILARITY_THRESHOLD:
            continue

        matches.append(
            _TriggerMatch(
                position=candidate_tokens[0].start,
                text=candidate_text,
                match_type=(
                    "normalized_exact" if similarity == 1.0 else "similarity"
                ),
                similarity=similarity,
                token_count=token_count,
            )
        )

    return max(
        matches,
        key=lambda match: (
            match.similarity,
            -match.token_count,
            match.position,
        ),
        default=None,
    )


def _first_ordered_match(
    normalized_text: str,
    phrases: tuple[str, ...],
) -> tuple[int, str] | None:
    matches = (
        (normalized_text.find(_normalize_text(phrase)), phrase)
        for phrase in phrases
    )
    return min((match for match in matches if match[0] >= 0), default=None)


def _trigger_start_seconds(
    segment: TranscriptSegment,
    matched_trigger: str,
) -> float:
    normalized_words = [_normalize_text(word.text) for word in segment.words]
    combined_words = "".join(normalized_words)
    trigger_start = combined_words.find(_normalize_text(matched_trigger))
    if trigger_start < 0:
        return segment.start_seconds

    offset = 0
    for word, normalized_word in zip(segment.words, normalized_words):
        word_end = offset + len(normalized_word)
        if trigger_start < word_end:
            return word.start_seconds
        offset = word_end

    return segment.start_seconds


def _tokenize(text: str) -> tuple[_TextToken, ...]:
    tokens: list[_TextToken] = []
    offset = 0
    for match in TOKEN_PATTERN.finditer(text):
        normalized = _normalize_text(match.group())
        tokens.append(
            _TextToken(
                text=match.group(),
                normalized=normalized,
                start=offset,
                end=offset + len(normalized),
            )
        )
        offset += len(normalized)
    return tuple(tokens)


def _trigger_key(text: str) -> str:
    normalized = _normalize_text(text)
    phonetic_parts: list[str] = []
    for character in normalized:
        if character == "a":
            phonetic_parts.append("에이")
        elif character == "i":
            phonetic_parts.append("아이")
        else:
            phonetic_parts.append(character)
    return "".join(phonetic_parts)


def _normalize_text(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())
