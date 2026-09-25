import base64
from dataclasses import dataclass
from enum import Enum
import json
import math
from numbers import Real
import socket
import time
from typing import Protocol
from urllib import error, request

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from app.services.candidate_generator import SceneCandidate
from app.services.proposal_contact_sheets import (
    ProposalContactSheet,
    ProposalContactSheetError,
    validate_proposal_contact_sheets,
)
from app.services.scene_boundary_proposals import SceneBoundaryProposal


DEFAULT_OLLAMA_ENDPOINT = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen3-vl:4b"
DEFAULT_OLLAMA_CONTEXT_SIZE = 16_384
PROMPT_VERSION = "vlm-proposal-selector-v0.1"
MAX_REASONING_SUMMARY_CHARACTERS = 240


class VLMProposalSelectionError(ValueError):
    """Raised when provider output cannot be safely used."""


class OllamaVLMProviderError(RuntimeError):
    """Raised when the local Ollama provider call fails."""

    def __init__(
        self,
        safe_message: str,
        *,
        http_status: int | None = None,
        provider_code: str | None = None,
        failure_stage: str = "provider_request",
        model: str | None = None,
        image_count: int | None = None,
        num_ctx: int | None = None,
        timeout: bool = False,
    ) -> None:
        super().__init__(safe_message)
        self.safe_message = safe_message
        self.http_status = http_status
        self.provider_code = provider_code
        self.failure_stage = failure_stage
        self.model = model
        self.image_count = image_count
        self.num_ctx = num_ctx
        self.timeout = timeout

    def with_request_context(
        self, *, model: str, image_count: int, num_ctx: int
    ) -> "OllamaVLMProviderError":
        return OllamaVLMProviderError(
            self.safe_message,
            http_status=self.http_status,
            provider_code=self.provider_code,
            failure_stage=self.failure_stage,
            model=model,
            image_count=image_count,
            num_ctx=num_ctx,
            timeout=self.timeout,
        )


class ProposalReasoningCode(str, Enum):
    EVENT_AND_REACTION_CONNECTED = "EVENT_AND_REACTION_CONNECTED"
    LONG_CONTEXT_REQUIRED = "LONG_CONTEXT_REQUIRED"
    INSUFFICIENT_VISUAL_EVIDENCE = "INSUFFICIENT_VISUAL_EVIDENCE"
    AMBIGUOUS_EVENT = "AMBIGUOUS_EVENT"
    NO_RELEVANT_PROPOSAL = "NO_RELEVANT_PROPOSAL"


ABSTAIN_CODES = frozenset(
    {
        ProposalReasoningCode.INSUFFICIENT_VISUAL_EVIDENCE,
        ProposalReasoningCode.AMBIGUOUS_EVENT,
        ProposalReasoningCode.NO_RELEVANT_PROPOSAL,
    }
)


class VLMProposalSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selected_proposal_id: str | None
    reasoning_code: ProposalReasoningCode
    reasoning_summary: str

    @field_validator("selected_proposal_id")
    @classmethod
    def validate_selected_id(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or value != value.strip()):
            raise ValueError("selected_proposal_id must be null or a trimmed ID")
        return value

    @field_validator("reasoning_summary")
    @classmethod
    def validate_summary(cls, value: str) -> str:
        if not value.strip() or value != value.strip():
            raise ValueError("reasoning_summary must be short non-empty text")
        if len(value) > MAX_REASONING_SUMMARY_CHARACTERS:
            raise ValueError("reasoning_summary is too long")
        return value

    @model_validator(mode="after")
    def validate_selection_state(self) -> "VLMProposalSelection":
        abstains = self.reasoning_code in ABSTAIN_CODES
        if abstains != (self.selected_proposal_id is None):
            raise ValueError("Abstain codes require null; selection codes require an ID")
        return self


@dataclass(frozen=True)
class VLMProposalSelectionInput:
    edit_memo_transcript: str
    selected_block_id: str
    selected_block_text: str
    proposals: tuple[SceneBoundaryProposal, ...]
    contact_sheets: tuple[ProposalContactSheet, ...] | None = None


