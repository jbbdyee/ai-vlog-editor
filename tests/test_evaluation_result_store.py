from dataclasses import fields
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.evaluation_result_store import (
    DuplicateEvaluationResultError,
    JsonlEvaluationResultStore,
    SemanticEvaluationResult,
)


class EvaluationResultStoreTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.path = Path(self.temporary_directory.name) / "nested" / "run.jsonl"
        self.store = JsonlEvaluationResultStore(self.path)

    def test_results_are_appended_and_previous_test_is_preserved(self) -> None:
        first = self._success("test-01")
        second = self._success("test-02")

        self.store.append(first)
        self.store.append(second)

        self.assertEqual(self.store.read_all(), (first, second))
        self.assertEqual(
            self.store.completed_test_ids("run-001"),
            ("test-01", "test-02"),
        )
        self.assertEqual(self.store.completed_count("run-001"), 2)

    def test_append_flushes_and_fsyncs_immediately(self) -> None:
        with patch("app.services.evaluation_result_store.os.fsync") as fsync:
            self.store.append(self._success("test-01"))

        fsync.assert_called_once()
        self.assertEqual(self.store.completed_count("run-001"), 1)

    def test_duplicate_run_and_test_is_rejected_without_changing_file(self) -> None:
        result = self._success("test-01")
        self.store.append(result)
        original = self.path.read_bytes()

        with self.assertRaises(DuplicateEvaluationResultError):
            self.store.append(result)

        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.store.read_all(), (result,))

    def test_provider_failure_is_durably_recoverable(self) -> None:
        failure = SemanticEvaluationResult.completed_now(
            run_id="run-001",
            test_id="test-02",
            model="gemini-3.5-flash",
            prompt_version="semantic-block-gemini-v0.1",
            selected_block_id=None,
            reasoning_code=None,
            reasoning_summary=None,
            validator_success=False,
            candidate_start=None,
            candidate_end=None,
            iou=None,
            coverage=None,
            start_boundary_error=None,
            end_boundary_error=None,
            total_boundary_error=None,
            latency_seconds=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            provider_error=True,
            provider_error_code="RESOURCE_EXHAUSTED",
        )

        self.store.append(failure)

        recovered = self.store.read_all()
        self.assertEqual(recovered, (failure,))
        self.assertTrue(recovered[0].provider_error)

    def test_jsonl_has_one_valid_object_per_completed_test(self) -> None:
        self.store.append(self._success("test-01"))
        self.store.append(self._success("test-02"))

        lines = self.path.read_text(encoding="utf-8").splitlines()

        self.assertEqual(len(lines), 2)
        self.assertEqual(
            [json.loads(line)["test_id"] for line in lines],
            ["test-01", "test-02"],
        )

    def test_result_schema_contains_no_sensitive_fields(self) -> None:
        field_names = {field.name.lower() for field in fields(SemanticEvaluationResult)}
        serialized = json.loads(
            json.dumps(self._success("test-01").__dict__, ensure_ascii=False)
        )

        for forbidden in ("api_key", "authorization", "headers", "env"):
            self.assertNotIn(forbidden, field_names)
            self.assertNotIn(forbidden, serialized)

    @staticmethod
    def _success(test_id: str) -> SemanticEvaluationResult:
        return SemanticEvaluationResult.completed_now(
            run_id="run-001",
            test_id=test_id,
            model="gemini-3.5-flash",
            prompt_version="semantic-block-gemini-v0.1",
            selected_block_id="block-0001",
            reasoning_code="EARLIER_SALIENT_EVENT",
            reasoning_summary="관련 사건 block을 선택했다.",
            validator_success=True,
            candidate_start=3.04,
            candidate_end=10.96,
            iou=0.5,
            coverage=0.75,
            start_boundary_error=1.0,
            end_boundary_error=0.5,
            total_boundary_error=1.5,
            latency_seconds=2.5,
            input_tokens=100,
            output_tokens=20,
            total_tokens=120,
            provider_error=False,
            provider_error_code=None,
        )
