"""Offline grouping checks; product candidate generation is untouched."""

from dataclasses import asdict
import math
import unittest

from evaluation.run_mvp08b_event_grouping import (
    CandidateInput, EvidenceRef, _coverage, _gaps, group_candidates,
)


SOURCE = "source-synthetic"


def evidence(evidence_id: str, kind: str, start: float, end: float) -> EvidenceRef:
    modality = "TRANSCRIPT" if kind.startswith("TRANSCRIPT") else (
        "AUDIO" if kind == "AUDIO_ACTIVITY" else "VISUAL"
    )
    return EvidenceRef(evidence_id, modality, kind, start, end)


def candidate(candidate_id: str, left: EvidenceRef, right: EvidenceRef, *, source: str = SOURCE) -> CandidateInput:
    start = max(left.start_seconds, right.start_seconds)
    end = min(left.end_seconds, right.end_seconds)
    return CandidateInput(candidate_id, source, start, end, "SYNTHETIC_PAIR", (left, right), (left, right))


class OfflineEventGroupingTests(unittest.TestCase):
    def test_empty_input(self) -> None:
        self.assertEqual(group_candidates(()), ())

    def test_deterministic_order_and_original_inputs_unchanged(self) -> None:
        shared_audio_a = evidence("a1", "AUDIO_ACTIVITY", 1.0, 2.0)
        shared_audio_b = evidence("a2", "AUDIO_ACTIVITY", 1.0, 2.0)
        first = candidate("first", shared_audio_a, evidence("v1", "VISUAL_ACTIVITY", 1.0, 1.4))
        second = candidate("second", shared_audio_b, evidence("v2", "VISUAL_ACTIVITY", 1.5, 2.0))
        before = (asdict(first), asdict(second))
        forward = group_candidates((first, second))
        backward = group_candidates((second, first))
        self.assertEqual(forward, backward)
        self.assertEqual((asdict(first), asdict(second)), before)
        self.assertEqual(forward[0].candidate_ids, ("first", "second"))
        self.assertEqual({ref.id for ref in forward[0].evidence_refs}, {"a1", "a2", "v1", "v2"})
        self.assertEqual(forward[0].no_evidence_intervals, ())
        self.assertEqual(forward[0].no_corroboration_intervals, ((1.4, 1.5),))

    def test_p1_shape_retains_all_members_and_separates_later_transcript(self) -> None:
        audio1 = evidence("a1", "AUDIO_ACTIVITY", 4.08, 4.84)
        transcript1 = evidence("t1", "TRANSCRIPT_STRUCTURE", 4.64, 6.12)
        inputs = (
            candidate("motion", audio1, evidence("v1", "VISUAL_ACTIVITY", 3.8, 4.6)),
            candidate("speech-early", evidence("a2", "AUDIO_ACTIVITY", 4.08, 4.84), transcript1),
            candidate("speech-late", evidence("a3", "AUDIO_ACTIVITY", 5.54, 6.48),
                      evidence("t2", "TRANSCRIPT_STRUCTURE", 4.64, 6.12)),
            candidate("memo", evidence("a4", "AUDIO_ACTIVITY", 8.86, 11.26),
                      evidence("t3", "TRANSCRIPT_STRUCTURE", 8.44, 11.0)),
        )
        result = group_candidates(inputs)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].candidate_ids, ("motion", "speech-early", "speech-late"))
        self.assertEqual((result[0].start_seconds, result[0].end_seconds), (4.08, 6.12))
        self.assertEqual(result[0].evidence_supported_intervals, ((4.08, 6.12),))
        self.assertEqual(result[0].no_corroboration_intervals, ((4.6, 4.64), (4.84, 5.54)))
        self.assertEqual(result[1].candidate_ids, ("memo",))

    def test_unrelated_close_events_do_not_merge(self) -> None:
        first = candidate("one", evidence("a1", "AUDIO_ACTIVITY", 1.0, 1.8),
                          evidence("v1", "VISUAL_ACTIVITY", 1.0, 1.4))
        second = candidate("two", evidence("a2", "AUDIO_ACTIVITY", 1.45, 2.0),
                           evidence("v2", "VISUAL_ACTIVITY", 1.45, 1.9))
        self.assertEqual(len(group_candidates((first, second))), 2)

    def test_shared_quality_evidence_is_not_a_grouping_bridge(self) -> None:
        first = candidate("one", evidence("a1", "AUDIO_ACTIVITY", 1.0, 1.8),
                          evidence("v1", "VISUAL_ACTIVITY", 1.0, 1.4))
        second = candidate("two", evidence("a2", "AUDIO_ACTIVITY", 1.45, 2.0),
                           evidence("v2", "VISUAL_ACTIVITY", 1.45, 1.9))
        static_a = EvidenceRef("q1", "QUALITY", "STATIC_INTERVAL", 1.0, 2.0)
        static_b = EvidenceRef("q2", "QUALITY", "STATIC_INTERVAL", 1.0, 2.0)
        first = CandidateInput(first.id, first.source_id, first.start_seconds, first.end_seconds,
                               first.promotion_rule, first.promotion_evidence, (*first.linked_evidence, static_a))
        second = CandidateInput(second.id, second.source_id, second.start_seconds, second.end_seconds,
                                second.promotion_rule, second.promotion_evidence, (*second.linked_evidence, static_b))
        self.assertEqual(len(group_candidates((first, second))), 2)

    def test_long_gap_and_exact_relative_boundary_do_not_merge(self) -> None:
        transcript = evidence("t1", "TRANSCRIPT_STRUCTURE", 1.0, 10.0)
        first = candidate("one", transcript, evidence("a1", "AUDIO_ACTIVITY", 1.0, 1.2))
        far = candidate("far", evidence("t2", "TRANSCRIPT_STRUCTURE", 1.0, 10.0),
                        evidence("a2", "AUDIO_ACTIVITY", 9.0, 9.2))
        boundary = candidate("boundary", evidence("t3", "TRANSCRIPT_STRUCTURE", 1.0, 10.0),
                             evidence("a3", "AUDIO_ACTIVITY", 1.6, 1.8))
        self.assertEqual(len(group_candidates((first, far))), 2)
        self.assertEqual(len(group_candidates((first, boundary))), 2)

    def test_overlap_and_duplicate_interval_with_distinct_ids(self) -> None:
        first = candidate("a", evidence("audio-a", "AUDIO_ACTIVITY", 1.0, 2.0),
                          evidence("visual-a", "VISUAL_ACTIVITY", 1.0, 1.8))
        same = candidate("b", evidence("audio-b", "AUDIO_ACTIVITY", 1.0, 2.0),
                         evidence("visual-b", "VISUAL_ACTIVITY", 1.0, 1.8))
        overlapping = candidate("c", evidence("audio-c", "AUDIO_ACTIVITY", 1.0, 2.0),
                                evidence("visual-c", "VISUAL_ACTIVITY", 1.5, 2.0))
        result = group_candidates((overlapping, same, first))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].candidate_ids, ("a", "b", "c"))
        self.assertEqual(result[0].corroborated_intervals, ((1.0, 2.0),))

    def test_distinct_transcript_segments_do_not_chain_through_audio(self) -> None:
        first = candidate("one", evidence("a1", "AUDIO_ACTIVITY", 1.0, 3.0),
                          evidence("t1", "TRANSCRIPT_STRUCTURE", 1.0, 1.5))
        bridge = candidate("bridge", evidence("a2", "AUDIO_ACTIVITY", 1.0, 3.0),
                           evidence("v2", "VISUAL_ACTIVITY", 1.6, 2.0))
        second = candidate("two", evidence("a3", "AUDIO_ACTIVITY", 1.0, 3.0),
                           evidence("t3", "TRANSCRIPT_STRUCTURE", 2.1, 2.6))
        self.assertEqual(len(group_candidates((first, bridge, second))), 2)

    def test_invalid_ids_sources_times_and_missing_evidence_are_explicit(self) -> None:
        left = evidence("a", "AUDIO_ACTIVITY", 1.0, 2.0)
        right = evidence("v", "VISUAL_ACTIVITY", 1.0, 1.5)
        valid = candidate("one", left, right)
        cases = (
            (valid, valid),
            (valid, candidate("two", left, right, source="other")),
            (CandidateInput("bad", SOURCE, math.nan, 2.0, "PAIR", (left, right), (left, right)),),
            (CandidateInput("bad", SOURCE, 1.0005, 1.5, "PAIR", (left, right), (left, right)),),
            (CandidateInput("bad", SOURCE, 1.0, 1.4, "PAIR", (left, right), (left, right)),),
            (CandidateInput("bad", SOURCE, 1.0, 1.5, "PAIR", (left, right), (left,)),),
        )
        for items in cases:
            with self.subTest(items=items), self.assertRaises(ValueError):
                group_candidates(items)

    def test_gap_and_coverage_boundaries(self) -> None:
        self.assertEqual(_gaps(1.0, 3.0, ((1.0, 1.5), (2.0, 2.5))),
                         ((1.5, 2.0), (2.5, 3.0)))
        self.assertEqual(_coverage(((1.0, 1.5), (1.25, 2.0)), (1.0, 2.0)),
                         {"overlap_seconds": 1.0, "coverage_fraction": 1.0})
        with self.assertRaises(ValueError):
            _coverage((), (2.0, 2.0))


if __name__ == "__main__":
    unittest.main()
