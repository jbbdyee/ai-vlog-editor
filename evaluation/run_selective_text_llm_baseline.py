"""Selective OpenAI transcript proposal evaluation on the Step 4 synthetic cases.

The runner never substitutes a mock result for an actual provider result. Without
OPENAI_API_KEY it reports the deterministic baseline and an explicit provider skip.
"""

from __future__ import annotations

import json
import os
from time import perf_counter

from backend.app.services.memo_guided_discovery import (
    DeterministicSemanticSelector,
    MemoGuidedSearchConfig,
    SelectionStatus,
    build_search_region,
    generate_scene_proposals,
    parse_memo_intent,
    validate_selection,
)
from backend.app.services.openai_transcript_proposal_provider import (
    OpenAITranscriptProposalProvider,
)
from backend.app.services.transcript_proposal_selector import (
    ProviderBackedTranscriptProposalSelector,
    SemanticExecutionOutcome,
    build_selection_input,
    escalation_reason_for,
    to_semantic_selection,
    validate_semantic_result,
)
from evaluation.run_memo_guided_baseline import (
    CASES,
    SOURCE_ID,
    _coverage,
    _memo,
    _tiou,
    run as run_deterministic,
)


MEMO_TEXT_BY_CASE = {
    "clear_just_now": "AI야 방금 여행 장면 꼭 살려줘",
    "source_start_clamp": "AI야 방금 첫 장면 꼭 살려줘",
    "ambiguous_blocks": "AI야 방금 둘째 장면 꼭 살려줘",
    "earlier_without_reference": "AI야 아까 예전 장면 꼭 살려줘",
    "no_transcript": "AI야 방금 장면 꼭 살려줘",
}


def run() -> dict[str, object]:
    deterministic = run_deterministic()
    if not os.environ.get("OPENAI_API_KEY"):
        return {
            "run_version": "selective-text-llm-v0.1",
            "dataset": "synthetic-focused-v0.1",
            "actual_provider_integration": "not executed: OPENAI_API_KEY is missing",
            "deterministic": deterministic,
            "semantic_escalated_cases": 2,
            "actual_provider_calls": 0,
            "ai_invocation_rate": None,
            "selective_llm_selection_accuracy": None,
            "provider_invocation_success": None,
            "structured_output_success": None,
            "python_validation_success": None,
            "vlm_calls": 0,
        }

    selector = ProviderBackedTranscriptProposalSelector(OpenAITranscriptProposalProvider())
    config = MemoGuidedSearchConfig(transcript_gap_seconds=0.1)
    deterministic_solved = 0
    escalated = 0
    provider_calls = 0
    provider_success = 0
    validation_success = 0
    selected_correct = 0
    expected_selection_cases = 0
    metrics: list[dict[str, float]] = []
    outcomes: dict[str, int] = {}
    rows: list[dict[str, object]] = []
    started = perf_counter()
    for index, case in enumerate(CASES, start=1):
        memo = _memo(index, case.memo_start, case.reference)
        intent = parse_memo_intent(memo)
        region = build_search_region(
            source_video_id=SOURCE_ID,
            memo_start_seconds=case.memo_start,
            duration_seconds=120,
            reference=intent.temporal_reference,
            config=config,
        )
        proposals = generate_scene_proposals(
            source_video_id=SOURCE_ID,
            transcript_segments=case.segments,
            search_region=region,
            duration_seconds=120,
            config=config,
        )
        context = {
            f"segment-{item_index:04d}": str(segment["text"])
            for item_index, segment in enumerate(case.segments, start=1)
        }
        deterministic_selection = DeterministicSemanticSelector().select(
            intent, region, proposals, context
        )
        semantic_input = build_selection_input(
            intent=intent,
            memo_text=MEMO_TEXT_BY_CASE[case.name],
            proposals=proposals,
            transcript_context=context,
        )
        reason = escalation_reason_for(
            deterministic_selection,
            intent=intent,
            eligible_proposal_count=len(semantic_input.proposals) if semantic_input else 0,
        )
        selection = deterministic_selection
        execution_outcome = None
        if reason is None or semantic_input is None:
            deterministic_solved += 1
        else:
            escalated += 1
            provider_calls += 1
            execution = selector.select(semantic_input)
            execution_outcome = execution.outcome.value
            outcomes[execution_outcome] = outcomes.get(execution_outcome, 0) + 1
            if execution.outcome is SemanticExecutionOutcome.SUCCEEDED:
                provider_success += 1
                try:
                    analysis = validate_semantic_result(execution, semantic_input)
                except ValueError:
                    outcomes["VALIDATION_FAILURE"] = outcomes.get("VALIDATION_FAILURE", 0) + 1
                else:
                    validation_success += 1
                    selection = to_semantic_selection(
                        analysis, provider=selector.provider_name, model=selector.model
                    )
        chosen = validate_selection(
            selection=selection,
            proposals=proposals,
            source_video_id=SOURCE_ID,
            search_region=region,
            duration_seconds=120,
            config_fingerprint=proposals[0].config_fingerprint if proposals else "",
        )
        if case.expected_status is SelectionStatus.SELECTED:
            expected_selection_cases += 1
            if chosen and case.ground_truth:
                best = max(
                    _tiou((proposal.start_seconds, proposal.end_seconds), case.ground_truth)
                    for proposal in proposals
                )
                if _tiou((chosen.start_seconds, chosen.end_seconds), case.ground_truth) == best:
                    selected_correct += 1
        if chosen and case.ground_truth:
            predicted = (chosen.start_seconds, chosen.end_seconds)
            metrics.append(
                {
                    "tiou": _tiou(predicted, case.ground_truth),
                    "coverage": _coverage(predicted, case.ground_truth),
                    "start_error": abs(predicted[0] - case.ground_truth[0]),
                    "end_error": abs(predicted[1] - case.ground_truth[1]),
                }
            )
        rows.append(
            {
                "case": case.name,
                "deterministic_status": deterministic_selection.status.value,
                "escalated": reason.value if reason else None,
                "execution_outcome": execution_outcome,
                "final_status": selection.status.value,
            }
        )
    return {
        "run_version": "selective-text-llm-v0.1",
        "dataset": "synthetic-focused-v0.1",
        "actual_provider_integration": "executed",
        "provider": selector.provider_name,
        "model": selector.model,
        "cases": rows,
        "deterministic_solved": deterministic_solved,
        "semantic_escalated_cases": escalated,
        "actual_provider_calls": provider_calls,
        "ai_invocation_rate": provider_calls / len(CASES),
        "provider_invocation_success": provider_success / provider_calls if provider_calls else None,
        "python_validation_success": validation_success / provider_success if provider_success else None,
        "selective_llm_selection_accuracy": selected_correct / expected_selection_cases,
        "mean_tiou": _mean(metrics, "tiou"),
        "mean_coverage": _mean(metrics, "coverage"),
        "mean_start_boundary_error_seconds": _mean(metrics, "start_error"),
        "mean_end_boundary_error_seconds": _mean(metrics, "end_error"),
        "execution_outcomes": outcomes,
        "processing_time_seconds": round(perf_counter() - started, 6),
        "vlm_calls": 0,
    }


def _mean(rows: list[dict[str, float]], key: str) -> float | None:
    return sum(row[key] for row in rows) / len(rows) if rows else None


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
