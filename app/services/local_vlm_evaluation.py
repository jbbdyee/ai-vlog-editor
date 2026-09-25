import time

from app.services.candidate_evaluator import GroundTruthSegment, evaluate_candidate
from app.services.evaluation_result_store import (
    DuplicateEvaluationResultError,
    JsonlLocalVLMEvaluationResultStore,
    LocalVLMEvaluationResult,
)
from app.services.gemini_vlm_proposal_selector import GeminiVLMProviderError
from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMProviderError,
    OllamaVLMProposalSelector,
    VLMProposalSelectionError,
    VLMProposalSelectionInput,
    validate_vlm_proposal_selection,
)


def run_persisted_local_vlm_evaluation(
    *,
    run_id: str,
    test_id: str,
    selector: OllamaVLMProposalSelector,
    selection_input: VLMProposalSelectionInput,
    video_duration_seconds: float,
    memo_start_seconds: float,
    ground_truth: GroundTruthSegment,
    store: JsonlLocalVLMEvaluationResultStore,
    runtime: str = "mac_native_ollama",
    provider: str = "ollama",
) -> LocalVLMEvaluationResult:
    """Evaluate one test once and durably persist every terminal outcome."""
    if test_id in store.completed_test_ids(run_id):
        raise DuplicateEvaluationResultError(
            f"Result already exists for run {run_id}, test {test_id}."
        )

    oracle_proposal, oracle_evaluation = max(
        (
            (
                proposal,
                evaluate_candidate(
                    _proposal_candidate(proposal), ground_truth
                ),
            )
            for proposal in selection_input.proposals
        ),
        key=lambda item: item[1].iou,
    )
    common = dict(
        run_id=run_id,
        test_id=test_id,
        model=selector.model,
        runtime=runtime,
        provider=provider,
        proposal_count=len(selection_input.proposals),
        image_count=(
            len(selection_input.contact_sheets)
            if selection_input.contact_sheets is not None
            else sum(
                len(proposal.frame_samples)
                for proposal in selection_input.proposals
            )
        ),
        logical_source_frame_count=sum(
            len(proposal.frame_samples) for proposal in selection_input.proposals
        ),
        actual_vlm_image_count=(
            len(selection_input.contact_sheets)
            if selection_input.contact_sheets is not None
            else sum(
                len(proposal.frame_samples)
                for proposal in selection_input.proposals
            )
        ),
        oracle_best_proposal_id=oracle_proposal.proposal_id,
        oracle_best_start=oracle_proposal.start_seconds,
        oracle_best_end=oracle_proposal.end_seconds,
        oracle_best_iou=oracle_evaluation.iou,
        oracle_best_coverage=oracle_evaluation.coverage,
        oracle_best_total_boundary_error=oracle_evaluation.total_boundary_error,
    )
    started = time.perf_counter()
    try:
        call_result = selector.select(selection_input)
    except Exception as exc:
        diagnostics = _provider_diagnostics(exc)
        result = LocalVLMEvaluationResult.completed_now(
            **common,
            selected_proposal_id=None,
            reasoning_code=None,
            reasoning_summary=None,
            structured_output_success=False,
            validator_success=False,
            candidate_start=None,
            candidate_end=None,
            iou=None,
            coverage=None,
            start_boundary_error=None,
            end_boundary_error=None,
            total_boundary_error=None,
            latency_seconds=time.perf_counter() - started,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_error=True,
            provider_error_code=diagnostics["provider_error_code"],
            **diagnostics["metadata"],
        )
        store.append(result)
        raise


    selection = call_result.selection
    try:
        validated = validate_vlm_proposal_selection(
            selection_input,
            selection,
            video_duration_seconds=video_duration_seconds,
            memo_start_seconds=memo_start_seconds,
        )
    except VLMProposalSelectionError:
        result = LocalVLMEvaluationResult.completed_now(
            **common,
            selected_proposal_id=selection.selected_proposal_id,
            reasoning_code=selection.reasoning_code.value,
            reasoning_summary=selection.reasoning_summary,
            structured_output_success=True,
            validator_success=False,
            candidate_start=None,
            candidate_end=None,
            iou=None,
            coverage=None,
            start_boundary_error=None,
            end_boundary_error=None,
            total_boundary_error=None,
            latency_seconds=call_result.latency_seconds,
            input_tokens=call_result.input_tokens,
            output_tokens=call_result.output_tokens,
            total_tokens=call_result.total_tokens,
            provider_error=False,
            provider_error_code=None,
        )
        store.append(result)
        raise


    evaluation = (
        evaluate_candidate(validated.candidate, ground_truth)
        if validated.candidate is not None
        else None
    )
    result = LocalVLMEvaluationResult.completed_now(
        **common,
        selected_proposal_id=selection.selected_proposal_id,
        reasoning_code=selection.reasoning_code.value,
        reasoning_summary=selection.reasoning_summary,
        structured_output_success=True,
        validator_success=True,
        candidate_start=(validated.candidate.start_seconds if validated.candidate else None),
        candidate_end=(validated.candidate.end_seconds if validated.candidate else None),
        iou=evaluation.iou if evaluation else None,
        coverage=evaluation.coverage if evaluation else None,
        start_boundary_error=(evaluation.start_boundary_error if evaluation else None),
        end_boundary_error=(evaluation.end_boundary_error if evaluation else None),
        total_boundary_error=(evaluation.total_boundary_error if evaluation else None),
        latency_seconds=call_result.latency_seconds,
        input_tokens=call_result.input_tokens,
        output_tokens=call_result.output_tokens,
        total_tokens=call_result.total_tokens,
        provider_error=False,
        provider_error_code=None,
    )
    store.append(result)
    return result


def _proposal_candidate(proposal):
    from app.services.candidate_generator import SceneCandidate

    return SceneCandidate(
        window_seconds=proposal.end_seconds - proposal.start_seconds,
        start_seconds=proposal.start_seconds,
        end_seconds=proposal.end_seconds,
    )


def _provider_diagnostics(exc: Exception) -> dict[str, object]:
    if isinstance(exc, GeminiVLMProviderError):
        diagnostics = exc.diagnostics
        return {
            "provider_error_code": (
                diagnostics.provider_error_code or type(exc).__name__
            ),
            "metadata": {
                "provider_http_status": diagnostics.http_status,
                "provider_error_message": diagnostics.safe_message,
                "provider_failure_stage": diagnostics.failure_stage,
                "provider_timeout": diagnostics.timeout,
                "provider_model": diagnostics.model,
                "provider_image_count": diagnostics.image_count,
                "provider_num_ctx": None,
            },
        }
    if not isinstance(exc, OllamaVLMProviderError):
        return {"provider_error_code": type(exc).__name__, "metadata": {}}
    return {
        "provider_error_code": exc.provider_code or type(exc).__name__,
        "metadata": {
            "provider_http_status": exc.http_status,
            "provider_error_message": exc.safe_message,
            "provider_failure_stage": exc.failure_stage,
            "provider_timeout": exc.timeout,
            "provider_model": exc.model,
            "provider_image_count": exc.image_count,
            "provider_num_ctx": exc.num_ctx,
        },
    }
