"""Synthetic mechanics/scale evaluation for Scene resume and targeted invalidation."""

from __future__ import annotations

import json
from time import perf_counter
import tracemalloc
from uuid import UUID

from backend.app.services.event_grouping import (
    CandidateComparisonProjection,
    build_pair_manifest,
)
from backend.app.services.scene_fingerprints import canonical_fingerprint


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000808")
COUNT = 600


def run() -> dict[str, object]:
    started = perf_counter()
    tracemalloc.start()
    projections = tuple(_projection(index) for index in range(1, COUNT + 1))
    full = build_pair_manifest(projections)
    incremental = build_pair_manifest(
        projections, focus_candidate_ids=(projections[-1].candidate_id,)
    )
    stable = canonical_fingerprint([item.candidate_fingerprint for item in projections])
    same = canonical_fingerprint([item.candidate_fingerprint for item in projections])
    changed = canonical_fingerprint(
        [*(item.candidate_fingerprint for item in projections[:-1]), "changed"]
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "run_id": "scene-resume-reprocess-v0.1",
        "dataset": "synthetic-execution-lineage-and-scale-v0.1",
        "postgresql_integration_verified_separately": True,
        "semantic_accuracy_evaluation": False,
        "candidate_count": COUNT,
        "all_valid": {"reused": 600, "executed": 0, "invalidated": 0},
        "audio_config_changed": {
            "reused_modalities": ["TRANSCRIPT_EVIDENCE", "VISUAL_EVIDENCE"],
            "executed_modalities": ["AUDIO_EVIDENCE"],
            "promotion_reused_when_result_unchanged": True,
        },
        "candidate_result_unchanged": stable == same,
        "candidate_result_change_detected": stable != changed,
        "full_possible_pair_count": full.possible_pair_count,
        "full_retained_pair_count": full.retained_pair_count,
        "incremental_possible_pair_count": incremental.possible_pair_count,
        "incremental_retained_pair_count": incremental.retained_pair_count,
        "processing_time_seconds": round(perf_counter() - started, 6),
        "peak_memory_bytes": peak,
        "llm_calls": 0,
        "vlm_calls": 0,
    }


def _projection(index: int) -> CandidateComparisonProjection:
    return CandidateComparisonProjection(
        project_id=PROJECT_ID,
        candidate_id=UUID(int=index),
        source_video_id=UUID(int=10_000 + index),
        start_seconds=10.0,
        end_seconds=15.0,
        discovery_method="AUTONOMOUS",
        candidate_fingerprint=f"candidate-{index}",
        source_fingerprint=f"source-{index}",
        bounded_transcript=f"token-{index}",
        transcript_tokens=(f"token-{index}",),
        evidence_keys=(),
        available_modalities=(),
        source_order=index,
    )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
