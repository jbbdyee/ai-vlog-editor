"""Focused synthetic evaluation for the provider-free Step 4-B baseline.

This is intentionally separate from the unavailable local eval_01..eval_05 media.
It measures proposal, selection, final interval, abstention, and failure taxonomy.
"""

from dataclasses import dataclass
import json
from time import perf_counter
from uuid import UUID

from backend.app.models import EditMemo
from backend.app.services.memo_guided_discovery import (
    DeterministicSemanticSelector,
    MemoGuidedSearchConfig,
    SelectionStatus,
    TemporalReference,
    build_search_region,
    generate_scene_proposals,
    parse_memo_intent,
    validate_selection,
)


SOURCE_ID = UUID("00000000-0000-0000-0000-000000000001")


def _segment(start: float, end: float, text: str) -> dict[str, object]:
    return {"start_seconds": start, "end_seconds": end, "text": text, "words": []}


@dataclass(frozen=True)
class Case:
    name: str
    memo_start: float
    reference: str
    segments: list[dict[str, object]]
    ground_truth: tuple[float, float] | None
    expected_status: SelectionStatus


CASES = (
    Case("clear_just_now", 16, "방금", [_segment(10, 15, "여행 장면")], (10, 15), SelectionStatus.SELECTED),
    Case("source_start_clamp", 4, "방금", [_segment(0.5, 3, "첫 장면")], (0.5, 3), SelectionStatus.SELECTED),
    Case("ambiguous_blocks", 16, "방금", [_segment(11, 14, "첫 장면"), _segment(14.2, 15, "둘째 장면")], (14.2, 15), SelectionStatus.SELECTED),
    Case("earlier_without_reference", 90, "아까", [_segment(20, 25, "예전 장면")], (20, 25), SelectionStatus.SELECTED),
    Case("no_transcript", 16, "방금", [], None, SelectionStatus.INSUFFICIENT_EVIDENCE),
)


def run() -> dict[str, object]:
    started = perf_counter()
    proposal_hits = 0
    oracle_cases = 0
    selected_correct = 0
    expected_selection_cases = 0
    final_metrics: list[dict[str, float]] = []
    abstentions: dict[str, int] = {}
    failures: dict[str, int] = {
        "MEMO_DETECTION_FAILURE": 0,
        "INTENT_PARSE_FAILURE": 0,
        "SEARCH_REGION_MISS": 0,
        "PROPOSAL_MISS": 0,
        "SELECTION_ERROR": 0,
        "SEMANTIC_AMBIGUITY": 0,
        "INSUFFICIENT_EVIDENCE": 0,
        "OUTPUT_VALIDATION_FAILURE": 0,
        "PERSISTENCE_FAILURE": 0,
    }
    proposal_counts: list[int] = []
    case_results = []
    selector = DeterministicSemanticSelector()
    config = MemoGuidedSearchConfig(transcript_gap_seconds=0.1)
    for index, case in enumerate(CASES, start=1):
        memo = _memo(index, case.memo_start, case.reference)
        intent = parse_memo_intent(memo)
        region = build_search_region(source_video_id=SOURCE_ID, memo_start_seconds=case.memo_start, duration_seconds=120, reference=intent.temporal_reference, config=config)
        proposals = generate_scene_proposals(source_video_id=SOURCE_ID, transcript_segments=case.segments, search_region=region, duration_seconds=120, config=config)
        proposal_counts.append(len(proposals))
        oracle = None
        if case.ground_truth is not None:
            oracle_cases += 1
            oracle = max(proposals, key=lambda item: _tiou((item.start_seconds, item.end_seconds), case.ground_truth), default=None)
            if oracle and _tiou((oracle.start_seconds, oracle.end_seconds), case.ground_truth) > 0:
                proposal_hits += 1
        context = {f"segment-{i:04d}": str(segment["text"]) for i, segment in enumerate(case.segments, start=1)}
        selection = selector.select(intent, region, proposals, context)
        chosen = validate_selection(selection=selection, proposals=proposals, source_video_id=SOURCE_ID, search_region=region, duration_seconds=120, config_fingerprint=proposals[0].config_fingerprint if proposals else "")
        if case.expected_status is SelectionStatus.SELECTED:
            expected_selection_cases += 1
            if chosen and case.ground_truth and _tiou((chosen.start_seconds, chosen.end_seconds), case.ground_truth) == max(_tiou((p.start_seconds, p.end_seconds), case.ground_truth) for p in proposals):
                selected_correct += 1
        if chosen and case.ground_truth:
            predicted = (chosen.start_seconds, chosen.end_seconds)
            final_metrics.append({
                "tiou": _tiou(predicted, case.ground_truth),
                "target_coverage": _coverage(predicted, case.ground_truth),
                "start_error": abs(predicted[0] - case.ground_truth[0]),
                "end_error": abs(predicted[1] - case.ground_truth[1]),
            })
        if selection.status is not SelectionStatus.SELECTED:
            abstentions[selection.reason_code] = abstentions.get(selection.reason_code, 0) + 1
            if selection.status is SelectionStatus.AMBIGUOUS:
                failures["SEMANTIC_AMBIGUITY"] += 1
            elif selection.status is SelectionStatus.INSUFFICIENT_EVIDENCE:
                failures["INSUFFICIENT_EVIDENCE"] += 1
            else:
                failures["SELECTION_ERROR"] += 1
        case_results.append({"case": case.name, "proposals": len(proposals), "status": selection.status.value, "reason": selection.reason_code})
    return {
        "dataset": "synthetic-focused-v0.1 (not eval_01..eval_05)",
        "cases": case_results,
        "proposal_recall_at_k": proposal_hits / oracle_cases,
        "average_proposal_count": sum(proposal_counts) / len(proposal_counts),
        "selection_accuracy_when_expected": selected_correct / expected_selection_cases,
        "selected_case_count": len(final_metrics),
        "mean_tiou": _mean(final_metrics, "tiou"),
        "mean_target_coverage": _mean(final_metrics, "target_coverage"),
        "mean_start_boundary_error_seconds": _mean(final_metrics, "start_error"),
        "mean_end_boundary_error_seconds": _mean(final_metrics, "end_error"),
        "abstentions": abstentions,
        "failure_taxonomy": failures,
        "processing_time_seconds": round(perf_counter() - started, 6),
        "llm_calls": 0,
        "vlm_calls": 0,
    }


def _memo(index: int, start: float, reference: str) -> EditMemo:
    return EditMemo(id=UUID(int=index), source_video_id=SOURCE_ID, transcript_id=UUID(int=100 + index), start_seconds=start, end_seconds=start + 1, transcript_text="synthetic memo", matched_trigger="AI야", matched_reference=reference, matched_action="살려줘", trigger_match_type="exact", trigger_similarity=1)


def _tiou(predicted: tuple[float, float], target: tuple[float, float]) -> float:
    intersection = max(0.0, min(predicted[1], target[1]) - max(predicted[0], target[0]))
    union = max(predicted[1], target[1]) - min(predicted[0], target[0])
    return intersection / union if union else 0.0


def _coverage(predicted: tuple[float, float], target: tuple[float, float]) -> float:
    intersection = max(0.0, min(predicted[1], target[1]) - max(predicted[0], target[0]))
    return intersection / (target[1] - target[0])


def _mean(rows: list[dict[str, float]], key: str) -> float | None:
    return sum(row[key] for row in rows) / len(rows) if rows else None


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2, sort_keys=True))