@dataclass(frozen=True)
class ValidatedVLMProposalSelection:
    selection: VLMProposalSelection
    selected_proposal: SceneBoundaryProposal | None
    candidate: SceneCandidate | None


@dataclass(frozen=True)
class OllamaVLMCallResult:
    selection: VLMProposalSelection
    latency_seconds: float
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    image_count: int


class HTTPTransport(Protocol):
    def post_json(self, url: str, payload: dict[str, object], timeout: float) -> dict[str, object]: ...


class UrllibHTTPTransport:
    def post_json(self, url: str, payload: dict[str, object], timeout: float) -> dict[str, object]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            provider_code, safe_message = _safe_provider_error(detail, exc.code)
            raise OllamaVLMProviderError(
                safe_message,
                http_status=exc.code,
                provider_code=provider_code,
                failure_stage="provider_request",
            ) from exc
        except (TimeoutError, socket.timeout) as exc:
            raise OllamaVLMProviderError(
                "Ollama request timed out.",
                provider_code="TIMEOUT",
                failure_stage="provider_request",
                timeout=True,
            ) from exc
        except error.URLError as exc:
            timed_out = isinstance(exc.reason, (TimeoutError, socket.timeout))
            raise OllamaVLMProviderError(
                "Ollama request timed out."
                if timed_out
                else "Could not connect to Ollama.",
                provider_code="TIMEOUT" if timed_out else "CONNECTION_ERROR",
                failure_stage="provider_request",
                timeout=timed_out,
            ) from exc
        try:
            parsed = json.loads(raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OllamaVLMProviderError(
                "Ollama returned invalid JSON.",
                provider_code="INVALID_PROVIDER_RESPONSE",
                failure_stage="provider_response",
            ) from exc
        if not isinstance(parsed, dict):
            raise OllamaVLMProviderError(
                "Ollama returned an invalid response object.",
                provider_code="INVALID_PROVIDER_RESPONSE",
                failure_stage="provider_response",
            )
        return parsed


class OllamaVLMProposalSelector:
    def __init__(
        self,
        *,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        model: str = DEFAULT_OLLAMA_MODEL,
        timeout_seconds: float = 120.0,
        transport: HTTPTransport | None = None,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.transport = transport or UrllibHTTPTransport()

    def select(self, selection_input: VLMProposalSelectionInput) -> OllamaVLMCallResult:
        _validate_selection_input(selection_input)
        payload, image_count = _build_request_payload(selection_input, self.model)
        started = time.perf_counter()
        try:
            response = self.transport.post_json(
                f"{self.endpoint}/api/chat", payload, self.timeout_seconds
            )
        except OllamaVLMProviderError as exc:
            raise exc.with_request_context(
                model=self.model,
                image_count=image_count,
                num_ctx=DEFAULT_OLLAMA_CONTEXT_SIZE,
            ) from exc
        latency = time.perf_counter() - started
        try:
            message = response["message"]
            if not isinstance(message, dict):
                raise TypeError
            content = message["content"]
            if not isinstance(content, str):
                raise TypeError
            selection = VLMProposalSelection.model_validate_json(content)
        except (KeyError, TypeError, ValidationError) as exc:
            raise OllamaVLMProviderError(
                "Ollama structured output could not be parsed.",
                provider_code="STRUCTURED_OUTPUT_ERROR",
                failure_stage="structured_output_parsing",
                model=self.model,
                image_count=image_count,
                num_ctx=DEFAULT_OLLAMA_CONTEXT_SIZE,
            ) from exc
        input_tokens = _optional_token_count(response.get("prompt_eval_count"))
        output_tokens = _optional_token_count(response.get("eval_count"))
        total_tokens = (
            input_tokens + output_tokens
            if input_tokens is not None and output_tokens is not None
            else None
        )
        return OllamaVLMCallResult(
            selection=selection,
            latency_seconds=latency,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            image_count=image_count,
        )


def validate_vlm_proposal_selection(
    selection_input: VLMProposalSelectionInput,
    selection: VLMProposalSelection,
    *,
    video_duration_seconds: float,
    memo_start_seconds: float,
) -> ValidatedVLMProposalSelection:
    """Resolve only a stored proposal ID; never accept model timestamps."""
    _validate_selection_input(selection_input)
    if not isinstance(selection, VLMProposalSelection):
        raise VLMProposalSelectionError("Selection must be a VLMProposalSelection.")
    duration = _positive_number(video_duration_seconds, "Video duration")
    memo_start = _bounded_time(memo_start_seconds, duration, "Memo start")
    proposals_by_id: dict[str, SceneBoundaryProposal] = {}
    for proposal in selection_input.proposals:
        _validate_proposal_manifest(
            proposal,
            selected_block_id=selection_input.selected_block_id,
            video_duration=duration,
            memo_start=memo_start,
        )
        if proposal.proposal_id in proposals_by_id:
            raise VLMProposalSelectionError(
                f"Duplicate proposal ID: {proposal.proposal_id}"
            )
        proposals_by_id[proposal.proposal_id] = proposal

    if selection.selected_proposal_id is None:
        return ValidatedVLMProposalSelection(selection, None, None)
    selected = proposals_by_id.get(selection.selected_proposal_id)
    if selected is None:
        raise VLMProposalSelectionError(
            f"Selected proposal ID does not exist: {selection.selected_proposal_id}"
        )
    return ValidatedVLMProposalSelection(
        selection=selection,
        selected_proposal=selected,
        candidate=SceneCandidate(
            window_seconds=selected.end_seconds - selected.start_seconds,
            start_seconds=selected.start_seconds,
            end_seconds=selected.end_seconds,
        ),
    )


def _build_request_payload(
    selection_input: VLMProposalSelectionInput, model: str
) -> tuple[dict[str, object], int]:
    proposal_lines: list[str] = []
    images: list[str] = []
    contact_sheets = selection_input.contact_sheets
    for proposal_index, proposal in enumerate(selection_input.proposals):
        frame_descriptions: list[str] = []
        for frame in proposal.frame_samples:
            frame_descriptions.append(
                f"{frame.frame_id}@{frame.timestamp_seconds:.3f}s"
            )
            if contact_sheets is None:
                images.append(base64.b64encode(frame.jpeg_bytes).decode("ascii"))
        proposal_lines.append(
            f"- {proposal.proposal_id}: {proposal.start_seconds:.3f}s~"
            f"{proposal.end_seconds:.3f}s; frames in image order: "
            + ", ".join(frame_descriptions)
        )
        if contact_sheets is not None:
            images.append(
                base64.b64encode(contact_sheets[proposal_index].jpeg_bytes).decode(
                    "ascii"
                )
            )
    schema = VLMProposalSelection.model_json_schema()
    prompt = (
        "Choose exactly one proposal that best contains the event referenced by the "
        "user's edit memo, using the selected transcript context and each proposal's "
        "ordered frames. Do not prefer a proposal merely because it is shortest, "
        "longest, or most recent. If none is supportable, abstain with an allowed "
        "abstain code and null selected_proposal_id. Select only an ID listed below. "
        "Do not create timestamps. Keep reasoning_summary under 240 characters."
        + (
            " Each proposal image is one horizontal contact sheet ordered left to "
            "right as early, middle, and late frames.\n\n"
            if contact_sheets is not None
            else "\n\n"
        )
        + f"Edit memo: {selection_input.edit_memo_transcript}\n"
        f"Selected transcript block ({selection_input.selected_block_id}): "
        f"{selection_input.selected_block_text}\n"
        "Proposals and image order:\n"
        + "\n".join(proposal_lines)
        + "\n\nReturn JSON matching this schema:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    return (
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt, "images": images}],
            "stream": False,
            "format": schema,
            "options": {
                "temperature": 0.0,
                "num_ctx": DEFAULT_OLLAMA_CONTEXT_SIZE,
            },
        },
        len(images),
    )


