from dataclasses import fields
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app.services.evaluation_result_store import (
    DuplicateEvaluationResultError,
    JsonlVLMSmokeResultStore,
    VLMSmokeTestResult,
)
from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMCallResult,
    OllamaVLMProviderError,
    ProposalReasoningCode,
    VLMProposalSelection,
    VLMProposalSelectionError,
    VLMProposalSelectionInput,
)
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)
from app.services.vlm_smoke_runner import run_persisted_vlm_smoke_test


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


def proposal(number: int, start: float, end: float) -> SceneBoundaryProposal:
    proposal_id = f"proposal-{number:03d}"
    duration = end - start
    return SceneBoundaryProposal(
        proposal_id=proposal_id,
        proposal_kind=ProposalKind.RAW_BLOCK,
        start_seconds=start,
        end_seconds=end,
        source_block_id="block-smoke",
        source_segment_ids=("segment-smoke",),
        source_audio_interval_ids=(),
        source_visual_interval_ids=(),
        frame_samples=tuple(
            ProposalFrameSample(
                frame_id=f"{proposal_id}-frame-{index:02d}",
                timestamp_seconds=start + duration * fraction,
                jpeg_bytes=b"sensitive-binary-not-persisted",
            )
            for index, fraction in enumerate((0.1, 0.5, 0.9), start=1)
        ),
    )


class VLMSmokeRunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "tmp" / "smoke.jsonl"
        self.store = JsonlVLMSmokeResultStore(self.path)
        self.selection_input = VLMProposalSelectionInput(
            edit_memo_transcript="AI야 방금 장면 꼭 살려줘",
            selected_block_id="block-smoke",
            selected_block_text="아 뭐야 물건 떨어졌네",
            proposals=(
                proposal(1, 1.0, 3.0),
                proposal(2, 0.0, 5.0),
                proposal(3, 0.0, 8.0),
            ),
        )

    def test_success_is_immediately_recoverable(self) -> None:
        selector = self._selector("proposal-002")

        with patch("app.services.evaluation_result_store.os.fsync") as fsync:
            result = self._run("smoke-success", selector)

        self.assertEqual(result.selected_proposal_id, "proposal-002")
        self.assertTrue(result.structured_output_success)
        self.assertTrue(result.validator_success)
        self.assertEqual(result.image_count, 9)
        self.assertEqual(self.store.get("smoke-success"), result)
        fsync.assert_called_once()

    def test_abstain_is_saved_as_successful_structured_result(self) -> None:
        selector = self._selector(
            None,
            code=ProposalReasoningCode.INSUFFICIENT_VISUAL_EVIDENCE,
        )

        result = self._run("smoke-abstain", selector)

        self.assertIsNone(result.selected_proposal_id)
        self.assertTrue(result.structured_output_success)
        self.assertTrue(result.validator_success)

    def test_validator_failure_is_saved_before_error_is_raised(self) -> None:
        selector = self._selector("proposal-999")

        with self.assertRaises(VLMProposalSelectionError):
            self._run("smoke-validator-failure", selector)

        recovered = self.store.get("smoke-validator-failure")
        self.assertTrue(recovered.structured_output_success)
        self.assertFalse(recovered.validator_success)
        self.assertFalse(recovered.provider_error)
        self.assertEqual(recovered.selected_proposal_id, "proposal-999")

    def test_provider_failure_is_saved_before_error_is_raised(self) -> None:
        selector = FakeSelector(
            error=OllamaVLMProviderError(
                "Ollama request timed out.",
                provider_code="TIMEOUT",
                failure_stage="provider_request",
                model="qwen3-vl:4b",
                image_count=9,
                num_ctx=16_384,
                timeout=True,
            )
        )

        with self.assertRaises(OllamaVLMProviderError):
            self._run("smoke-provider-failure", selector)

        recovered = self.store.get("smoke-provider-failure")
        self.assertTrue(recovered.provider_error)
        self.assertEqual(
            recovered.provider_error_code, "TIMEOUT"
        )
        self.assertEqual(recovered.provider_error_message, "Ollama request timed out.")
        self.assertEqual(recovered.provider_failure_stage, "provider_request")
        self.assertTrue(recovered.provider_timeout)
        self.assertEqual(recovered.provider_model, "qwen3-vl:4b")
        self.assertEqual(recovered.provider_image_count, 9)
        self.assertEqual(recovered.provider_num_ctx, 16_384)
        self.assertFalse(recovered.structured_output_success)

    def test_existing_run_blocks_provider_call(self) -> None:
        first_selector = self._selector("proposal-001")
        self._run("same-run", first_selector)
        second_selector = self._selector("proposal-002")

        with self.assertRaises(DuplicateEvaluationResultError):
            self._run("same-run", second_selector)

        self.assertEqual(second_selector.calls, 0)
        self.assertEqual(len(self.store.read_all()), 1)

    def test_jsonl_contains_no_prompt_images_or_sensitive_fields(self) -> None:
        self._run("safe-run", self._selector("proposal-003"))

        raw = self.path.read_text(encoding="utf-8")
        record = json.loads(raw)
        field_names = {field.name for field in fields(VLMSmokeTestResult)}

        self.assertNotIn("sensitive-binary-not-persisted", raw)
        for forbidden in (
            "images",
            "image_bytes",
            "jpeg_bytes",
            "base64",
            "prompt",
            "authorization",
            "api_key",
        ):
            self.assertNotIn(forbidden, field_names)
            self.assertNotIn(forbidden, record)

    def _run(self, run_id: str, selector: FakeSelector) -> VLMSmokeTestResult:
        return run_persisted_vlm_smoke_test(
            run_id=run_id,
            selector=selector,
            selection_input=self.selection_input,
            video_duration_seconds=10.0,
            memo_start_seconds=9.0,
            store=self.store,
            runtime="test_runtime",
        )

    @staticmethod
    def _selector(
        selected_id: str | None,
        *,
        code: ProposalReasoningCode = ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
    ) -> FakeSelector:
        selection = VLMProposalSelection(
            selected_proposal_id=selected_id,
            reasoning_code=code,
            reasoning_summary="짧은 선택 근거",
        )
        return FakeSelector(
            result=OllamaVLMCallResult(
                selection=selection,
                latency_seconds=82.5,
                input_tokens=9831,
                output_tokens=25,
                total_tokens=9856,
                image_count=9,
            )
        )


if __name__ == "__main__":
    unittest.main()
