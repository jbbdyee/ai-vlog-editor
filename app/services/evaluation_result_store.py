from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
from typing import Any


DEFAULT_GEMINI_EVALUATION_RESULT_PATH = Path(
    "evaluation/tmp/gemini-semantic-run.jsonl"
)


class EvaluationResultStoreError(ValueError):
    """Raised when an evaluation result cannot be stored or recovered safely."""


class DuplicateEvaluationResultError(EvaluationResultStoreError):
    """Raised when the same run and test have already been persisted."""


@dataclass(frozen=True)
class SemanticEvaluationResult:
    run_id: str
    test_id: str
    model: str
    prompt_version: str
    selected_block_id: str | None
    reasoning_code: str | None
    reasoning_summary: str | None
    validator_success: bool
    candidate_start: float | None
    candidate_end: float | None
    iou: float | None
    coverage: float | None
    start_boundary_error: float | None
    end_boundary_error: float | None
    total_boundary_error: float | None
    latency_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    provider_error: bool
    provider_error_code: str | None
    completed_at: str

    @classmethod
    def completed_now(cls, **values: Any) -> "SemanticEvaluationResult":
        return cls(
            completed_at=datetime.now(timezone.utc).isoformat(),
            **values,
        )


class JsonlEvaluationResultStore:
    """Durably append and recover one semantic evaluation result per line."""

    def __init__(self, path: Path = DEFAULT_GEMINI_EVALUATION_RESULT_PATH) -> None:
        self.path = Path(path)

    def append(self, result: SemanticEvaluationResult) -> None:
        _validate_result(result)
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("a+", encoding="utf-8") as result_file:
            result_file.seek(0)
            existing = _read_jsonl(result_file, source=self.path)
            key = (result.run_id, result.test_id)
            if any((item["run_id"], item["test_id"]) == key for item in existing):
                raise DuplicateEvaluationResultError(
                    f"Result already exists for run {result.run_id}, test {result.test_id}."
                )

            result_file.seek(0, os.SEEK_END)
            result_file.write(
                json.dumps(asdict(result), ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )
            result_file.flush()
            os.fsync(result_file.fileno())

    def read_all(self) -> tuple[SemanticEvaluationResult, ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as result_file:
            raw_results = _read_jsonl(result_file, source=self.path)
        try:
            return tuple(SemanticEvaluationResult(**item) for item in raw_results)
        except TypeError as exc:
            raise EvaluationResultStoreError(
                f"Evaluation result file has an invalid record: {self.path}"
            ) from exc

    def completed_test_ids(self, run_id: str) -> tuple[str, ...]:
        _validate_text(run_id, "Run ID")
        return tuple(
            result.test_id
            for result in self.read_all()
            if result.run_id == run_id
        )

    def completed_count(self, run_id: str) -> int:
        return len(self.completed_test_ids(run_id))


def _read_jsonl(result_file: Any, *, source: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(result_file, start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise EvaluationResultStoreError(
                f"Invalid JSONL at {source}, line {line_number}."
            ) from exc
        if not isinstance(record, dict):
            raise EvaluationResultStoreError(
                f"Evaluation record must be an object at {source}, line {line_number}."
            )
        records.append(record)
    return records


def _validate_result(result: SemanticEvaluationResult) -> None:
    if not isinstance(result, SemanticEvaluationResult):
        raise EvaluationResultStoreError(
            "Result must be a SemanticEvaluationResult."
        )
    for value, label in (
        (result.run_id, "Run ID"),
        (result.test_id, "Test ID"),
        (result.model, "Model"),
        (result.prompt_version, "Prompt version"),
        (result.completed_at, "Completed at"),
    ):
        _validate_text(value, label)

    for value, label in (
        (result.candidate_start, "Candidate start"),
        (result.candidate_end, "Candidate end"),
        (result.iou, "IoU"),
        (result.coverage, "Coverage"),
        (result.start_boundary_error, "Start boundary error"),
        (result.end_boundary_error, "End boundary error"),
        (result.total_boundary_error, "Total boundary error"),
        (result.latency_seconds, "Latency"),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
        ):
            raise EvaluationResultStoreError(f"{label} must be finite or null.")

    for value, label in (
        (result.input_tokens, "Input tokens"),
        (result.output_tokens, "Output tokens"),
        (result.total_tokens, "Total tokens"),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise EvaluationResultStoreError(
                f"{label} must be a non-negative integer or null."
            )


def _validate_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationResultStoreError(f"{label} must be non-empty text.")
