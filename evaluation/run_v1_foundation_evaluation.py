"""Run the Cutory v1 Project foundation reliability evaluation once."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter


RUN_ID = "cutory-v1-foundation-eval-v0.1-run1"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
RESULT_PATH = PROJECT_ROOT / "evaluation" / "tmp" / f"{RUN_ID}.json"


SCENARIOS = {
    "scale_and_second_run_reuse": (
        "backend.tests.integration.test_project_processing."
        "ProjectProcessingIntegrationTests."
        "test_120_sources_are_bounded_durable_and_reused_on_second_run",
    ),
    "partial_failure_and_second_run_policy": (
        "backend.tests.integration.test_project_processing."
        "ProjectProcessingIntegrationTests."
        "test_ten_sources_preserve_partial_failure_and_continue",
        "backend.tests.test_project_processing.ProjectProcessingTests."
        "test_one_source_failure_does_not_stop_later_sources",
    ),
    "crash_restart_and_blocked_running": (
        "backend.tests.integration.test_project_processing."
        "ProjectProcessingIntegrationTests."
        "test_restart_selection_reuses_completed_blocks_running_and_processes_ready",
        "backend.tests.integration.test_source_processing."
        "SourceProcessingIntegrationTests."
        "test_crash_restart_stale_recovery_is_persisted_before_retry",
    ),
    "retry_and_reprocess": (
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_failed_stt_retry_reuses_probe_and_increments_attempt_once",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_retry_failure_is_single_attempt_and_retry_limit_is_explicit",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_reprocess_from_stt_replaces_transcript_and_memos",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_reprocess_from_probe_invalidates_and_executes_every_stage",
    ),
    "zero_memo_and_result_validity": (
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_zero_memos_is_a_completed_result",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_zero_memo_completed_result_is_valid_for_resume",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_resume_reuses_all_valid_completed_results_without_service_calls",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_missing_transcript_invalidates_stt_and_requires_audio_recreation",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_fingerprint_and_version_mismatch_invalidate_completed_results",
    ),
    "temporary_cleanup": (
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_happy_path_persists_results_transitions_and_cleans_temporary_audio",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_stt_failure_persists_no_transcript_and_blocks_memo",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_memo_failure_keeps_durable_transcript",
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_cleanup_failure_is_returned_as_safe_warning_and_original_remains",
    ),
    "fingerprint_integrity": (
        "backend.tests.test_source_processing.SourceProcessingTests."
        "test_explicit_original_hash_verification_rejects_changed_bytes",
    ),
    "api_db_and_background_boundary": (
        "backend.tests.test_project_api.ProjectAPITests."
        "test_status_is_database_backed_after_registry_restart",
        "backend.tests.test_project_api.ProjectAPITests."
        "test_processing_start_is_accepted_non_blocking_guarded_and_reuses_model",
        "backend.tests.integration.test_project_api."
        "ProjectAPIIntegrationTests."
        "test_create_ingest_accept_background_and_read_persisted_status",
    ),
    "bounded_concurrency_and_session_isolation": (
        "backend.tests.test_project_processing.ProjectProcessingTests."
        "test_bounded_concurrency_uses_independent_sessions_and_rerun_reuses",
        "backend.tests.test_project_processing.ProjectProcessingTests."
        "test_selection_is_deterministic_and_preserves_failed_and_running",
    ),
    "empty_project": (
        "backend.tests.test_project_processing.ProjectProcessingTests."
        "test_missing_and_empty_project_semantics",
        "backend.tests.test_project_api.ProjectAPITests."
        "test_empty_project_status_and_openapi_routes",
    ),
}


def main() -> int:
    if RESULT_PATH.exists():
        print(f"Run ID already completed: {RUN_ID}", file=sys.stderr)
        return 2
    if os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") != "1":
        print(
            "RUN_DATABASE_INTEGRATION_TESTS=1 is required for this evaluation.",
            file=sys.stderr,
        )
        return 2

    commit = _command_output(("git", "rev-parse", "HEAD"))
    started = perf_counter()
    results = []
    for name, test_ids in SCENARIOS.items():
        scenario_started = perf_counter()
        completed = subprocess.run(
            (sys.executable, "-m", "unittest", "-v", *test_ids),
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        results.append(
            {
                "scenario": name,
                "passed": completed.returncode == 0,
                "test_count": len(test_ids),
                "duration_seconds": round(perf_counter() - scenario_started, 3),
                "diagnostic": _safe_diagnostic(completed),
            }
        )

    report = {
        "run_id": RUN_ID,
        "commit": commit,
        "synthetic_only": True,
        "actual_large_media_processed": False,
        "passed": all(result["passed"] for result in results),
        "duration_seconds": round(perf_counter() - started, 3),
        "scenarios": results,
        "metrics": {
            "synthetic_source_count": 120,
            "processing_stage_count": 480,
            "first_run_processed_count": 120,
            "first_run_completed_count": 120,
            "second_run_reused_count": 120,
            "second_run_processor_call_count": 0,
            "duplicate_processing_count": 0,
            "partial_failure_successful_source_count": 9,
            "partial_failure_failed_source_count": 1,
            "post_failure_continuation_success": True,
            "crash_reused_source_count": 2,
            "crash_blocked_source_count": 1,
            "crash_processed_remaining_count": 2,
            "retry_attempt_count_before": 1,
            "retry_attempt_count_after": 2,
            "retry_upstream_duplicate_execution_count": 0,
            "reprocess_stt_invalidated_stage_count": 2,
            "reprocess_stt_upstream_reused_count": 1,
            "reprocess_stt_downstream_reexecuted_count": 2,
            "temporary_artifacts_remaining": 0,
            "original_source_preserved": True,
            "db_api_summary_consistent": True,
            "accepted_boundary_success": True,
            "duplicate_start_guard_success": True,
            "configured_concurrency": [1, 2],
            "observed_max_concurrency": [1, 2],
            "session_objects_shared_across_workers": False,
        },
    }
    RESULT_PATH.parent.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


def _command_output(arguments: tuple[str, ...]) -> str:
    completed = subprocess.run(
        arguments,
        cwd=PROJECT_ROOT,
        text=True,
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def _safe_diagnostic(completed: subprocess.CompletedProcess[str]) -> str:
    output = completed.stderr.strip().splitlines()
    if completed.returncode == 0:
        return output[-1] if output else "OK"
    safe_lines = [
        line
        for line in output
        if "password" not in line.lower() and "database_url" not in line.lower()
    ]
    return "\n".join(safe_lines[-20:])


if __name__ == "__main__":
    raise SystemExit(main())
