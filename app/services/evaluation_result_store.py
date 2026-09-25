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
DEFAULT_VLM_SMOKE_RESULT_PATH = Path("evaluation/tmp/local-vlm-smoke.jsonl")
DEFAULT_LOCAL_VLM_EVALUATION_RESULT_PATH = Path(
    "evaluation/tmp/local-vlm-proposal-run.jsonl"
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


@dataclass(frozen=True)
class VLMSmokeTestResult:
    run_id: str
    test_type: str
    model: str
    runtime: str
    num_ctx: int | None
    temperature: float
    image_count: int
    input_tokens: int | None
    selected_proposal_id: str | None
    reasoning_code: str | None
    reasoning_summary: str | None
    structured_output_success: bool
    validator_success: bool
    latency_seconds: float | None
    output_tokens: int | None
    total_tokens: int | None
    provider_error: bool
    provider_error_code: str | None
    completed_at: str
    provider_http_status: int | None = None
    provider_error_message: str | None = None
    provider_failure_stage: str | None = None
    provider_timeout: bool = False
    provider_model: str | None = None
    provider_image_count: int | None = None
    provider_num_ctx: int | None = None
    proposal_count: int | None = None
    logical_source_frame_count: int | None = None
    actual_vlm_image_count: int | None = None
    provider: str | None = None

    @classmethod
    def completed_now(cls, **values: Any) -> "VLMSmokeTestResult":
        return cls(completed_at=datetime.now(timezone.utc).isoformat(), **values)


@dataclass(frozen=True)
class LocalVLMEvaluationResult:
    run_id: str
    test_id: str
    model: str
    runtime: str
    proposal_count: int
    image_count: int
    selected_proposal_id: str | None
    reasoning_code: str | None
    reasoning_summary: str | None
    structured_output_success: bool
    validator_success: bool
    candidate_start: float | None
    candidate_end: float | None
    iou: float | None
    coverage: float | None
    start_boundary_error: float | None
    end_boundary_error: float | None
    total_boundary_error: float | None
    oracle_best_proposal_id: str | None
    oracle_best_iou: float | None
    oracle_best_coverage: float | None
    oracle_best_total_boundary_error: float | None
    latency_seconds: float | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    provider_error: bool
    provider_error_code: str | None
    completed_at: str
    provider: str | None = None
    oracle_best_start: float | None = None
    oracle_best_end: float | None = None
    preparation_error: bool = False
    preparation_error_code: str | None = None
    provider_http_status: int | None = None
    provider_error_message: str | None = None
    provider_failure_stage: str | None = None
    provider_timeout: bool = False
    provider_model: str | None = None
    provider_image_count: int | None = None
    provider_num_ctx: int | None = None
    logical_source_frame_count: int | None = None
    actual_vlm_image_count: int | None = None

    @classmethod
    def completed_now(cls, **values: Any) -> "LocalVLMEvaluationResult":
        return cls(completed_at=datetime.now(timezone.utc).isoformat(), **values)


class JsonlEvaluationResultStore:
    """Durably append and recover one semantic evaluation result per line."""

    def __init__(self, path: Path = DEFAULT_GEMINI_EVALUATION_RESULT_PATH) -> None:
        self.path = Path(path)

    def append(self, result: SemanticEvaluationResult) -> None:
        _validate_result(result)
        _append_jsonl_record(
            self.path,
            asdict(result),
            duplicate=lambda item: (
                item.get("run_id"), item.get("test_id")
            )
            == (result.run_id, result.test_id),
            duplicate_message=(
                f"Result already exists for run {result.run_id}, "
                f"test {result.test_id}."
            ),
        )

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


class JsonlVLMSmokeResultStore:
    """Durably append and recover one VLM smoke result per run ID."""

    def __init__(self, path: Path = DEFAULT_VLM_SMOKE_RESULT_PATH) -> None:
        self.path = Path(path)

    def append(self, result: VLMSmokeTestResult) -> None:
        _validate_smoke_result(result)
        _append_jsonl_record(
            self.path,
            asdict(result),
            duplicate=lambda item: item.get("run_id") == result.run_id,
            duplicate_message=f"Smoke result already exists for run {result.run_id}.",
        )

    def read_all(self) -> tuple[VLMSmokeTestResult, ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as result_file:
            raw_results = _read_jsonl(result_file, source=self.path)
        try:
            results = tuple(VLMSmokeTestResult(**item) for item in raw_results)
        except TypeError as exc:
            raise EvaluationResultStoreError(
                f"VLM smoke result file has an invalid record: {self.path}"
            ) from exc
        for result in results:
            _validate_smoke_result(result)
        return results

    def has_run(self, run_id: str) -> bool:
        _validate_text(run_id, "Run ID")
        return any(result.run_id == run_id for result in self.read_all())

    def get(self, run_id: str) -> VLMSmokeTestResult | None:
        _validate_text(run_id, "Run ID")
        return next(
            (result for result in self.read_all() if result.run_id == run_id),
            None,
        )


class JsonlLocalVLMEvaluationResultStore:
    """Durably append one local VLM evaluation result per run and test."""

    def __init__(
        self, path: Path = DEFAULT_LOCAL_VLM_EVALUATION_RESULT_PATH
    ) -> None:
        self.path = Path(path)

    def append(self, result: LocalVLMEvaluationResult) -> None:
        _validate_local_vlm_evaluation_result(result)
        _append_jsonl_record(
            self.path,
            asdict(result),
            duplicate=lambda item: (
                item.get("run_id"), item.get("test_id")
            )
            == (result.run_id, result.test_id),
            duplicate_message=(
                f"Local VLM result already exists for run {result.run_id}, "
                f"test {result.test_id}."
            ),
        )

    def read_all(self) -> tuple[LocalVLMEvaluationResult, ...]:
        if not self.path.exists():
            return ()
        with self.path.open("r", encoding="utf-8") as result_file:
            raw_results = _read_jsonl(result_file, source=self.path)
        try:
            results = tuple(LocalVLMEvaluationResult(**item) for item in raw_results)
        except TypeError as exc:
            raise EvaluationResultStoreError(
                f"Local VLM result file has an invalid record: {self.path}"
            ) from exc
        for result in results:
            _validate_local_vlm_evaluation_result(result)
        return results

    def completed_test_ids(self, run_id: str) -> tuple[str, ...]:
        _validate_text(run_id, "Run ID")
        return tuple(
            result.test_id for result in self.read_all() if result.run_id == run_id
        )

    def completed_count(self, run_id: str) -> int:
        return len(self.completed_test_ids(run_id))


def _append_jsonl_record(
    path: Path,
    record: dict[str, Any],
    *,
    duplicate: Any,
    duplicate_message: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as result_file:
        result_file.seek(0)
        existing = _read_jsonl(result_file, source=path)
        if any(duplicate(item) for item in existing):
            raise DuplicateEvaluationResultError(duplicate_message)

        result_file.seek(0, os.SEEK_END)
        result_file.write(
            json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        )
        result_file.flush()
        os.fsync(result_file.fileno())


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


def _validate_smoke_result(result: VLMSmokeTestResult) -> None:
    if not isinstance(result, VLMSmokeTestResult):
        raise EvaluationResultStoreError("Result must be a VLMSmokeTestResult.")
    for value, label in (
        (result.run_id, "Run ID"),
        (result.test_type, "Test type"),
        (result.model, "Model"),
        (result.runtime, "Runtime"),
        (result.completed_at, "Completed at"),
    ):
        _validate_text(value, label)
    if result.test_type != "vlm_smoke":
        raise EvaluationResultStoreError("Test type must be vlm_smoke.")
    for value, label in (
        (result.num_ctx, "Context size"),
        (result.image_count, "Image count"),
        (result.input_tokens, "Input tokens"),
        (result.output_tokens, "Output tokens"),
        (result.total_tokens, "Total tokens"),
        (result.provider_image_count, "Provider image count"),
        (result.provider_num_ctx, "Provider context size"),
        (result.proposal_count, "Proposal count"),
        (result.logical_source_frame_count, "Logical source frame count"),
        (result.actual_vlm_image_count, "Actual VLM image count"),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise EvaluationResultStoreError(
                f"{label} must be a non-negative integer or null."
            )
    _validate_provider_diagnostics(result)
    if (result.num_ctx is not None and result.num_ctx <= 0) or result.image_count <= 0:
        raise EvaluationResultStoreError(
            "Context size must be null or positive, and image count must be positive."
        )
    if result.provider is not None:
        _validate_text(result.provider, "Provider")
    for value, label in (
        (result.temperature, "Temperature"),
        (result.latency_seconds, "Latency"),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise EvaluationResultStoreError(
                f"{label} must be a finite non-negative number or null."
            )


def _validate_local_vlm_evaluation_result(
    result: LocalVLMEvaluationResult,
) -> None:
    if not isinstance(result, LocalVLMEvaluationResult):
        raise EvaluationResultStoreError(
            "Result must be a LocalVLMEvaluationResult."
        )
    for value, label in (
        (result.run_id, "Run ID"),
        (result.test_id, "Test ID"),
        (result.model, "Model"),
        (result.runtime, "Runtime"),
        (result.completed_at, "Completed at"),
    ):
        _validate_text(value, label)
    if result.oracle_best_proposal_id is not None:
        _validate_text(result.oracle_best_proposal_id, "Oracle proposal ID")
    for value, label in (
        (result.proposal_count, "Proposal count"),
        (result.image_count, "Image count"),
        (result.input_tokens, "Input tokens"),
        (result.output_tokens, "Output tokens"),
        (result.total_tokens, "Total tokens"),
        (result.provider_image_count, "Provider image count"),
        (result.provider_num_ctx, "Provider context size"),
        (result.logical_source_frame_count, "Logical source frame count"),
        (result.actual_vlm_image_count, "Actual VLM image count"),
    ):
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, int) or value < 0
        ):
            raise EvaluationResultStoreError(
                f"{label} must be a non-negative integer or null."
            )
    _validate_provider_diagnostics(result)
    if result.proposal_count < 0 or result.image_count < 0:
        raise EvaluationResultStoreError(
            "Proposal count and image count must not be negative."
        )
    if not result.preparation_error and (
        result.proposal_count == 0 or result.image_count == 0
    ):
        raise EvaluationResultStoreError(
            "Prepared results require proposals and images."
        )
    for value, label in (
        (result.candidate_start, "Candidate start"),
        (result.candidate_end, "Candidate end"),
        (result.iou, "IoU"),
        (result.coverage, "Coverage"),
        (result.start_boundary_error, "Start boundary error"),
        (result.end_boundary_error, "End boundary error"),
        (result.total_boundary_error, "Total boundary error"),
        (result.oracle_best_iou, "Oracle IoU"),
        (result.oracle_best_coverage, "Oracle coverage"),
        (result.oracle_best_total_boundary_error, "Oracle total boundary error"),
        (result.latency_seconds, "Latency"),
    ):
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
        ):
            raise EvaluationResultStoreError(
                f"{label} must be a finite non-negative number or null."
            )


def _validate_text(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationResultStoreError(f"{label} must be non-empty text.")


def _validate_provider_diagnostics(result: object) -> None:
    status = getattr(result, "provider_http_status")
    if status is not None and (
        isinstance(status, bool) or not isinstance(status, int) or not 100 <= status <= 599
    ):
        raise EvaluationResultStoreError(
            "Provider HTTP status must be an HTTP status code or null."
        )
    for field_name, label in (
        ("provider_error_message", "Provider error message"),
        ("provider_failure_stage", "Provider failure stage"),
        ("provider_model", "Provider model"),
    ):
        value = getattr(result, field_name)
        if value is not None:
            _validate_text(value, label)
    if not isinstance(getattr(result, "provider_timeout"), bool):
        raise EvaluationResultStoreError("Provider timeout must be boolean.")
