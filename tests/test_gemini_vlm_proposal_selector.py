from dataclasses import replace
import json
import os
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from app.services.gemini_vlm_proposal_selector import (
    DEFAULT_GEMINI_VLM_MODEL,
    GeminiVLMProposalSelector,
    GeminiVLMProviderError,
)
from app.services.ollama_vlm_proposal_selector import (
    ProposalReasoningCode,
    VLMProposalSelection,
    VLMProposalSelectionError,
    VLMProposalSelectionInput,
    validate_vlm_proposal_selection,
)
from app.services.proposal_contact_sheets import ProposalContactSheet
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)


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
                jpeg_bytes=b"source-jpeg",
            )
            for index, fraction in enumerate((0.10, 0.50, 0.90), start=1)
        ),
    )


class GeminiVLMProposalSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        proposals = (
            proposal(1, 1.0, 3.0),
            proposal(2, 0.0, 5.0),
            proposal(3, 0.0, 8.0),
        )
        sheets = tuple(
            ProposalContactSheet(
                proposal_id=item.proposal_id,
                jpeg_bytes=f"sheet-{index}".encode(),
                source_frame_ids=tuple(
                    frame.frame_id for frame in item.frame_samples
                ),
                source_frame_timestamps=tuple(
                    frame.timestamp_seconds for frame in item.frame_samples
                ),
            )
            for index, item in enumerate(proposals, start=1)
        )
        self.selection_input = VLMProposalSelectionInput(
            edit_memo_transcript="AI야 방금 장면 꼭 살려줘",
            selected_block_id="block-smoke",
            selected_block_text="아 뭐야 물건 떨어졌네",
            proposals=proposals,
            contact_sheets=sheets,
        )

    def test_structured_selection_uses_three_contact_sheet_parts(self) -> None:
        client = self._client(self._selection("proposal-002"))
        result = GeminiVLMProposalSelector(client=client).select(
            self.selection_input
        )

        self.assertEqual(result.selection.selected_proposal_id, "proposal-002")
        self.assertEqual(result.image_count, 3)
        self.assertEqual(result.total_tokens, 456)
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], DEFAULT_GEMINI_VLM_MODEL)
        self.assertEqual(len(request["contents"]), 4)
        self.assertIsInstance(request["contents"][0], str)
        self.assertEqual(
            [part.inline_data.data for part in request["contents"][1:]],
            [b"sheet-1", b"sheet-2", b"sheet-3"],
        )
        config = request["config"]
        self.assertEqual(config.temperature, 0.0)
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertIsNone(config.response_schema)
        self.assertIsInstance(config.response_json_schema, dict)
        prompt = request["contents"][0]
        self.assertNotIn("ground_truth", prompt.lower())
        self.assertNotIn("proposal_kind", prompt)

    def test_abstain_and_validator_connection(self) -> None:
        selection = self._selection(
            None, ProposalReasoningCode.INSUFFICIENT_VISUAL_EVIDENCE
        )
        result = GeminiVLMProposalSelector(client=self._client(selection)).select(
            self.selection_input
        )
        validated = validate_vlm_proposal_selection(
            self.selection_input,
            result.selection,
            video_duration_seconds=10.0,
            memo_start_seconds=9.0,
        )
        self.assertIsNone(validated.candidate)

    def test_unknown_proposal_reaches_deterministic_validator(self) -> None:
        selection = self._selection("proposal-999")
        result = GeminiVLMProposalSelector(client=self._client(selection)).select(
            self.selection_input
        )
        with self.assertRaises(VLMProposalSelectionError):
            validate_vlm_proposal_selection(
                self.selection_input,
                result.selection,
                video_duration_seconds=10.0,
                memo_start_seconds=9.0,
            )

    def test_api_and_schema_errors_are_distinct(self) -> None:
        failed_client = Mock()
        failed_client.models.generate_content.side_effect = RuntimeError("down")
        with self.assertRaises(GeminiVLMProviderError) as provider_error:
            GeminiVLMProposalSelector(client=failed_client).select(
                self.selection_input
            )
        self.assertEqual(
            provider_error.exception.diagnostics.failure_stage, "generate_content"
        )

        invalid_client = Mock()
        invalid_client.models.generate_content.return_value = SimpleNamespace(
            parsed=None,
            text='{"selected_proposal_id":"proposal-001"}',
            usage_metadata=None,
        )
        with self.assertRaises(GeminiVLMProviderError) as parsing_error:
            GeminiVLMProposalSelector(client=invalid_client).select(
                self.selection_input
            )
        self.assertEqual(
            parsing_error.exception.diagnostics.failure_stage,
            "structured_output_parsing",
        )

    def test_api_key_is_not_in_error_or_payload(self) -> None:
        secret = "AIzaSyntheticSecretThatMustNotAppear123456"
        client = Mock()
        client.models.generate_content.side_effect = RuntimeError(secret)
        with patch.dict(os.environ, {"GEMINI_API_KEY": secret}):
            with self.assertRaises(GeminiVLMProviderError) as raised:
                GeminiVLMProposalSelector(client=client).select(self.selection_input)
        self.assertNotIn(secret, str(raised.exception))
        request = client.models.generate_content.call_args.kwargs
        self.assertNotIn(secret, json.dumps(request, default=str))

    @staticmethod
    def _selection(
        selected_id: str | None,
        code: ProposalReasoningCode = ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
    ) -> VLMProposalSelection:
        return VLMProposalSelection(
            selected_proposal_id=selected_id,
            reasoning_code=code,
            reasoning_summary="짧은 선택 근거",
        )

    @staticmethod
    def _client(selection: VLMProposalSelection) -> Mock:
        response = SimpleNamespace(
            parsed=selection,
            text=selection.model_dump_json(),
            usage_metadata=SimpleNamespace(
                prompt_token_count=400,
                candidates_token_count=56,
                total_token_count=456,
            ),
        )
        client = Mock()
        client.models.generate_content.return_value = response
        return client


if __name__ == "__main__":
    unittest.main()
