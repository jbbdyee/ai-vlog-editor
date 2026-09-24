from dataclasses import dataclass
import math
from numbers import Real
import re
from typing import Protocol

from app.services.candidate_generator import SceneCandidate
from app.services.memo_detector import EditMemo
from app.services.transcript_scene_retriever import TranscriptBlock


MAX_REASONING_SUMMARY_CHARACTERS = 240
MAX_REASONING_CODE_CHARACTERS = 64
REASONING_CODE_PATTERN = re.compile(r"[A-Z][A-Z0-9_]*")


class SemanticBlockSelectionError(ValueError):
    """Raised when a semantic block selection cannot be trusted."""


@dataclass(frozen=True)
class SemanticBlockSelectionInput:
    memo: EditMemo
    blocks: tuple[TranscriptBlock, ...]


@dataclass(frozen=True)
class SemanticBlockSelection:
    selected_block_id: str
    reasoning_code: str
    reasoning_summary: str


@dataclass(frozen=True)
class ValidatedSemanticBlockSelection:
    selection: SemanticBlockSelection
    selected_block: TranscriptBlock
    candidate: SceneCandidate


class BlockSelector(Protocol):
    """Minimal provider-independent contract for selecting one block ID."""

    def select(
        self, selection_input: SemanticBlockSelectionInput
    ) -> SemanticBlockSelection: ...


def run_block_selector(
    selector: BlockSelector,
    selection_input: SemanticBlockSelectionInput,
    *,
    video_duration_seconds: float,
) -> ValidatedSemanticBlockSelection:
    """Run a selector and validate its untrusted structured result."""
    try:
        selection = selector.select(selection_input)
    except SemanticBlockSelectionError:
        raise
    except Exception as exc:
        raise SemanticBlockSelectionError("Block selector failed.") from exc

    return validate_block_selection(
        selection_input,
        selection,
        video_duration_seconds=video_duration_seconds,
    )


def validate_block_selection(
    selection_input: SemanticBlockSelectionInput,
    selection: SemanticBlockSelection,
    *,
    video_duration_seconds: float,
) -> ValidatedSemanticBlockSelection:
    """Resolve one selected block ID into a validated SceneCandidate."""
    if not isinstance(selection_input, SemanticBlockSelectionInput):
        raise SemanticBlockSelectionError(
            "Selection input must be a SemanticBlockSelectionInput."
        )
    if not isinstance(selection, SemanticBlockSelection):
        raise SemanticBlockSelectionError(
            "Selector output must be a SemanticBlockSelection."
        )

    video_duration = _validate_positive_number(
        video_duration_seconds, "Video duration"
    )
    memo_start = _validate_memo(selection_input.memo, video_duration)
    blocks_by_id = _validate_blocks(
        selection_input.blocks,
        memo_start=memo_start,
        video_duration=video_duration,
    )
    selected_block_id = _validate_non_empty_text(
        selection.selected_block_id, "Selected block ID"
    )
    selected_block = blocks_by_id.get(selected_block_id)
    if selected_block is None:
        raise SemanticBlockSelectionError(
            f"Selected block ID does not exist in the input: {selected_block_id}"
        )

    _validate_reasoning(selection)
    candidate = SceneCandidate(
        window_seconds=selected_block.end_seconds - selected_block.start_seconds,
        start_seconds=selected_block.start_seconds,
        end_seconds=selected_block.end_seconds,
    )
    return ValidatedSemanticBlockSelection(
        selection=selection,
        selected_block=selected_block,
        candidate=candidate,
    )


def _validate_memo(memo: EditMemo, video_duration: float) -> float:
    if not isinstance(memo, EditMemo):
        raise SemanticBlockSelectionError("Memo must be an EditMemo.")
    start = _validate_non_negative_number(memo.start_seconds, "Memo start")
    end = _validate_non_negative_number(memo.end_seconds, "Memo end")
    if start >= end:
        raise SemanticBlockSelectionError("Memo start must be less than memo end.")
    if end > video_duration:
        raise SemanticBlockSelectionError(
            "Memo timestamps exceed the video duration."
        )
    return start


def _validate_blocks(
    blocks: tuple[TranscriptBlock, ...],
    *,
    memo_start: float,
    video_duration: float,
) -> dict[str, TranscriptBlock]:
    if not isinstance(blocks, tuple) or not blocks:
        raise SemanticBlockSelectionError(
            "Selection input must contain at least one transcript block."
        )

    blocks_by_id: dict[str, TranscriptBlock] = {}
    previous_end = 0.0
    for index, block in enumerate(blocks, start=1):
        if not isinstance(block, TranscriptBlock):
            raise SemanticBlockSelectionError(
                "Selection input contains an invalid transcript block."
            )
        block_id = _validate_non_empty_text(block.block_id, f"Block {index} ID")
        if block_id in blocks_by_id:
            raise SemanticBlockSelectionError(f"Duplicate block ID: {block_id}")

        start = _validate_non_negative_number(
            block.start_seconds, f"Block {block_id} start"
        )
        end = _validate_non_negative_number(
            block.end_seconds, f"Block {block_id} end"
        )
        if start >= end:
            raise SemanticBlockSelectionError(
                f"Block {block_id} start must be less than its end."
            )
        if end > video_duration:
            raise SemanticBlockSelectionError(
                f"Block {block_id} timestamps exceed the video duration."
            )
        if end > memo_start:
            raise SemanticBlockSelectionError(
                f"Block {block_id} must end before the edit memo starts."
            )
        if index > 1 and start < previous_end:
            raise SemanticBlockSelectionError(
                "Transcript blocks must be ordered and non-overlapping."
            )
        _validate_non_empty_text(
            block.transcript_text, f"Block {block_id} transcript"
        )

        blocks_by_id[block_id] = block
        previous_end = end
    return blocks_by_id


def _validate_reasoning(selection: SemanticBlockSelection) -> None:
    code = _validate_non_empty_text(selection.reasoning_code, "Reasoning code")
    if len(code) > MAX_REASONING_CODE_CHARACTERS or not REASONING_CODE_PATTERN.fullmatch(
        code
    ):
        raise SemanticBlockSelectionError(
            "Reasoning code must use short uppercase letters, digits, or underscores."
        )

    summary = _validate_non_empty_text(
        selection.reasoning_summary, "Reasoning summary"
    )
    if len(summary) > MAX_REASONING_SUMMARY_CHARACTERS:
        raise SemanticBlockSelectionError(
            "Reasoning summary must not exceed "
            f"{MAX_REASONING_SUMMARY_CHARACTERS} characters."
        )


def _validate_non_empty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SemanticBlockSelectionError(f"{label} must be a non-empty string.")
    if value != value.strip():
        raise SemanticBlockSelectionError(
            f"{label} must not have leading or trailing whitespace."
        )
    return value


def _validate_positive_number(value: object, label: str) -> float:
    number = _validate_number(value, label)
    if number <= 0:
        raise SemanticBlockSelectionError(f"{label} must be greater than zero.")
    return number


def _validate_non_negative_number(value: object, label: str) -> float:
    number = _validate_number(value, label)
    if number < 0:
        raise SemanticBlockSelectionError(f"{label} must not be negative.")
    return number


def _validate_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise SemanticBlockSelectionError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise SemanticBlockSelectionError(f"{label} must be a finite number.")
    return number
