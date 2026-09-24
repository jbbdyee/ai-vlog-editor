import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from openai import APITimeoutError

from app.services.memo_detector import EditMemo
from app.services.openai_semantic_block_selector import (
    DEFAULT_OPENAI_MODEL,
    OpenAISelectionPayload,
    OpenAISemanticBlockSelector,
    OpenAISelectorAPIError,
    OpenAISelectorConfigurationError,
    OpenAISelectorResponseError,
    OpenAISelectorTimeoutError,
    PROMPT_VERSION,
    ReasoningCode,
    SYSTEM_PROMPT,
    build_user_prompt,
)
from app.services.semantic_block_selector import (
    SemanticBlockSelectionError,
    SemanticBlockSelectionInput,
    run_block_selector,
)
from app.services.transcript_scene_retriever import TranscriptBlock


class OpenAISemanticBlockSelectorTests(TestCase):
    def test_structured_selection_uses_responses_api_and_tracks_usage(self) -> None:
        client = self._client_with_payload("block-0001")
        selector = OpenAISemanticBlockSelector(client=client)

        selection = selector.select(self._input())

        self.assertEqual(selection.selected_block_id, "block-0001")
        self.assertEqual(selection.reasoning_code, "EARLIER_SALIENT_EVENT")
        request = client.responses.parse.call_args.kwargs
        self.assertEqual(request["model"], DEFAULT_OPENAI_MODEL)
        self.assertEqual(request["instructions"], SYSTEM_PROMPT)
        self.assertIs(request["text_format"], OpenAISelectionPayload)
        self.assertEqual(request["reasoning"], {"effort": "low"})
        self.assertFalse(request["store"])
        self.assertNotIn("temperature", request)
        self.assertEqual(selector.last_call_metadata.input_tokens, 120)
        self.assertEqual(selector.last_call_metadata.output_tokens, 24)

    def test_user_payload_contains_only_allowed_transcript_information(self) -> None:
        payload = json.loads(build_user_prompt(self._input()))

        self.assertEqual(payload["prompt_version"], PROMPT_VERSION)
        self.assertEqual(payload["edit_memo"], "아 AIA 방금 장면 꼭 살려줘")
        self.assertEqual(
            set(payload["blocks"][0]),
            {"block_id", "start_seconds", "end_seconds", "transcript_text"},
        )
        self.assertNotIn("ground_truth", payload)
        self.assertNotIn("segment_ids", payload["blocks"][0])

    def test_missing_api_key_is_configuration_error(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                OpenAISelectorConfigurationError, "OPENAI_API_KEY"
            ):
                OpenAISemanticBlockSelector()

    def test_timeout_is_distinct_provider_error(self) -> None:
        client = Mock()
        client.responses.parse.side_effect = APITimeoutError(request=Mock())
        selector = OpenAISemanticBlockSelector(client=client)

        with self.assertRaises(OpenAISelectorTimeoutError):
            selector.select(self._input())

    def test_api_failure_is_distinct_provider_error(self) -> None:
        client = Mock()
        client.responses.parse.side_effect = RuntimeError("provider down")
        selector = OpenAISemanticBlockSelector(client=client)

        with self.assertRaises(OpenAISelectorAPIError):
            selector.select(self._input())

    def test_invalid_structured_response_is_rejected(self) -> None:
        client = Mock()
        client.responses.parse.return_value = SimpleNamespace(
            id="resp-test",
            model=DEFAULT_OPENAI_MODEL,
            usage=None,
            output=(),
            output_parsed={"selected_block_id": "block-0001"},
        )
        selector = OpenAISemanticBlockSelector(client=client)

        with self.assertRaises(OpenAISelectorResponseError):
            selector.select(self._input())

    def test_refusal_is_rejected_without_selection(self) -> None:
        refusal = SimpleNamespace(type="refusal", refusal="cannot comply")
        response = SimpleNamespace(
            id="resp-test",
            model=DEFAULT_OPENAI_MODEL,
            usage=None,
            output=(SimpleNamespace(content=(refusal,)),),
            output_parsed=None,
        )
        client = Mock()
        client.responses.parse.return_value = response
        selector = OpenAISemanticBlockSelector(client=client)

        with self.assertRaisesRegex(OpenAISelectorResponseError, "refused"):
            selector.select(self._input())

    def test_unknown_block_id_reaches_deterministic_validator(self) -> None:
        client = self._client_with_payload("block-9999")
        selector = OpenAISemanticBlockSelector(client=client)

        with self.assertRaisesRegex(
            SemanticBlockSelectionError, "does not exist"
        ):
            run_block_selector(
                selector,
                self._input(),
                video_duration_seconds=40.05,
            )

    def test_valid_selection_connects_to_existing_candidate_validator(self) -> None:
        client = self._client_with_payload("block-0001")
        selector = OpenAISemanticBlockSelector(client=client)

        result = run_block_selector(
            selector,
            self._input(),
            video_duration_seconds=40.05,
        )

        self.assertEqual(result.selected_block.block_id, "block-0001")
        self.assertEqual(result.candidate.start_seconds, 3.04)
        self.assertEqual(result.candidate.end_seconds, 10.96)

    @staticmethod
    def _client_with_payload(block_id: str) -> Mock:
        parsed = OpenAISelectionPayload(
            selected_block_id=block_id,
            reasoning_code=ReasoningCode.EARLIER_SALIENT_EVENT,
            reasoning_summary="반응 발화가 포함된 이전 사건 block이다.",
        )
        response = SimpleNamespace(
            id="resp-test",
            model=DEFAULT_OPENAI_MODEL,
            usage=SimpleNamespace(
                input_tokens=120,
                output_tokens=24,
                total_tokens=144,
            ),
            output=(),
            output_parsed=parsed,
        )
        client = Mock()
        client.responses.parse.return_value = response
        return client

    @classmethod
    def _input(cls) -> SemanticBlockSelectionInput:
        return SemanticBlockSelectionInput(
            memo=EditMemo(
                start_seconds=32.84,
                end_seconds=36.32,
                transcript_text="아 AIA 방금 장면 꼭 살려줘",
                matched_trigger="AIA",
                matched_reference="방금",
                matched_action="살려줘",
            ),
            blocks=(
                cls._block("block-0001", 3.04, 10.96, "아 뭐야 떨어졌네"),
                cls._block(
                    "block-0002",
                    14.0,
                    23.8,
                    "다시 주었습니다... 다음 테스트도 해보겠습니다",
                ),
            ),
        )

    @staticmethod
    def _block(
        block_id: str, start: float, end: float, text: str
    ) -> TranscriptBlock:
        return TranscriptBlock(
            block_id=block_id,
            start_seconds=start,
            end_seconds=end,
            segment_ids=("segment-0001",),
            transcript_text=text,
        )
