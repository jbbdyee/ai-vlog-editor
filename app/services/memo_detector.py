from collections.abc import Iterable
from dataclasses import dataclass

from app.services.stt_service import STTResult, TranscriptSegment


@dataclass(frozen=True)
class MemoDetectionRules:
    triggers: tuple[str, ...]
    references: tuple[str, ...]
    actions: tuple[str, ...]


DEFAULT_MEMO_RULES = MemoDetectionRules(
    triggers=("AI야", "에이아이야", "에이아이아"),
    references=("방금", "지금"),
    actions=("살려줘",),
)


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
    trigger = _first_ordered_match(normalized_text, rules.triggers)
    reference = _first_ordered_match(normalized_text, rules.references)
    action = _first_ordered_match(normalized_text, rules.actions)

    if trigger is None or reference is None or action is None:
        return None

    trigger_position, matched_trigger = trigger
    reference_position, matched_reference = reference
    action_position, matched_action = action
    if not trigger_position < reference_position < action_position:
        return None

    return EditMemo(
        start_seconds=_trigger_start_seconds(segment, matched_trigger),
        end_seconds=segment.end_seconds,
        transcript_text=segment.text,
        matched_trigger=matched_trigger,
        matched_reference=matched_reference,
        matched_action=matched_action,
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


def _normalize_text(text: str) -> str:
    return "".join(character for character in text.casefold() if character.isalnum())
