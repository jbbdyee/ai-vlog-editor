import time
from typing import Any

from app.services.evaluation_result_store import (
    DuplicateEvaluationResultError,
    JsonlVLMSmokeResultStore,
    VLMSmokeTestResult,
)
from app.services.ollama_vlm_proposal_selector import (
    DEFAULT_OLLAMA_CONTEXT_SIZE,
    DEFAULT_OLLAMA_MODEL,
    OllamaVLMProposalSelector,
    OllamaVLMProviderError,
    VLMProposalSelectionError,
    VLMProposalSelectionInput,
    validate_vlm_proposal_selection,
)
from app.services.gemini_vlm_proposal_selector import GeminiVLMProviderError


DEFAULT_SMOKE_RUNTIME = "mac_native_ollama"
DEFAULT_TEMPERATURE = 0.0


def run_persisted_vlm_smoke_test(
    *,
    run_id: str,
    selector: Any,
    selection_input: VLMProposalSelectionInput,
    video_duration_seconds: float,
    memo_start_seconds: float,
    store: JsonlVLMSmokeResultStore,
    runtime: str = DEFAULT_SMOKE_RUNTIME,
    provider: str = "ollama",
    num_ctx: int | None = DEFAULT_OLLAMA_CONTEXT_SIZE,
    config_version: str | None = None,
) -> VLMSmokeTestResult:
    """Run at most once per run ID and durably persist every terminal outcome."""
    if store.has_run(run_id):
        raise DuplicateEvaluationResultError(
            f"Smoke result already exists for run {run_id}; provider was not called."
        )

    started = time.perf_counter()
    try:
        call_result = selector.select(selection_input)
    except Exception as exc:
        diagnostics = _provider_diagnostics(exc)
        result = _result(
            run_id=run_id,
            selector=selector,
            runtime=runtime,
            provider=provider,
            num_ctx=num_ctx,
            config_version=config_version,
            image_count=_actual_image_count(selection_input),
            proposal_count=len(selection_input.proposals),
            logical_source_frame_count=_logical_frame_count(selection_input),
            actual_vlm_image_count=_actual_image_count(selection_input),
            latency_seconds=time.perf_counter() - started,
            provider_error=True,
            provider_error_code=diagnostics["provider_error_code"],
            **diagnostics["metadata"],
        )
        store.append(result)
        raise

    selection = call_result.selection
    try:
        validate_vlm_proposal_selection(
            selection_input,
            selection,
            video_duration_seconds=video_duration_seconds,
            memo_start_seconds=memo_start_seconds,
        )
    except VLMProposalSelectionError:
        result = _result(
            run_id=run_id,
            selector=selector,
            runtime=runtime,
            provider=provider,
            num_ctx=num_ctx,
            config_version=config_version,
            image_count=call_result.image_count,
            proposal_count=len(selection_input.proposals),
            logical_source_frame_count=_logical_frame_count(selection_input),
            actual_vlm_image_count=call_result.image_count,
            input_tokens=call_result.input_tokens,
            selected_proposal_id=selection.selected_proposal_id,
            reasoning_code=selection.reasoning_code.value,
            reasoning_summary=selection.reasoning_summary,
            structured_output_success=True,
            validator_success=False,
            latency_seconds=call_result.latency_seconds,
            output_tokens=call_result.output_tokens,
            total_tokens=call_result.total_tokens,
        )
        store.append(result)
        raise

    result = _result(
        run_id=run_id,
        selector=selector,
        runtime=runtime,
        provider=provider,
        num_ctx=num_ctx,
        config_version=config_version,
        image_count=call_result.image_count,
        proposal_count=len(selection_input.proposals),
        logical_source_frame_count=_logical_frame_count(selection_input),
        actual_vlm_image_count=call_result.image_count,
        input_tokens=call_result.input_tokens,
        selected_proposal_id=selection.selected_proposal_id,
        reasoning_code=selection.reasoning_code.value,
        reasoning_summary=selection.reasoning_summary,
        structured_output_success=True,
        validator_success=True,
        latency_seconds=call_result.latency_seconds,
        output_tokens=call_result.output_tokens,
        total_tokens=call_result.total_tokens,
    )
    store.append(result)
    return result


def _result(
    *,
    run_id: str,
    selector: Any,
    runtime: str,
    image_count: int,
    input_tokens: int | None = None,
    selected_proposal_id: str | None = None,
    reasoning_code: str | None = None,
    reasoning_summary: str | None = None,
    structured_output_success: bool = False,
    validator_success: bool = False,
    latency_seconds: float | None = None,
    output_tokens: int | None = None,
    total_tokens: int | None = None,
    provider_error: bool = False,
    provider_error_code: str | None = None,
    provider_http_status: int | None = None,
    provider_error_message: str | None = None,
    provider_failure_stage: str | None = None,
    provider_timeout: bool = False,
    provider_model: str | None = None,
    provider_image_count: int | None = None,
    provider_num_ctx: int | None = None,
    proposal_count: int | None = None,
    logical_source_frame_count: int | None = None,
    actual_vlm_image_count: int | None = None,
    provider: str = "ollama",
    num_ctx: int | None = DEFAULT_OLLAMA_CONTEXT_SIZE,
    config_version: str | None = None,
) -> VLMSmokeTestResult:
    return VLMSmokeTestResult.completed_now(
        run_id=run_id,
        test_type="vlm_smoke",
        model=selector.model or DEFAULT_OLLAMA_MODEL,
        runtime=runtime,
        num_ctx=num_ctx,
        temperature=DEFAULT_TEMPERATURE,
        image_count=image_count,
        input_tokens=input_tokens,
        selected_proposal_id=selected_proposal_id,
        reasoning_code=reasoning_code,
        reasoning_summary=reasoning_summary,
        structured_output_success=structured_output_success,
        validator_success=validator_success,
        latency_seconds=latency_seconds,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        provider_error=provider_error,
        provider_error_code=provider_error_code,
        provider_http_status=provider_http_status,
        provider_error_message=provider_error_message,
        provider_failure_stage=provider_failure_stage,
        provider_timeout=provider_timeout,
        provider_model=provider_model,
        provider_image_count=provider_image_count,
        provider_num_ctx=provider_num_ctx,
        proposal_count=proposal_count,
        logical_source_frame_count=logical_source_frame_count,
        actual_vlm_image_count=actual_vlm_image_count,
        provider=provider,
        config_version=config_version,
    )


def _logical_frame_count(selection_input: VLMProposalSelectionInput) -> int:
    return sum(len(proposal.frame_samples) for proposal in selection_input.proposals)


def _actual_image_count(selection_input: VLMProposalSelectionInput) -> int:
    if selection_input.contact_sheets is not None:
        return len(selection_input.contact_sheets)
    return _logical_frame_count(selection_input)


def _provider_diagnostics(exc: Exception) -> dict[str, object]:
    if isinstance(exc, GeminiVLMProviderError):
        diagnostics = exc.diagnostics
        return {
            "provider_error_code": diagnostics.provider_error_code
            or type(exc).__name__,
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