def _validate_selection_input(value: VLMProposalSelectionInput) -> None:
    if not isinstance(value, VLMProposalSelectionInput):
        raise VLMProposalSelectionError(
            "Selection input must be a VLMProposalSelectionInput."
        )
    for label, text in (
        ("Edit memo transcript", value.edit_memo_transcript),
        ("Selected block ID", value.selected_block_id),
        ("Selected block text", value.selected_block_text),
    ):
        if not isinstance(text, str) or not text.strip():
            raise VLMProposalSelectionError(f"{label} must be non-empty text.")
    if not isinstance(value.proposals, tuple) or not 3 <= len(value.proposals) <= 6:
        raise VLMProposalSelectionError("Selection input requires 3 to 6 proposals.")
    for proposal in value.proposals:
        if not isinstance(proposal, SceneBoundaryProposal):
            raise VLMProposalSelectionError("Selection input contains an invalid proposal.")
        if proposal.source_block_id != value.selected_block_id:
            raise VLMProposalSelectionError("Proposal source block does not match input.")
        if len(proposal.frame_samples) != 3:
            raise VLMProposalSelectionError("Each proposal requires exactly three frames.")
    if value.contact_sheets is not None:
        try:
            validate_proposal_contact_sheets(value.proposals, value.contact_sheets)
        except ProposalContactSheetError as exc:
            raise VLMProposalSelectionError(str(exc)) from exc


