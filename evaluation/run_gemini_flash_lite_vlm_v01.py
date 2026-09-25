"""Run Gemini Flash-Lite Contact Sheet evaluation once per pending test."""

import sys

from app.config import load_environment
from app.services.evaluation_result_store import (
    JsonlLocalVLMEvaluationResultStore,
    LocalVLMEvaluationResult,
)
from app.services.gemini_vlm_proposal_selector import GeminiVLMProposalSelector
from app.services.local_vlm_evaluation import run_persisted_local_vlm_evaluation
from app.services.stt_service import load_model
from evaluation.run_local_vlm_proposal_v01 import CASES, _prepare_case


RUN_ID = "gemini-flash-lite-vlm-eval-v0.1-run1"
MODEL = "gemini-3.1-flash-lite"


def main() -> int:
    load_environment()
    store = JsonlLocalVLMEvaluationResultStore()
    completed = set(store.completed_test_ids(RUN_ID))
    pending = tuple(case for case in CASES if case.test_id not in completed)
    if not pending:
        return 0

    stt_model = load_model()
    selector = GeminiVLMProposalSelector(model=MODEL)
    for case in pending:
        try:
            selection_input, duration, memo_start = _prepare_case(case, stt_model)
            run_persisted_local_vlm_evaluation(
                run_id=RUN_ID,
                test_id=case.test_id,
                selector=selector,
                selection_input=selection_input,
                video_duration_seconds=duration,
                memo_start_seconds=memo_start,
                ground_truth=case.ground_truth,
                store=store,
                runtime="gemini_api",
                provider="gemini",
            )
        except Exception as exc:
            if case.test_id not in store.completed_test_ids(RUN_ID):
                _persist_preparation_failure(case, selector, store, exc)
            print(f"{case.test_id}: {type(exc).__name__}", file=sys.stderr)
    return 0


def _persist_preparation_failure(case, selector, store, error) -> None:
    store.append(
        LocalVLMEvaluationResult.completed_now(
            run_id=RUN_ID,
            test_id=case.test_id,
            model=selector.model,
            runtime="gemini_api",
            provider="gemini",
            proposal_count=0,
            image_count=0,
            logical_source_frame_count=0,
            actual_vlm_image_count=0,
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
            oracle_best_proposal_id=None,
            oracle_best_start=None,
            oracle_best_end=None,
            oracle_best_iou=None,
            oracle_best_coverage=None,
            oracle_best_total_boundary_error=None,
            latency_seconds=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_error=False,
            provider_error_code=None,
            preparation_error=True,
            preparation_error_code=type(error).__name__,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
