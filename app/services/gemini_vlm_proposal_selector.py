from dataclasses import dataclass
import os
import re
from time import perf_counter
from typing import Any

import httpx
from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMCallResult,
    VLMProposalSelection,
    VLMProposalSelectionInput,
    VLMProposalSelectionError,
    _validate_selection_input,
    build_vlm_selection_prompt,
)


DEFAULT_GEMINI_VLM_MODEL = "gemini-3.5-flash"
DEFAULT_GEMINI_VLM_TIMEOUT_SECONDS = 30.0
GEMINI_VLM_PROMPT_VERSION = "vlm-proposal-selector-contact-sheet-v0.2"


@dataclass(frozen=True)
class GeminiVLMErrorDiagnostics:
    http_status: int | None
    provider_error_code: str | None
    safe_message: str
    failure_stage: str
    model: str
    image_count: int
    timeout: bool


class GeminiVLMProviderError(RuntimeError):
    def __init__(self, diagnostics: GeminiVLMErrorDiagnostics) -> None:
        super().__init__(diagnostics.safe_message)
        self.diagnostics = diagnostics


class GeminiVLMProposalSelector:
    """Select one existing proposal ID with Gemini multimodal structured output."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        client: Any | None = None,
        model: str = DEFAULT_GEMINI_VLM_MODEL,
        timeout_seconds: float = DEFAULT_GEMINI_VLM_TIMEOUT_SECONDS,
    ) -> None:
        if not isinstance(model, str) or not model.strip():
            raise VLMProposalSelectionError("Gemini model must be set.")
        if timeout_seconds <= 0:
            raise VLMProposalSelectionError("Gemini timeout must be greater than zero.")
        if client is None:
            resolved_key = api_key or os.environ.get("GEMINI_API_KEY")
            if not resolved_key:
                raise VLMProposalSelectionError(
                    "GEMINI_API_KEY is required for the Gemini VLM selector."
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

    def select(self, selection_input: VLMProposalSelectionInput) -> OllamaVLMCallResult:
        _validate_selection_input(selection_input)
        if selection_input.contact_sheets is None:
            raise VLMProposalSelectionError(
                "Gemini VLM feasibility requires proposal contact sheets."
            )
        schema = _response_json_schema()
        prompt = build_vlm_selection_prompt(selection_input, schema=schema)
        contents: list[object] = [prompt]
        contents.extend(
            types.Part.from_bytes(data=sheet.jpeg_bytes, mime_type="image/jpeg")
            for sheet in selection_input.contact_sheets
        )
        image_count = len(selection_input.contact_sheets)
        started = perf_counter()
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    temperature=0.0,
                    max_output_tokens=256,
                    response_mime_type="application/json",
                    response_json_schema=schema,
                    thinking_config=types.ThinkingConfig(thinking_level="minimal"),
                ),
            )
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise self._error(
                "Gemini VLM request timed out.",
                code="TIMEOUT",
                stage="generate_content",
                image_count=image_count,
                timeout=True,
            ) from exc
        except errors.APIError as exc:
            raise self._error(
                _sanitize_provider_message(getattr(exc, "message", None)),
                http_status=_optional_int(getattr(exc, "code", None)),
                code=_optional_string(getattr(exc, "status", None)),
                stage="generate_content",
                image_count=image_count,
            ) from exc
        except Exception as exc:
            raise self._error(
                "Unexpected Gemini VLM client error.",
                code="UNEXPECTED_CLIENT_ERROR",
                stage="generate_content",
                image_count=image_count,
            ) from exc
        latency = perf_counter() - started
        try:
            selection = _parse_selection(response)
        except (ValidationError, ValueError, TypeError) as exc:
            raise self._error(
                "Gemini returned an invalid structured proposal selection.",
                code="STRUCTURED_OUTPUT_ERROR",
                stage="structured_output_parsing",
                image_count=image_count,
            ) from exc
        usage = getattr(response, "usage_metadata", None)
        input_tokens = _optional_int(getattr(usage, "prompt_token_count", None))
        output_tokens = _optional_int(
            getattr(usage, "candidates_token_count", None)
        )
        total_tokens = _optional_int(getattr(usage, "total_token_count", None))
        return OllamaVLMCallResult(
            selection=selection,
            latency_seconds=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            image_count=image_count,
        )

    def _error(
        self,
        message: str,
        *,
        code: str | None,
        stage: str,
        image_count: int,
        http_status: int | None = None,
        timeout: bool = False,
    ) -> GeminiVLMProviderError:
        return GeminiVLMProviderError(
            GeminiVLMErrorDiagnostics(
                http_status=http_status,
                provider_error_code=code,
                safe_message=message,
                failure_stage=stage,
                model=self.model,
                image_count=image_count,
                timeout=timeout,
            )
        )


def _response_json_schema() -> dict[str, Any]:
    return _remove_unsupported_length_keywords(
        VLMProposalSelection.model_json_schema()
    )


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


def _parse_selection(response: Any) -> VLMProposalSelection:
    parsed = getattr(response, "parsed", None)
    if isinstance(parsed, VLMProposalSelection):
        return parsed
    if isinstance(parsed, dict):
        return VLMProposalSelection.model_validate(parsed)
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise ValueError("No structured selection")
    return VLMProposalSelection.model_validate_json(text)


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