def _validate_proposal_manifest(
    proposal: SceneBoundaryProposal,
    *,
    selected_block_id: str,
    video_duration: float,
    memo_start: float,
) -> None:
    if proposal.source_block_id != selected_block_id:
        raise VLMProposalSelectionError("Proposal source block mismatch.")
    start = _non_negative_number(proposal.start_seconds, "Proposal start")
    end = _non_negative_number(proposal.end_seconds, "Proposal end")
    if start >= end or end > video_duration or end > memo_start:
        raise VLMProposalSelectionError("Proposal timestamp is outside its valid range.")
    if len(proposal.frame_samples) != 3:
        raise VLMProposalSelectionError("Proposal frame manifest must contain three frames.")
    seen: set[str] = set()
    previous_time = -1.0
    duration = end - start
    expected_times = tuple(start + duration * part for part in (0.10, 0.50, 0.90))
    for index, (frame, expected_time) in enumerate(
        zip(proposal.frame_samples, expected_times), start=1
    ):
        expected_id = f"{proposal.proposal_id}-frame-{index:02d}"
        if frame.frame_id != expected_id or frame.frame_id in seen:
            raise VLMProposalSelectionError("Frame manifest has an invalid or duplicate ID.")
        timestamp = _non_negative_number(frame.timestamp_seconds, "Frame timestamp")
        if (
            timestamp < start
            or timestamp > end
            or timestamp < previous_time
            or not math.isclose(timestamp, expected_time, abs_tol=1e-6)
        ):
            raise VLMProposalSelectionError("Frame timestamp does not match its proposal.")
        if not isinstance(frame.jpeg_bytes, bytes) or not frame.jpeg_bytes:
            raise VLMProposalSelectionError("Frame manifest contains an empty image.")
        seen.add(frame.frame_id)
        previous_time = timestamp


def _safe_provider_error(detail: str, http_status: int) -> tuple[str, str]:
    provider_code = f"HTTP_{http_status}"
    try:
        parsed = json.loads(detail)
        provider_error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(provider_error, str) and provider_error.strip():
            return provider_code, provider_error.strip()[:500]
        if isinstance(provider_error, dict):
            code = provider_error.get("type") or provider_error.get("code")
            message = provider_error.get("message")
            if isinstance(code, (str, int)) and str(code).strip():
                provider_code = str(code).strip()[:100]
            if isinstance(message, str) and message.strip():
                return provider_code, message.strip()[:500]
    except json.JSONDecodeError:
        pass
    return provider_code, "Ollama provider request failed."


def _optional_token_count(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _bounded_time(value: object, duration: float, label: str) -> float:
    number = _non_negative_number(value, label)
    if number > duration:
        raise VLMProposalSelectionError(f"{label} exceeds video duration.")
    return number


def _positive_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number <= 0:
        raise VLMProposalSelectionError(f"{label} must be greater than zero.")
    return number


def _non_negative_number(value: object, label: str) -> float:
    number = _number(value, label)
    if number < 0:
        raise VLMProposalSelectionError(f"{label} must not be negative.")
    return number


def _number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise VLMProposalSelectionError(f"{label} must be a valid number.")
    number = float(value)
    if not math.isfinite(number):
        raise VLMProposalSelectionError(f"{label} must be finite.")
    return number
