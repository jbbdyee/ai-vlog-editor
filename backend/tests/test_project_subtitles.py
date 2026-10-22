"""MVP-06B planned-time subtitle mapping; no database or media execution."""

import unittest
from decimal import Decimal
from uuid import uuid4

from backend.app.models import SceneCandidate, Transcript
from backend.app.services.project_subtitles import generate_srt, map_subtitle_cues


def candidate(source, start, end):
    return SceneCandidate(source_video_id=source, start_seconds=start, end_seconds=end)


def transcript(source, segments):
    return Transcript(source_video_id=source, text="", language="ko", segments=segments)


def segment(start, end, text, words=None):
    item = {"start_seconds": start, "end_seconds": end, "text": text}
    if words is not None:
        item["words"] = [
            {"start_seconds": a, "end_seconds": b, "text": t}
            for a, b, t in words
        ]
    return item


class ProjectSubtitleTests(unittest.TestCase):
    def setUp(self):
        self.source = uuid4()

    def test_single_candidate_and_word_grouping(self):
        item = candidate(self.source, 2, 5)
        saved = transcript(self.source, [segment(2.1, 3.0, "잘못된 전체 문장", [(2.1, 2.4, "안녕"), (2.5, 3, " 하세요")])])
        self.assertEqual(generate_srt([item], {self.source: saved}), "1\n00:00:00,100 --> 00:00:01,000\n안녕 하세요\n")

    def test_front_of_utterance_only(self):
        saved = transcript(self.source, [segment(1, 4, "전체", [(1, 2, "앞"), (2, 3, " 중"), (3, 4, " 뒤")])])
        self.assertEqual(map_subtitle_cues([candidate(self.source, 1, 2.5)], {self.source: saved})[0].text, "앞 중")

    def test_back_of_utterance_only(self):
        saved = transcript(self.source, [segment(1, 4, "전체", [(1, 2, "앞"), (2, 3, " 중"), (3, 4, " 뒤")])])
        cues = map_subtitle_cues([candidate(self.source, 2.5, 4)], {self.source: saved})
        self.assertEqual((cues[0].start_seconds, cues[0].text), (Decimal(0), "중 뒤"))

    def test_multiple_sources_keep_separate_timelines(self):
        other = uuid4()
        data = {self.source: transcript(self.source, [segment(1, 2, "첫째")]), other: transcript(other, [segment(1, 2, "둘째")])}
        cues = map_subtitle_cues([candidate(self.source, 0, 3), candidate(other, 0, 3)], data)
        self.assertEqual([(cue.start_seconds, cue.text) for cue in cues], [(Decimal(1), "첫째"), (Decimal(4), "둘째")])

    def test_changed_order(self):
        other = uuid4()
        data = {self.source: transcript(self.source, [segment(0, 1, "A")]), other: transcript(other, [segment(0, 1, "B")])}
        cues = map_subtitle_cues([candidate(other, 0, 1), candidate(self.source, 0, 1)], data)
        self.assertEqual([cue.text for cue in cues], ["B", "A"])

    def test_repeated_candidate_input(self):
        item = candidate(self.source, 0, 2)
        saved = transcript(self.source, [segment(0.5, 1, "반복")])
        self.assertEqual([cue.start_seconds for cue in map_subtitle_cues([item, item], {self.source: saved})], [Decimal("0.5"), Decimal("2.5")])

    def test_subtitle_free_clip_still_advances_offset(self):
        item = candidate(self.source, 0, 4)
        saved = transcript(self.source, [segment(5, 6, "뒤")])
        cues = map_subtitle_cues([item, candidate(self.source, 4, 7)], {self.source: saved})
        self.assertEqual(cues[0].start_seconds, Decimal(5))

    def test_missing_words_full_segment_uses_observed_segment_times(self):
        saved = transcript(self.source, [segment(1, 2, "한국어", None)])
        self.assertEqual(map_subtitle_cues([candidate(self.source, 0, 3)], {self.source: saved})[0].text, "한국어")
        self.assertEqual(map_subtitle_cues([candidate(self.source, 1.5, 3)], {self.source: saved}), ())

    def test_invalid_words_do_not_get_inferred_times(self):
        saved = transcript(self.source, [segment(0, 3, "추정 금지", [(float("nan"), 2, "가"), (2, 1, "나")])])
        self.assertEqual(map_subtitle_cues([candidate(self.source, 0, 3)], {self.source: saved}), ())

    def test_boundary_crossing_word_clipped_and_touch_only_excluded(self):
        saved = transcript(self.source, [segment(0, 4, "전체", [(0, 1, "제외"), (1, 2, "경계"), (2, 3, "끝")])])
        cues = map_subtitle_cues([candidate(self.source, 1, 2)], {self.source: saved})
        self.assertEqual((cues[0].text, cues[0].start_seconds, cues[0].end_seconds), ("경계", Decimal(0), Decimal(1)))
        crossing = map_subtitle_cues([candidate(self.source, 1.5, 2.5)], {self.source: saved})
        self.assertEqual(crossing[0].text, "경계끝")

    def test_zero_start_and_millisecond_rounding(self):
        saved = transcript(self.source, [segment(0, 1, "한글", [(0.0004, 0.9995, "한글")])])
        self.assertIn("00:00:00,000 --> 00:00:01,000", generate_srt([candidate(self.source, 0, 1)], {self.source: saved}))

    def test_special_characters_and_newline_cannot_inject_cue(self):
        saved = transcript(self.source, [segment(0, 1, "안녕\n2\n00:00:00,000 --> 99:00:00,000 & 반가워")])
        result = generate_srt([candidate(self.source, 0, 1)], {self.source: saved})
        self.assertEqual(result.count(" --> "), 1)
        self.assertIn("안녕 2 00:00:00,000 → 99:00:00,000 & 반가워", result)

    def test_empty_plan_and_no_transcript(self):
        self.assertEqual(generate_srt([], {}), "")
        self.assertEqual(generate_srt([candidate(self.source, 0, 1)], {}), "")

    def test_long_timeline_hour_conversion(self):
        saved = transcript(self.source, [segment(3600.1, 3601, "시각")])
        result = generate_srt([candidate(self.source, 0, 3602)], {self.source: saved})
        self.assertIn("01:00:00,100 --> 01:00:01,000", result)

    def test_measured_output_lengths_scale_cues_and_offsets(self):
        item = candidate(self.source, 0, 1)
        saved = transcript(self.source, [segment(0.25, 0.75, "반올림")])
        cues = map_subtitle_cues(
            [item, item], {self.source: saved}, output_clip_durations_seconds=[1.2, 0.8],
        )
        self.assertEqual(
            [(cue.start_seconds, cue.end_seconds) for cue in cues],
            [(Decimal("0.300"), Decimal("0.900")),
             (Decimal("1.400"), Decimal("1.800"))],
        )

    def test_invalid_measured_lengths_rejected(self):
        item = candidate(self.source, 0, 1)
        with self.assertRaises(ValueError):
            map_subtitle_cues([item], {}, output_clip_durations_seconds=[])
        with self.assertRaises(ValueError):
            map_subtitle_cues([item], {}, output_clip_durations_seconds=[float("nan")])

    def test_source_mismatch_and_invalid_candidate_rejected(self):
        with self.assertRaises(ValueError):
            map_subtitle_cues([candidate(self.source, 0, 1)], {self.source: transcript(uuid4(), [])})
        with self.assertRaises(ValueError):
            map_subtitle_cues([candidate(self.source, 2, 1)], {})


if __name__ == "__main__":
    unittest.main()
