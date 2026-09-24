from dataclasses import dataclass
from enum import Enum
import json
import os
import re
from time import perf_counter
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.services.semantic_block_selector import (
    MAX_REASONING_SUMMARY_CHARACTERS,
    SemanticBlockSelection,
    SemanticBlockSelectionError,
    SemanticBlockSelectionInput,
)


DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"
DEFAULT_TIMEOUT_SECONDS = 30.0
PROMPT_VERSION = "semantic-block-gemini-v0.1"

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


class GeminiSelectionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_block_id: str = Field(min_length=1)
    reasoning_code: ReasoningCode
    reasoning_summary: str = Field(
        min_length=1,
        max_length=MAX_REASONING_SUMMARY_CHARACTERS,
    )


class GeminiSemanticBlockSelectorError(SemanticBlockSelectionError):
    """Base error for Gemini Provider failures before deterministic validation."""


class GeminiSelectorConfigurationError(GeminiSemanticBlockSelectorError):
    """Raised when the Gemini selector cannot be configured safely."""


class GeminiSelectorTimeoutError(GeminiSemanticBlockSelectorError):
    """Raised when the Gemini request times out."""


class GeminiSelectorAPIError(GeminiSemanticBlockSelectorError):
    """Raised when the Gemini API request fails."""

    def __init__(self, diagnostics: "GeminiProviderErrorDiagnostics") -> None:
        super().__init__("Gemini semantic block selection request failed.")
        self.diagnostics = diagnostics


class GeminiSelectorResponseError(GeminiSemanticBlockSelectorError):
    """Raised when Gemini returns no usable structured selection."""


@dataclass(frozen=True)
class GeminiSelectorCallMetadata:
    latency_seconds: float
    response_id: str | None
    model: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None


@dataclass(frozen=True)
class GeminiProviderErrorDiagnostics:
    http_status: int | None
    provider_error_code: str | None
    safe_message: str
    failure_stage: str
    model: str


class GeminiSemanticBlockSelector:
    """Select one TranscriptBlock through Gemini Structured Outputs."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        model: str = DEFAULT_GEMINI_MODEL,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise GeminiSelectorConfigurationError("Gemini model must be set.")
        if timeout_seconds <= 0:
            raise GeminiSelectorConfigurationError(
                "Gemini timeout must be greater than zero."
            )

        if client is None:
            resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
            if not resolved_key:
                raise GeminiSelectorConfigurationError(
                    "GEMINI_API_KEY is required for the Gemini selector."
                )
            client = genai.Client(
                api_key=resolved_key,
                http_options=types.HttpOptions(
                    timeout=int(float(timeout_seconds) * 1000)
                ),
            )

        self._client = client
        self.model = model
        self.timeout_seconds = float(timeout_seconds)
        self.last_call_metadata: GeminiSelectorCallMetadata | None = None

    def select(
        self, selection_input: SemanticBlockSelectionInput
    ) -> SemanticBlockSelection:
        user_prompt = build_user_prompt(selection_input)
        started_at = perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=user_prompt,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_PROMPT,
                    temperature=0.0,
                    max_output_tokens=256,
                    response_mime_type="application/json",
                    response_json_schema=build_response_json_schema(),
                    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                ),
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise GeminiSelectorTimeoutError(
                "Gemini semantic block selection timed out."
            ) from exc
        except errors.APIError as exc:
            raise GeminiSelectorAPIError(
                _build_provider_error_diagnostics(exc, model=self.model)
            ) from exc
        except Exception as exc:
            raise GeminiSelectorAPIError(
                GeminiProviderErrorDiagnostics(
                    http_status=None,
                    provider_error_code=None,
                    safe_message="Unexpected Gemini client error.",
                    failure_stage="generate_content",
                    model=self.model,
                )
            ) from exc
        latency_seconds = perf_counter() - started_at

        self.last_call_metadata = _build_call_metadata(
            response,
            latency_seconds=latency_seconds,
            requested_model=self.model,
        )
        parsed = _parse_selection_payload(response)
        return SemanticBlockSelection(
            selected_block_id=parsed.selected_block_id,
            reasoning_code=parsed.reasoning_code.value,
            reasoning_summary=parsed.reasoning_summary,
        )


def build_user_prompt(selection_input: SemanticBlockSelectionInput) -> str:
    """Serialize only the memo text and selectable block fields for Gemini."""
    if not isinstance(selection_input, SemanticBlockSelectionInput):
        raise GeminiSelectorConfigurationError(
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


def build_response_json_schema() -> dict[str, Any]:
    """Build Gemini's supported JSON Schema while preserving strict objects."""
    schema = GeminiSelectionPayload.model_json_schema()
    return _remove_unsupported_length_keywords(schema)


def _remove_unsupported_length_keywords(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _remove_unsupported_length_keywords(item)
            for key, item in value.items()
            if key not in {"minLength", "maxLength"}
        }
    if isinstance(value, list):
        return [_remove_unsupported_length_keywords(item) for item in value]
    return value


def _parse_selection_payload(response: Any) -> GeminiSelectionPayload:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, GeminiSelectionPayload):
        return parsed
    if isinstance(parsed, dict):
        try:
            return GeminiSelectionPayload.model_validate(parsed)
        except ValidationError as exc:
            raise GeminiSelectorResponseError(
                "Gemini returned an invalid structured block selection."
            ) from exc

    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise GeminiSelectorResponseError(
            "Gemini returned no structured block selection."
        )
    try:
        return GeminiSelectionPayload.model_validate_json(text)
    except (ValidationError, ValueError) as exc:
        raise GeminiSelectorResponseError(
            "Gemini returned an invalid structured block selection."
        ) from exc


def _build_call_metadata(
    response: Any,
    *,
    latency_seconds: float,
    requested_model: str,
) -> GeminiSelectorCallMetadata:
    usage = getattr(response, "usage_metadata", None)
    return GeminiSelectorCallMetadata(
        latency_seconds=latency_seconds,
        response_id=_optional_string(getattr(response, "response_id", None)),
        model=_optional_string(getattr(response, "model_version", None))
        or requested_model,
        input_tokens=_optional_int(getattr(usage, "prompt_token_count", None)),
        output_tokens=_optional_int(
            getattr(usage, "candidates_token_count", None)
        ),
        total_tokens=_optional_int(getattr(usage, "total_token_count", None)),
    )


def _build_provider_error_diagnostics(
    error: errors.APIError,
    *,
    model: str,
) -> GeminiProviderErrorDiagnostics:
    return GeminiProviderErrorDiagnostics(
        http_status=_optional_int(getattr(error, "code", None)),
        provider_error_code=_optional_string(getattr(error, "status", None)),
        safe_message=_sanitize_provider_message(getattr(error, "message", None)),
        failure_stage="generate_content",
        model=model,
    )


def _sanitize_provider_message(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return "Gemini Provider returned no error message."

    message = " ".join(value.split())
    configured_key = os.environ.get("GEMINI_API_KEY")
    if configured_key:
        message = message.replace(configured_key, "[REDACTED]")
    message = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(
        r"(?i)(api[_ -]?key\s*[:=]\s*)[^\s,;]+",
        r"\1[REDACTED]",
        message,
    )
    message = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "[REDACTED]", message)
    return message[:500]


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None
