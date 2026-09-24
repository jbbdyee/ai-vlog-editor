import json
import os
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from google.genai import types
from google.genai.errors import ClientError

from app.services.gemini_semantic_block_selector import (
    DEFAULT_GEMINI_MODEL,
    GeminiSelectionPayload,
    GeminiSemanticBlockSelector,
    GeminiSelectorAPIError,
    GeminiSelectorConfigurationError,
    GeminiSelectorResponseError,
    GeminiSelectorTimeoutError,
    PROMPT_VERSION,
    ReasoningCode,
    SYSTEM_PROMPT,
    build_response_json_schema,
    build_user_prompt,
)
from app.services.memo_detector import EditMemo
from app.services.semantic_block_selector import (
    SemanticBlockSelectionError,
    SemanticBlockSelectionInput,
    run_block_selector,
)
from app.services.transcript_scene_retriever import TranscriptBlock


class GeminiSemanticBlockSelectorTests(TestCase):
    def test_structured_selection_uses_gemini_schema_and_tracks_usage(self) -> None:
        client = self._client_with_payload("block-0001")
        selector = GeminiSemanticBlockSelector(client=client)

        selection = selector.select(self._input())

        self.assertEqual(selection.selected_block_id, "block-0001")
        self.assertEqual(selection.reasoning_code, "EARLIER_SALIENT_EVENT")
        request = client.models.generate_content.call_args.kwargs
        self.assertEqual(request["model"], DEFAULT_GEMINI_MODEL)
        config = request["config"]
        self.assertIsInstance(config, types.GenerateContentConfig)
        self.assertEqual(config.system_instruction, SYSTEM_PROMPT)
        self.assertEqual(config.temperature, 0.0)
        self.assertEqual(config.response_mime_type, "application/json")
        self.assertIsNone(config.response_schema)
        self.assertEqual(
            config.response_json_schema,
            build_response_json_schema(),
        )
        self.assertEqual(
            config.thinking_config.thinking_level,
            types.ThinkingLevel.MINIMAL,
        )
        self.assertEqual(selector.last_call_metadata.input_tokens, 120)
        self.assertEqual(selector.last_call_metadata.output_tokens, 24)

    def test_json_schema_preserves_strict_object_and_removes_only_unsupported_lengths(
        self,
    ) -> None:
        original_schema = GeminiSelectionPayload.model_json_schema()
        schema = build_response_json_schema()

        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["required"], original_schema["required"])
        self.assertEqual(schema["$defs"], original_schema["$defs"])
        self.assertNotIn("minLength", schema["properties"]["selected_block_id"])
        self.assertNotIn("minLength", schema["properties"]["reasoning_summary"])
        self.assertNotIn("maxLength", schema["properties"]["reasoning_summary"])
        self.assertEqual(
            set(schema),
            {
                "$defs",
                "additionalProperties",
                "properties",
                "required",
                "title",
                "type",
            },
        )

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
                GeminiSelectorConfigurationError, "GEMINI_API_KEY"
            ):
                GeminiSemanticBlockSelector()

    def test_timeout_is_distinct_provider_error(self) -> None:
        client = Mock()
        client.models.generate_content.side_effect = TimeoutError("timed out")
        selector = GeminiSemanticBlockSelector(client=client)

        with self.assertRaises(GeminiSelectorTimeoutError):
            selector.select(self._input())

    def test_api_failure_is_distinct_provider_error(self) -> None:
        client = Mock()
        client.models.generate_content.side_effect = RuntimeError("provider down")
        selector = GeminiSemanticBlockSelector(client=client)

        with self.assertRaises(GeminiSelectorAPIError):
            selector.select(self._input())

    def test_client_error_preserves_only_safe_diagnostics(self) -> None:
        secret = "AIzaSecretValueThatMustNeverAppear123456"
        provider_error = ClientError(
            400,
            {
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": (
                        "Invalid structured output. "
                        f"api_key={secret} Authorization: Bearer {secret}"
                    ),
                }
            },
        )
        client = Mock()
        client.models.generate_content.side_effect = provider_error
        selector = GeminiSemanticBlockSelector(client=client)

        with patch.dict(os.environ, {"GEMINI_API_KEY": secret}):
            with self.assertRaises(GeminiSelectorAPIError) as caught:
                selector.select(self._input())

        diagnostics = caught.exception.diagnostics
        self.assertEqual(diagnostics.http_status, 400)
        self.assertEqual(diagnostics.provider_error_code, "INVALID_ARGUMENT")
        self.assertEqual(diagnostics.failure_stage, "generate_content")
        self.assertEqual(diagnostics.model, DEFAULT_GEMINI_MODEL)
        self.assertIn("Invalid structured output", diagnostics.safe_message)
        self.assertNotIn(secret, diagnostics.safe_message)
        self.assertNotIn("Bearer", diagnostics.safe_message)
        self.assertNotIn(secret, str(caught.exception))

    def test_invalid_structured_response_is_rejected(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            response_id="response-test",
            model_version=DEFAULT_GEMINI_MODEL,
            usage_metadata=None,
            parsed=None,
            text='{"selected_block_id":"block-0001"}',
        )
        selector = GeminiSemanticBlockSelector(client=client)

        with self.assertRaises(GeminiSelectorResponseError):
            selector.select(self._input())

    def test_empty_response_is_rejected_without_selection(self) -> None:
        client = Mock()
        client.models.generate_content.return_value = SimpleNamespace(
            response_id="response-test",
            model_version=DEFAULT_GEMINI_MODEL,
            usage_metadata=None,
            parsed=None,
            text=None,
        )
        selector = GeminiSemanticBlockSelector(client=client)

        with self.assertRaisesRegex(GeminiSelectorResponseError, "no structured"):
            selector.select(self._input())

    def test_unknown_block_id_reaches_deterministic_validator(self) -> None:
        selector = GeminiSemanticBlockSelector(
            client=self._client_with_payload("block-9999")
        )

        with self.assertRaisesRegex(SemanticBlockSelectionError, "does not exist"):
            run_block_selector(
                selector,
                self._input(),
                video_duration_seconds=40.05,
            )

    def test_valid_selection_connects_to_existing_candidate_validator(self) -> None:
        selector = GeminiSemanticBlockSelector(
            client=self._client_with_payload("block-0001")
        )

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
        parsed = GeminiSelectionPayload(
            selected_block_id=block_id,
            reasoning_code=ReasoningCode.EARLIER_SALIENT_EVENT,
            reasoning_summary="반응 발화가 포함된 이전 사건 block이다.",
        )
        response = SimpleNamespace(
            response_id="response-test",
            model_version=DEFAULT_GEMINI_MODEL,
            usage_metadata=SimpleNamespace(
                prompt_token_count=120,
                candidates_token_count=24,
                total_token_count=144,
            ),
            parsed=parsed,
            text=parsed.model_dump_json(),
        )
        client = Mock()
        client.models.generate_content.return_value = response
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
