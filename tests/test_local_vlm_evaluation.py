from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.services.candidate_evaluator import GroundTruthSegment
from app.services.evaluation_result_store import (
    DuplicateEvaluationResultError,
    JsonlLocalVLMEvaluationResultStore,
)
from app.services.local_vlm_evaluation import run_persisted_local_vlm_evaluation
from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMCallResult,
    OllamaVLMProviderError,
    ProposalReasoningCode,
    VLMProposalSelection,
    VLMProposalSelectionInput,
)
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)


class FakeSelector:
    model = "qwen3-vl:4b"

    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    def select(self, selection_input):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def proposal(number, start, end):
    proposal_id = f"proposal-{number:03d}"
    duration = end - start
    return SceneBoundaryProposal(
        proposal_id,
        ProposalKind.RAW_BLOCK,
        start,
        end,
        "block-0001",
        ("segment-0001",),
        (),
        (),
        tuple(
            ProposalFrameSample(
                f"{proposal_id}-frame-{index:02d}",
                start + duration * fraction,
                b"jpeg",
            )
            for index, fraction in enumerate((0.1, 0.5, 0.9), start=1)
        ),
    )


class LocalVLMEvaluationTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.store = JsonlLocalVLMEvaluationResultStore(
            Path(temporary.name) / "run.jsonl"
        )
        self.selection_input = VLMProposalSelectionInput(
            "AI야 방금 장면 꼭 살려줘",
            "block-0001",
            "물건이 떨어졌네",
            (
                proposal(1, 3.0, 5.0),
                proposal(2, 2.0, 7.0),
                proposal(3, 1.0, 9.0),
            ),
        )

    def test_selection_and_oracle_are_persisted(self):
        selector = self._selector("proposal-002")
        result = self._run("eval_01", selector)

        self.assertEqual(result.selected_proposal_id, "proposal-002")
        self.assertEqual(result.oracle_best_proposal_id, "proposal-002")
        self.assertEqual(result.iou, 0.8)
        self.assertEqual(self.store.completed_count("run-1"), 1)

    def test_abstain_keeps_metrics_null_but_preserves_oracle(self):
        selector = self._selector(
            None, ProposalReasoningCode.INSUFFICIENT_VISUAL_EVIDENCE
        )
        result = self._run("eval_02", selector)

        self.assertIsNone(result.iou)
        self.assertEqual(result.oracle_best_proposal_id, "proposal-002")
        self.assertTrue(result.validator_success)

    def test_provider_failure_is_persisted_and_duplicate_is_blocked(self):
        first = FakeSelector(error=OllamaVLMProviderError(
            "provider rejected request",
            http_status=400,
            provider_code="INVALID_REQUEST",
            failure_stage="provider_request",
            model="qwen3-vl:4b",
            image_count=9,
            num_ctx=16_384,
        ))
        with self.assertRaises(OllamaVLMProviderError):
            self._run("eval_03", first)
        recovered = self.store.read_all()[0]
        self.assertTrue(recovered.provider_error)
        self.assertEqual(recovered.provider_http_status, 400)
        self.assertEqual(recovered.provider_error_code, "INVALID_REQUEST")
        self.assertEqual(recovered.provider_error_message, "provider rejected request")
        self.assertEqual(recovered.provider_failure_stage, "provider_request")
        self.assertEqual(recovered.provider_num_ctx, 16_384)

        second = self._selector("proposal-001")
        with self.assertRaises(DuplicateEvaluationResultError):
            self._run("eval_03", second)
        self.assertEqual(second.calls, 0)

    def _run(self, test_id, selector):
        return run_persisted_local_vlm_evaluation(
            run_id="run-1",
            test_id=test_id,
            selector=selector,
            selection_input=self.selection_input,
            video_duration_seconds=10.0,
            memo_start_seconds=9.5,
            ground_truth=GroundTruthSegment(2.0, 6.0),
            store=self.store,
        )

    @staticmethod
    def _selector(selected_id, code=ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED):
        return FakeSelector(
            OllamaVLMCallResult(
                selection=VLMProposalSelection(
                    selected_proposal_id=selected_id,
                    reasoning_code=code,
                    reasoning_summary="근거",
                ),
                latency_seconds=1.0,
                input_tokens=10,
                output_tokens=2,
                total_tokens=12,
                image_count=9,
            )
        )


if __name__ == "__main__":
    unittest.main()
