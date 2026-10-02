"""Synthetic, signal-level evaluation for the Step 5-B deterministic baseline."""

import json
from time import perf_counter
from uuid import UUID

from backend.app.models import SceneEvidenceModality
from backend.app.services.autonomous_discovery import (
    AnalysisInterval,
    AnalysisUnitType,
    SignalEvidence,
    build_promotion_manifest,
)


SOURCE_ID = UUID("00000000-0000-0000-0000-000000000005")
DURATION = 48.0


def run() -> dict[str, object]:
    started = perf_counter()
    cases = (
        (
            "reaction_plus_audio",
            (
                _fact(16, 20, SceneEvidenceModality.TRANSCRIPT, "TRANSCRIPT_REACTION_CUE"),
                _fact(16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),
            ),
            (),
        ),
        (
            "quality_only",
            (
                _fact(20, 40, SceneEvidenceModality.QUALITY, "LONG_SILENCE"),
                _fact(20, 40, SceneEvidenceModality.QUALITY, "STATIC_INTERVAL"),
            ),
            (),
        ),
        (
            "audio_visual_with_partial_transcript_failure",
            (
                _fact(40, 48, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),
                _fact(40, 48, SceneEvidenceModality.VISUAL, "VISUAL_ACTIVITY"),
            ),
            ("TRANSCRIPT_ANALYSIS_FAILED",),
        ),
    )
    candidate_count = 0
    candidate_duration = 0.0
    abstentions = 0
    partial_failures = 0
    evidence_counts: dict[str, int] = {}
    duplicate_count = 0
    results = []
    for name, facts, warnings in cases:
        for fact in facts:
            evidence_counts[fact.modality.value] = evidence_counts.get(fact.modality.value, 0) + 1
        proposals = build_promotion_manifest(facts + facts, duration_seconds=DURATION)
        without_duplicates = build_promotion_manifest(facts, duration_seconds=DURATION)
        duplicate_count += max(0, len(proposals) - len(without_duplicates))
        candidate_count += len(proposals)
        duration = sum(item.end_seconds - item.start_seconds for item in proposals)
        candidate_duration += duration
        abstentions += int(not proposals)
        partial_failures += int(bool(warnings))
        results.append({"case": name, "candidate_count": len(proposals), "candidate_duration_seconds": duration, "warnings": list(warnings)})
    return {
        "dataset": "synthetic-signal-scenarios-v0.1",
        "actual_media": False,
        "ground_truth_available": False,
        "cases": results,
        "candidate_count": candidate_count,
        "candidate_duration_seconds": candidate_duration,
        "candidate_duration_ratio": candidate_duration / (DURATION * len(cases)),
        "candidates_per_minute": candidate_count / (DURATION * len(cases) / 60),
        "evidence_counts": evidence_counts,
        "abstention_count": abstentions,
        "partial_failure_count": partial_failures,
        "exact_duplicate_output_count": duplicate_count,
        "candidate_recall": None,
        "candidate_precision": None,
        "reduction_rate": None,
        "gt_recall_after_reduction": None,
        "failure_taxonomy": {
            "MODALITY_PARTIAL_FAILURE": partial_failures,
            "INSUFFICIENT_CROSS_MODAL_EVIDENCE": abstentions,
            "ALL_MODALITIES_FAILED": 0,
            "PROMOTION_FAILURE": 0,
            "PERSISTENCE_FAILURE": 0,
        },
        "llm_calls": 0,
        "vlm_calls": 0,
        "processing_time_seconds": round(perf_counter() - started, 6),
    }


def _fact(start, end, modality, evidence_type):
    unit = {
        SceneEvidenceModality.TRANSCRIPT: AnalysisUnitType.TRANSCRIPT_SEGMENT,
        SceneEvidenceModality.AUDIO: AnalysisUnitType.AUDIO_ACTIVITY,
        SceneEvidenceModality.VISUAL: AnalysisUnitType.VISUAL_ACTIVITY,
        SceneEvidenceModality.QUALITY: AnalysisUnitType.STATIC_INTERVAL,
    }[modality]
    return SignalEvidence(
        AnalysisInterval(SOURCE_ID, start, end, unit, "synthetic-eval", "v0.1"),
        modality,
        evidence_type,
        {"measurement": 1},
    )


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
