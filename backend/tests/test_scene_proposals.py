"""Promotion v0.4: consolidation of raw evidence intersections into editable scenes."""

from unittest import TestCase
from uuid import uuid4

from backend.app.models import SceneEvidenceModality
from backend.app.services.autonomous_discovery import (
    SCENE_MAX_SECONDS, SCENE_MIN_SECONDS, AnalysisInterval, AnalysisUnitType, SignalEvidence,
    build_promotion_manifest, build_scene_proposals,
)

SOURCE = uuid4()
UNITS = {"TRANSCRIPT_STRUCTURE": AnalysisUnitType.TRANSCRIPT_SEGMENT, "TRANSCRIPT_REACTION_CUE": AnalysisUnitType.TRANSCRIPT_SEGMENT,
         "AUDIO_ACTIVITY": AnalysisUnitType.AUDIO_ACTIVITY, "VISUAL_ACTIVITY": AnalysisUnitType.VISUAL_ACTIVITY}
MODALITY = {"TRANSCRIPT_STRUCTURE": SceneEvidenceModality.TRANSCRIPT, "TRANSCRIPT_REACTION_CUE": SceneEvidenceModality.TRANSCRIPT,
            "AUDIO_ACTIVITY": SceneEvidenceModality.AUDIO, "VISUAL_ACTIVITY": SceneEvidenceModality.VISUAL}


def fact(kind, start, end):
    return SignalEvidence(AnalysisInterval(SOURCE, start, end, UNITS[kind], "test", "1"),
                          modality=MODALITY[kind], evidence_type=kind, payload={})


def spans(proposals):
    return [(p.start_seconds, p.end_seconds) for p in proposals]


class SceneProposalTests(TestCase):
    def test_short_nearby_intersections_merge_and_pad_to_minimum(self):
        facts = [fact("AUDIO_ACTIVITY", 4.0, 4.6), fact("TRANSCRIPT_STRUCTURE", 4.0, 6.2), fact("AUDIO_ACTIVITY", 5.5, 6.1)]
        self.assertEqual(spans(build_promotion_manifest(facts, duration_seconds=30)), [(4.0, 4.6), (5.5, 6.1)])
        result = build_scene_proposals(facts, duration_seconds=30)
        self.assertEqual(len(result), 1)
        (start, end), = spans(result)
        self.assertLessEqual(start, 4.0); self.assertGreaterEqual(end, 6.1)
        self.assertAlmostEqual(end - start, SCENE_MIN_SECONDS)

    def test_distant_scenes_stay_separate_and_never_overlap(self):
        facts = [fact("TRANSCRIPT_STRUCTURE", 0, 30), fact("AUDIO_ACTIVITY", 2.0, 2.5),
                 fact("AUDIO_ACTIVITY", 3.8, 4.0), fact("AUDIO_ACTIVITY", 20.0, 21.0)]
        result = spans(build_scene_proposals(facts, duration_seconds=30))
        self.assertEqual(len(result), 2)
        for (a_start, a_end), (b_start, b_end) in zip(result, result[1:]):
            self.assertLessEqual(a_end, b_start)
        self.assertTrue(all(end - start >= SCENE_MIN_SECONDS for start, end in result))

    def test_padding_is_clamped_to_source_bounds(self):
        result = spans(build_scene_proposals([fact("AUDIO_ACTIVITY", 0.0, 0.5), fact("TRANSCRIPT_STRUCTURE", 0.0, 0.5)],
                                             duration_seconds=10))
        self.assertEqual(result, [(0.0, 3.0)])
        short_source = spans(build_scene_proposals([fact("AUDIO_ACTIVITY", 0.5, 1.0), fact("TRANSCRIPT_STRUCTURE", 0.5, 1.0)],
                                                   duration_seconds=2))
        self.assertEqual(short_source, [(0.0, 2.0)])

    def test_merging_stops_at_maximum_scene_length(self):
        facts = [fact("TRANSCRIPT_STRUCTURE", 0, 60)] + [fact("AUDIO_ACTIVITY", s, s + 2) for s in range(0, 40, 3)]
        result = spans(build_scene_proposals(facts, duration_seconds=60))
        self.assertGreater(len(result), 1)
        self.assertTrue(all(end - start <= SCENE_MAX_SECONDS for start, end in result))

    def test_speech_motion_fallback_only_without_audio_intersections(self):
        speech_motion = [fact("TRANSCRIPT_STRUCTURE", 10, 14), fact("VISUAL_ACTIVITY", 12, 16)]
        self.assertEqual(build_promotion_manifest(speech_motion, duration_seconds=30), ())
        result = build_scene_proposals(speech_motion, duration_seconds=30)
        self.assertEqual([p.rule_id for p in result], ["TRANSCRIPT_PLUS_VISUAL_ACTIVITY"])
        self.assertEqual(spans(result), [(11.5, 14.5)])
        with_audio = speech_motion + [fact("AUDIO_ACTIVITY", 20, 24), fact("TRANSCRIPT_STRUCTURE", 20, 24)]
        rules = {p.rule_id for p in build_scene_proposals(with_audio, duration_seconds=30)}
        self.assertNotIn("TRANSCRIPT_PLUS_VISUAL_ACTIVITY", rules)

    def test_single_modality_still_abstains(self):
        self.assertEqual(build_scene_proposals([fact("VISUAL_ACTIVITY", 0, 10)], duration_seconds=30), ())
        self.assertEqual(build_scene_proposals([fact("TRANSCRIPT_STRUCTURE", 0, 10)], duration_seconds=30), ())
