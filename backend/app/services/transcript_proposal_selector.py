from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
from typing import Protocol

from backend.app.services.memo_guided_discovery import (
    MemoIntent,
    SceneProposal,
    SelectionStatus,
    SemanticSelection,
)


CAPABILITY = "TRANSCRIPT_PROPOSAL_SELECTOR"
PROMPT_VERSION = "transcript-proposal-selector-v0.1"
SCHEMA_VERSION = "transcript-proposal-selection-v0.1"
MAX_MEMO_CHARACTERS = 500
MAX_SNIPPET_CHARACTERS = 600
MAX_TOTAL_SNIPPET_CHARACTERS = 6_000
MAX_SUMMARY_CHARACTERS = 240


class SemanticEscalationReason(str, Enum):
    AMBIGUOUS_TRANSCRIPT_PROPOSALS = "AMBIGUOUS_TRANSCRIPT_PROPOSALS"
    SEMANTIC_REFERENCE_UNRESOLVED = "SEMANTIC_REFERENCE_UNRESOLVED"
    TRANSCRIPT_INSUFFICIENT = "TRANSCRIPT_INSUFFICIENT"


class SemanticExecutionOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    PROVIDER_FAILURE = "PROVIDER_FAILURE"
    TIMEOUT = "TIMEOUT"
    PARSE_FAILURE = "PARSE_FAILURE"
    OUTPUT_INVALID = "OUTPUT_INVALID"
    VALIDATION_FAILURE = "VALIDATION_FAILURE"


@dataclass(frozen=True)
class TranscriptProposalInput:
    proposal_id: str
    transcript_snippet: str
    relative_order: int


@dataclass(frozen=True)
class TranscriptProposalSelectionInput:
    capability: str
    prompt_version: str
    schema_version: str
    memo_action: str
    temporal_reference: str
    semantic_reference: str | None
    memo_text: str
    proposals: tuple[TranscriptProposalInput, ...]
    proposal_manifest_fingerprint: str
    semantic_input_fingerprint: str


@dataclass(frozen=True)
class SemanticProviderMetadata:
    provider: str
    model: str
    latency_seconds: float
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None
    response_id: str | None = None


@dataclass(frozen=True)
class SemanticAnalysisResult:
    semantic_status: SelectionStatus
    selected_id: str | None
    reason_code: str
    bounded_summary: str | None
    model_confidence: float | None
    capability: str = CAPABILITY
    schema_version: str = SCHEMA_VERSION


@dataclass(frozen=True)
class SemanticExecutionResult:
    outcome: SemanticExecutionOutcome
    analysis: SemanticAnalysisResult | None
    metadata: SemanticProviderMetadata | None
    safe_error_code: str | None = None
    safe_error_message: str | None = None


class SemanticTextProvider(Protocol):
    provider_name: str
    model: str

    def analyze(
        self, selection_input: TranscriptProposalSelectionInput
    ) -> SemanticExecutionResult: ...


class TranscriptProposalSelector(Protocol):
    provider_name: str
    model: str

    def select(
        self, selection_input: TranscriptProposalSelectionInput
    ) -> SemanticExecutionResult: ...


class ProviderBackedTranscriptProposalSelector:
    def __init__(self, provider: SemanticTextProvider) -> None:
        self._provider = provider
        self.provider_name = provider.provider_name
        self.model = provider.model

    def select(
        self, selection_input: TranscriptProposalSelectionInput
    ) -> SemanticExecutionResult:
        return self._provider.analyze(selection_input)


def escalation_reason_for(
    selection: SemanticSelection,
    *,
    intent: MemoIntent,
    eligible_proposal_count: int,
) -> SemanticEscalationReason | None:
    if selection.status is SelectionStatus.SELECTED or eligible_proposal_count == 0:
        return None
    if selection.status is SelectionStatus.AMBIGUOUS:
        return SemanticEscalationReason.AMBIGUOUS_TRANSCRIPT_PROPOSALS
    if selection.reason_code in {"EARLIER_NEEDS_REFERENCE", "LEXICAL_REFERENCE_NO_MATCH"}:
        return SemanticEscalationReason.SEMANTIC_REFERENCE_UNRESOLVED
    if (
        selection.status is SelectionStatus.INSUFFICIENT_EVIDENCE
        and intent.semantic_reference is not None
    ):
        return SemanticEscalationReason.TRANSCRIPT_INSUFFICIENT
    return None


