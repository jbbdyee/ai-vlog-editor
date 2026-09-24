from dataclasses import dataclass
from enum import Enum
import json
import os
from time import perf_counter
from typing import Any

from openai import APIError, APITimeoutError, OpenAI
from pydantic import BaseModel, ConfigDict, Field

from app.services.semantic_block_selector import (
    MAX_REASONING_SUMMARY_CHARACTERS,
    SemanticBlockSelection,
    SemanticBlockSelectionError,
    SemanticBlockSelectionInput,
)


DEFAULT_OPENAI_MODEL = "gpt-6-luna"
DEFAULT_TIMEOUT_SECONDS = 30.0
PROMPT_VERSION = "semantic-block-openai-v0.1"

SYSTEM_PROMPT = """You select exactly one transcript block that is most likely to contain the event or utterance referenced by the user's edit memo.

Rules:
- Select one block_id from the provided blocks.
- Do not simply choose the most recent block.
- When the memo is ambiguous, such as "방금 장면", use eventfulness, reactions, and transcript context to select the most likely referenced event.
- Use only a block_id that exists in the input.
- Do not guess or infer Ground Truth.
- Do not create or modify timestamps.
- Return one allowed reasoning_code and a brief reasoning_summary of at most 240 characters.
- If evidence is weak, select the best available block and use INSUFFICIENT_TRANSCRIPT_EVIDENCE.
"""


class ReasoningCode(str, Enum):
    RECENT_EVENT_REACTION = "RECENT_EVENT_REACTION"
    EARLIER_SALIENT_EVENT = "EARLIER_SALIENT_EVENT"
    MULTI_SEGMENT_EVENT = "MULTI_SEGMENT_EVENT"
    INSUFFICIENT_TRANSCRIPT_EVIDENCE = "INSUFFICIENT_TRANSCRIPT_EVIDENCE"


class OpenAISelectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_block_id: str = Field(min_length=1)
    reasoning_code: ReasoningCode
    reasoning_summary: str = Field(
        min_length=1,
        max_length=MAX_REASONING_SUMMARY_CHARACTERS,
    )


class OpenAISemanticBlockSelectorError(SemanticBlockSelectionError):
    """Base error for OpenAI Provider failures before deterministic validation."""


class OpenAISelectorConfigurationError(OpenAISemanticBlockSelectorError):
    """Raised when the selector cannot be configured safely."""


class OpenAISelectorTimeoutError(OpenAISemanticBlockSelectorError):
    """Raised when the OpenAI request times out."""


class OpenAISelectorAPIError(OpenAISemanticBlockSelectorError):
    """Raised when the OpenAI API request fails."""


class OpenAISelectorResponseError(OpenAISemanticBlockSelectorError):
    """Raised when the Provider response has no usable structured selection."""


@dataclass(frozen=True)
class OpenAISelectorCallMetadata:
    latency_seconds: float
    response_id: str | None
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


class OpenAISemanticBlockSelector:
    """Select one TranscriptBlock through OpenAI Responses Structured Outputs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: OpenAI | None = None,
        model: str = DEFAULT_OPENAI_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise OpenAISelectorConfigurationError("OpenAI model must be set.")
        if timeout_seconds <= 0:
            raise OpenAISelectorConfigurationError(
                "OpenAI timeout must be greater than zero."
            )

        if client is None:
            resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
            if not resolved_key:
                raise OpenAISelectorConfigurationError(
                    "OPENAI_API_KEY is required for the OpenAI selector."
                )
            client = OpenAI(api_key=resolved_key, timeout=timeout_seconds)

        self._client = client
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.last_call_metadata: OpenAISelectorCallMetadata | None = None

    def select(
        self, selection_input: SemanticBlockSelectionInput
    ) -> SemanticBlockSelection:
        user_prompt = build_user_prompt(selection_input)
        started_at = perf_counter()
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=SYSTEM_PROMPT,
                input=user_prompt,
                text_format=OpenAISelectionPayload,
                reasoning={"effort": "low"},
                max_output_tokens=256,
                store=False,
                timeout=self.timeout_seconds,
            )
        except APITimeoutError as exc:
            raise OpenAISelectorTimeoutError(
                "OpenAI semantic block selection timed out."
            ) from exc
        except APIError as exc:
            raise OpenAISelectorAPIError(
                "OpenAI semantic block selection request failed."
            ) from exc
        except Exception as exc:
            raise OpenAISelectorAPIError(
                "OpenAI semantic block selection request failed."
            ) from exc
        latency_seconds = perf_counter() - started_at

        self.last_call_metadata = _build_call_metadata(
            response,
            latency_seconds=latency_seconds,
            requested_model=self.model,
        )
        refusal = _find_refusal(response)
        if refusal is not None:
            raise OpenAISelectorResponseError(
                f"OpenAI refused semantic block selection: {refusal}"
            )

        parsed = getattr(response, "output_parsed", None)
        if not isinstance(parsed, OpenAISelectionPayload):
            raise OpenAISelectorResponseError(
                "OpenAI returned no valid structured block selection."
            )

        return SemanticBlockSelection(
            selected_block_id=parsed.selected_block_id,
            reasoning_code=parsed.reasoning_code.value,
            reasoning_summary=parsed.reasoning_summary,
        )


def build_user_prompt(selection_input: SemanticBlockSelectionInput) -> str:
    """Serialize only the memo text and selectable block fields for OpenAI."""
    if not isinstance(selection_input, SemanticBlockSelectionInput):
        raise OpenAISelectorConfigurationError(
            "Selection input must be a SemanticBlockSelectionInput."
        )

    payload = {
        "prompt_version": PROMPT_VERSION,
        "edit_memo": selection_input.memo.transcript_text,
        "blocks": [
            {
                "block_id": block.block_id,
                "start_seconds": block.start_seconds,
                "end_seconds": block.end_seconds,
                "transcript_text": block.transcript_text,
            }
            for block in selection_input.blocks
        ],
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _find_refusal(response: Any) -> str | None:
    for output in getattr(response, "output", ()) or ():
        for content in getattr(output, "content", ()) or ():
            if getattr(content, "type", None) == "refusal":
                refusal = getattr(content, "refusal", None)
                return refusal if isinstance(refusal, str) and refusal else "refused"
    return None


def _build_call_metadata(
    response: Any,
    *,
    latency_seconds: float,
    requested_model: str,
) -> OpenAISelectorCallMetadata:
    usage = getattr(response, "usage", None)
    return OpenAISelectorCallMetadata(
        latency_seconds=latency_seconds,
        response_id=_optional_string(getattr(response, "id", None)),
        model=_optional_string(getattr(response, "model", None)) or requested_model,
        input_tokens=_optional_int(getattr(usage, "input_tokens", None)),
        output_tokens=_optional_int(getattr(usage, "output_tokens", None)),
        total_tokens=_optional_int(getattr(usage, "total_tokens", None)),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
