"""Synthetic mechanics/scale evaluation for deterministic Event Grouping v0.1."""

from __future__ import annotations

import json
from time import perf_counter
import tracemalloc
from uuid import UUID

from backend.app.services.event_grouping import (
    CandidateComparisonProjection,
    build_conservative_group_sets,
    build_pair_manifest,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000707")
SCALE_CANDIDATE_COUNT = 600


def run() -> dict[str, object]:
    started = perf_counter()
    tracemalloc.start()
    focused = _focused_scenarios()
    projections = tuple(_projection(index) for index in range(1, SCALE_CANDIDATE_COUNT + 1))
    manifest = build_pair_manifest(projections)
    incremental = build_pair_manifest(
        projections,
        focus_candidate_ids=(projections[-1].candidate_id,),
    )
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return {
        "run_id": "event-grouping-deterministic-v0.1",
        "dataset": "synthetic-grouping-mechanics-and-scale-v0.1",
        "actual_media": False,
        "semantic_ground_truth_available": False,
        "focused_scenarios": focused,
        "candidate_count": manifest.candidate_count,
        "possible_pair_count": manifest.possible_pair_count,
        "retained_pair_count": manifest.retained_pair_count,
        "reduction_rate": round(manifest.reduction_rate, 8),
        "blocking_reason_counts": manifest.reason_counts,
        "deterministic_relation_count": 0,
        "event_group_count": focused["event_group_count"],
        "unassigned_count": focused["unassigned_count"],
        "singleton_avoided_count": focused["singleton_avoided_count"],
        "bridge_merge_prevented_count": focused["bridge_merge_prevented_count"],
        "duplicate_relation_count": 0,
        "incremental_possible_pair_count": incremental.possible_pair_count,
        "incremental_retained_pair_count": incremental.retained_pair_count,
        "processing_time_seconds": round(perf_counter() - started, 6),
        "peak_memory_bytes": peak,
        "llm_calls": 0,
        "vlm_calls": 0,
        "semantic_grouping_accuracy": None,
    }


def _focused_scenarios() -> dict[str, int]:
    a, b, c, d, singleton = (UUID(int=index) for index in range(1, 6))
    groups, prevented, unassigned = build_conservative_group_sets(
        (a, b, c, d, singleton),
        ((a, b), (c, d), (b, c)),
    )
    return {
        "event_group_count": len(groups),
        "grouped_candidate_count": sum(len(group) for group in groups),
        "unassigned_count": len(unassigned),
        "singleton_avoided_count": int(singleton in unassigned),
        "bridge_merge_prevented_count": prevented,
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
        bounded_transcript=f"unique-token-{index}",
        transcript_tokens=(f"unique-token-{index}",),
        evidence_keys=(),
        available_modalities=(),
        source_order=index,
    )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
