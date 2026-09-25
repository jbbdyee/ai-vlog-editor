from dataclasses import replace
import io
import json
import socket
import unittest
from unittest.mock import patch
from urllib import error

from pydantic import ValidationError

from app.services.ollama_vlm_proposal_selector import (
    OllamaVLMProposalSelector,
    OllamaVLMProviderError,
    ProposalReasoningCode,
    VLMProposalSelection,
    VLMProposalSelectionError,
    VLMProposalSelectionInput,
    UrllibHTTPTransport,
    validate_vlm_proposal_selection,
)
from app.services.scene_boundary_proposals import (
    ProposalFrameSample,
    ProposalKind,
    SceneBoundaryProposal,
)


class FakeTransport:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error
        self.payload = None

    def post_json(self, url, payload, timeout):
        self.payload = payload
        if self.error:
            raise self.error
        return self.response


def make_proposal(number: int, start: float, end: float):
    proposal_id = f"proposal-{number:03d}"
    duration = end - start
    return SceneBoundaryProposal(
        proposal_id=proposal_id,
        proposal_kind=ProposalKind.RAW_BLOCK,
        start_seconds=start,
        end_seconds=end,
        source_block_id="block-0001",
        source_segment_ids=("segment-0001",),
        source_audio_interval_ids=(),
        source_visual_interval_ids=(),
        frame_samples=tuple(
            ProposalFrameSample(
                frame_id=f"{proposal_id}-frame-{index:02d}",
                timestamp_seconds=start + duration * fraction,
                jpeg_bytes=b"jpeg",
            )
            for index, fraction in enumerate((0.1, 0.5, 0.9), start=1)
        ),
    )


class OllamaVLMProposalSelectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.selection_input = VLMProposalSelectionInput(
            edit_memo_transcript="AI야 방금 장면 꼭 살려줘",
            selected_block_id="block-0001",
            selected_block_text="아 뭐야 물건 떨어졌네",
            proposals=(
                make_proposal(1, 3.0, 5.0),
                make_proposal(2, 2.0, 7.0),
                make_proposal(3, 1.0, 10.0),
            ),
        )

    def test_structured_selection_and_validator(self) -> None:
        content = VLMProposalSelection(
            selected_proposal_id="proposal-002",
            reasoning_code=ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
            reasoning_summary="낙하와 반응을 함께 포함합니다.",
        ).model_dump_json()
        transport = FakeTransport(
            {
                "message": {"content": content},
                "prompt_eval_count": 100,
                "eval_count": 20,
            }
        )
        result = OllamaVLMProposalSelector(transport=transport).select(
            self.selection_input
        )
        validated = validate_vlm_proposal_selection(
            self.selection_input,
            result.selection,
            video_duration_seconds=20.0,
            memo_start_seconds=15.0,
        )

        self.assertEqual(validated.selected_proposal.proposal_id, "proposal-002")
        self.assertEqual((validated.candidate.start_seconds, validated.candidate.end_seconds), (2.0, 7.0))
        self.assertEqual(result.total_tokens, 120)
        self.assertEqual(result.image_count, 9)
        self.assertIsInstance(transport.payload["format"], dict)
        self.assertEqual(
            transport.payload["options"],
            {"temperature": 0.0, "num_ctx": 16_384},
        )
        self.assertEqual(transport.payload["model"], "qwen3-vl:4b")
        self.assertFalse(transport.payload["stream"])
        self.assertEqual(len(transport.payload["messages"]), 1)
        self.assertEqual(len(transport.payload["messages"][0]["images"]), 9)
        self.assertNotIn("proposal_kind", json.dumps(transport.payload))

    def test_rejects_unknown_proposal_id(self) -> None:
        selection = VLMProposalSelection(
            selected_proposal_id="proposal-999",
            reasoning_code=ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
            reasoning_summary="관련 사건입니다.",
        )
        with self.assertRaises(VLMProposalSelectionError):
            validate_vlm_proposal_selection(
                self.selection_input,
                selection,
                video_duration_seconds=20.0,
                memo_start_seconds=15.0,
            )

    def test_accepts_explicit_abstain(self) -> None:
        selection = VLMProposalSelection(
            selected_proposal_id=None,
            reasoning_code=ProposalReasoningCode.INSUFFICIENT_VISUAL_EVIDENCE,
            reasoning_summary="프레임만으로 판단할 수 없습니다.",
        )
        validated = validate_vlm_proposal_selection(
            self.selection_input,
            selection,
            video_duration_seconds=20.0,
            memo_start_seconds=15.0,
        )
        self.assertIsNone(validated.candidate)

    def test_rejects_invalid_reasoning_code_and_null_mismatch(self) -> None:
        with self.assertRaises(ValidationError):
            VLMProposalSelection(
                selected_proposal_id="proposal-001",
                reasoning_code="MADE_UP",
                reasoning_summary="설명",
            )
        with self.assertRaises(ValidationError):
            VLMProposalSelection(
                selected_proposal_id=None,
                reasoning_code=ProposalReasoningCode.LONG_CONTEXT_REQUIRED,
                reasoning_summary="설명",
            )

    def test_rejects_invalid_timestamp_and_video_range(self) -> None:
        invalid_timestamp = replace(
            self.selection_input.proposals[0], start_seconds=float("nan")
        )
        invalid_input = replace(
            self.selection_input,
            proposals=(invalid_timestamp, *self.selection_input.proposals[1:]),
        )
        selection = VLMProposalSelection(
            selected_proposal_id="proposal-001",
            reasoning_code=ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
            reasoning_summary="설명",
        )
        with self.assertRaises(VLMProposalSelectionError):
            validate_vlm_proposal_selection(
                invalid_input,
                selection,
                video_duration_seconds=20.0,
                memo_start_seconds=15.0,
            )

        outside = replace(self.selection_input.proposals[2], end_seconds=21.0)
        outside_input = replace(
            self.selection_input,
            proposals=(*self.selection_input.proposals[:2], outside),
        )
        with self.assertRaises(VLMProposalSelectionError):
            validate_vlm_proposal_selection(
                outside_input,
                selection,
                video_duration_seconds=20.0,
                memo_start_seconds=15.0,
            )

    def test_rejects_frame_manifest_mismatch(self) -> None:
        first = self.selection_input.proposals[0]
        bad_frame = replace(first.frame_samples[0], timestamp_seconds=4.9)
        bad_proposal = replace(
            first, frame_samples=(bad_frame, *first.frame_samples[1:])
        )
        invalid_input = replace(
            self.selection_input,
            proposals=(bad_proposal, *self.selection_input.proposals[1:]),
        )
        selection = VLMProposalSelection(
            selected_proposal_id="proposal-001",
            reasoning_code=ProposalReasoningCode.EVENT_AND_REACTION_CONNECTED,
            reasoning_summary="설명",
        )
        with self.assertRaises(VLMProposalSelectionError):
            validate_vlm_proposal_selection(
                invalid_input,
                selection,
                video_duration_seconds=20.0,
                memo_start_seconds=15.0,
            )

    def test_provider_failure_and_structured_parse_failure(self) -> None:
        provider = OllamaVLMProposalSelector(
            transport=FakeTransport(error=OllamaVLMProviderError("timeout"))
        )
        with self.assertRaises(OllamaVLMProviderError) as provider_error:
            provider.select(self.selection_input)
        self.assertEqual(provider_error.exception.model, "qwen3-vl:4b")
        self.assertEqual(provider_error.exception.image_count, 9)
        self.assertEqual(provider_error.exception.num_ctx, 16_384)

        malformed = OllamaVLMProposalSelector(
            transport=FakeTransport({"message": {"content": "not-json"}})
        )
        with self.assertRaises(OllamaVLMProviderError) as parse_error:
            malformed.select(self.selection_input)
        self.assertEqual(
            parse_error.exception.failure_stage, "structured_output_parsing"
        )
        self.assertEqual(
            parse_error.exception.provider_code, "STRUCTURED_OUTPUT_ERROR"
        )

    def test_http_400_preserves_safe_nested_provider_error(self) -> None:
        body = json.dumps(
            {
                "error": {
                    "type": "exceed_context_size_error",
                    "message": "input exceeds configured context",
                }
            }
        ).encode()
        http_error = error.HTTPError(
            "http://localhost:11434/api/chat", 400, "Bad Request", {}, io.BytesIO(body)
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(OllamaVLMProviderError) as raised:
                UrllibHTTPTransport().post_json("http://localhost", {}, 1.0)
        self.assertEqual(raised.exception.http_status, 400)
        self.assertEqual(
            raised.exception.provider_code, "exceed_context_size_error"
        )
        self.assertEqual(
            raised.exception.safe_message, "input exceeds configured context"
        )

    def test_http_500_uses_safe_error_string(self) -> None:
        http_error = error.HTTPError(
            "http://localhost", 500, "Error", {}, io.BytesIO(b'{"error":"internal failure"}')
        )
        with patch("urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(OllamaVLMProviderError) as raised:
                UrllibHTTPTransport().post_json("http://localhost", {}, 1.0)
        self.assertEqual(raised.exception.http_status, 500)
        self.assertEqual(raised.exception.provider_code, "HTTP_500")
        self.assertEqual(raised.exception.safe_message, "internal failure")

    def test_timeout_and_connection_errors_are_distinguished(self) -> None:
        with patch("urllib.request.urlopen", side_effect=socket.timeout()):
            with self.assertRaises(OllamaVLMProviderError) as timeout_error:
                UrllibHTTPTransport().post_json("http://localhost", {}, 1.0)
        self.assertTrue(timeout_error.exception.timeout)
        self.assertEqual(timeout_error.exception.provider_code, "TIMEOUT")

        with patch(
            "urllib.request.urlopen",
            side_effect=error.URLError(ConnectionRefusedError()),
        ):
            with self.assertRaises(OllamaVLMProviderError) as connection_error:
                UrllibHTTPTransport().post_json("http://localhost", {}, 1.0)
        self.assertFalse(connection_error.exception.timeout)
        self.assertEqual(
            connection_error.exception.provider_code, "CONNECTION_ERROR"
        )


if __name__ == "__main__":
    unittest.main()