def build_selection_input(
    *,
    intent: MemoIntent,
    memo_text: str,
    proposals: tuple[SceneProposal, ...],
    transcript_context: dict[str, str],
) -> TranscriptProposalSelectionInput | None:
    bounded: list[TranscriptProposalInput] = []
    total_characters = 0
    for proposal in proposals:
        parts = [
            transcript_context[reference].strip()
            for reference in proposal.evidence_refs
            if transcript_context.get(reference, "").strip()
        ]
        if not parts:
            continue
        snippet = _bounded_text(" ".join(parts), MAX_SNIPPET_CHARACTERS)
        if total_characters + len(snippet) > MAX_TOTAL_SNIPPET_CHARACTERS:
            break
        bounded.append(
            TranscriptProposalInput(
                proposal_id=proposal.proposal_id,
                transcript_snippet=snippet,
                relative_order=len(bounded) + 1,
            )
        )
        total_characters += len(snippet)
    if not bounded:
        return None

    manifest_fingerprint = _fingerprint(
        [
            {
                "id": proposal.proposal_id,
                "source": str(proposal.source_video_id),
                "start": proposal.start_seconds,
                "end": proposal.end_seconds,
                "config": proposal.config_fingerprint,
            }
            for proposal in proposals
        ]
    )
    semantic_payload = {
        "capability": CAPABILITY,
        "prompt_version": PROMPT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "memo_action": intent.action.value,
        "temporal_reference": intent.temporal_reference.value,
        "semantic_reference": intent.semantic_reference,
        "memo_text": _bounded_text(memo_text, MAX_MEMO_CHARACTERS),
        "proposals": [
            {
                "id": proposal.proposal_id,
                "snippet": proposal.transcript_snippet,
                "order": proposal.relative_order,
            }
            for proposal in bounded
        ],
        "manifest": manifest_fingerprint,
    }
    return TranscriptProposalSelectionInput(
        capability=CAPABILITY,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        memo_action=intent.action.value,
        temporal_reference=intent.temporal_reference.value,
        semantic_reference=intent.semantic_reference,
        memo_text=semantic_payload["memo_text"],
        proposals=tuple(bounded),
        proposal_manifest_fingerprint=manifest_fingerprint,
        semantic_input_fingerprint=_fingerprint(semantic_payload),
    )


def validate_semantic_result(
    result: SemanticExecutionResult,
    selection_input: TranscriptProposalSelectionInput,
) -> SemanticAnalysisResult:
    if result.outcome is not SemanticExecutionOutcome.SUCCEEDED or result.analysis is None:
        raise ValueError("Only a successful semantic execution can be validated.")
    analysis = result.analysis
    if analysis.capability != CAPABILITY or analysis.schema_version != SCHEMA_VERSION:
        raise ValueError("Semantic output capability or schema version is invalid.")
    if analysis.model_confidence is not None:
        raise ValueError("Model confidence is not accepted for this baseline.")
    if analysis.bounded_summary is not None and len(analysis.bounded_summary) > MAX_SUMMARY_CHARACTERS:
        raise ValueError("Semantic output summary exceeds the bounded limit.")
    allowed_ids = {proposal.proposal_id for proposal in selection_input.proposals}
    if analysis.semantic_status is SelectionStatus.SELECTED:
        if analysis.selected_id not in allowed_ids:
            raise ValueError("Selected proposal ID is outside the supplied allowlist.")
    elif analysis.selected_id is not None:
        raise ValueError("An abstention cannot include a selected proposal ID.")
    return analysis


def to_semantic_selection(
    analysis: SemanticAnalysisResult,
    *,
    provider: str,
    model: str,
) -> SemanticSelection:
    return SemanticSelection(
        status=analysis.semantic_status,
        selected_proposal_id=analysis.selected_id,
        confidence=None,
        reason_code=analysis.reason_code,
        summary=analysis.bounded_summary,
        selector=f"{provider}-transcript-proposal-selector",
        selector_version=f"{PROMPT_VERSION}:{model}",
    )


def _bounded_text(value: str, limit: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    candidate = normalized[: limit - 1]
    boundary = max(candidate.rfind(" "), candidate.rfind("."), candidate.rfind("?"), candidate.rfind("!"))
    if boundary >= limit // 2:
        candidate = candidate[:boundary]
    return candidate.rstrip() + "…"


def _fingerprint(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()
