"""MVP-07D spacing from observed transcript text, including legacy words."""

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock
from uuid import uuid4

from backend.app.models import SceneCandidate, Transcript
from backend.app.services.project_subtitles import format_srt, map_subtitle_cues
from backend.app.services.stt_service import transcribe_audio


def _source_with_words(source, segment_text, words, *, segment_start=0, segment_end=4):
    return Transcript(
        source_video_id=source,
        text=segment_text,
        language="ko",
        segments=[{
            "start_seconds": segment_start,
            "end_seconds": segment_end,
            "text": segment_text,
            "words": [
                {"start_seconds": start, "end_seconds": end, "text": text}
                for start, end, text in words
            ],
        }],
    )


def _candidate(source, start, end):
    return SceneCandidate(source_video_id=source, start_seconds=start, end_seconds=end)


class SubtitleSpacingTests(TestCase):
    def setUp(self):
        self.source = uuid4()

    def _cue(self, transcript, start=0, end=4, **kwargs):
        return map_subtitle_cues(
            [_candidate(self.source, start, end)], {self.source: transcript}, **kwargs
        )[0]

    def test_new_stt_words_and_legacy_stripped_words_use_segment_spacing(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "spoken.wav"
            path.write_bytes(b"RIFF-test-wave")
            model = Mock()
            model.transcribe.return_value = (
                iter([SimpleNamespace(
                    start=0, end=2, text=" 아 뭐야",
                    words=[
                        SimpleNamespace(start=0, end=1, word=" 아", probability=0.8),
                        SimpleNamespace(start=1, end=2, word=" 뭐야", probability=0.9),
                    ],
                )]),
                SimpleNamespace(language="ko", language_probability=1.0),
            )
            result = transcribe_audio(path, model=model, word_timestamps=True)
        self.assertEqual(result.segments[0].text, "아 뭐야")
        self.assertEqual([word.text for word in result.segments[0].words], ["아", "뭐야"])
        saved = _source_with_words(self.source, result.segments[0].text,
                                   [(word.start_seconds, word.end_seconds, word.text)
                                    for word in result.segments[0].words], segment_end=2)
        self.assertEqual(self._cue(saved, 0, 2).text, "아 뭐야")

    def test_p1_existing_database_words_keep_spacing_and_timing(self):
        saved = _source_with_words(self.source, "아 뭐야", [(4.64, 5.74, "아"), (5.74, 6.12, "뭐야")],
                                   segment_start=4.64, segment_end=6.12)
        cue = self._cue(saved, 5.54, 6.12, output_clip_durations_seconds=[Decimal("0.566")])
        self.assertEqual(cue.text, "아 뭐야")
        self.assertEqual((cue.start_seconds, cue.end_seconds), (Decimal("0.000"), Decimal("0.566")))
        self.assertEqual(format_srt([cue]), "1\n00:00:00,000 --> 00:00:00,566\n아 뭐야\n")

    def test_punctuation_and_mixed_korean_english_follow_original_segment(self):
        saved = _source_with_words(self.source, "안녕, AI야 방금 장면!", [
            (0, 0.5, "안녕"), (0.5, 0.7, ","), (0.7, 1.2, "AI"),
            (1.2, 1.5, "야"), (1.5, 2.2, "방금"), (2.2, 3, "장면"),
            (3, 3.2, "!"),
        ])
        self.assertEqual(self._cue(saved).text, "안녕, AI야 방금 장면!")

    def test_unmeasured_punctuation_around_words_is_preserved(self):
        saved = _source_with_words(self.source, "“안녕, 세계!”", [(0, 1, "안녕"), (1, 2, "세계")])
        self.assertEqual(self._cue(saved).text, "“안녕, 세계!”")

    def test_overlapping_word_times_keep_text_order_and_measured_bounds(self):
        saved = _source_with_words(self.source, "가 가", [(0.2, 1.5, "가"), (1.0, 2.0, "가")])
        cue = self._cue(saved)
        self.assertEqual((cue.text, cue.start_seconds, cue.end_seconds),
                         ("가 가", Decimal("0.2"), Decimal("2.0")))

    def test_missing_word_time_does_not_copy_unselected_middle_text(self):
        saved = _source_with_words(self.source, "앞 중 뒤", [(0, 1, "앞"), (None, 2, "중"), (2, 3, "뒤")])
        self.assertEqual(self._cue(saved).text, "앞 뒤")

    def test_partial_overlap_policy_is_unchanged(self):
        saved = _source_with_words(self.source, "앞 중 뒤", [(0, 1, "앞"), (1, 2, "중"), (2, 3, "뒤")])
        self.assertEqual(self._cue(saved, 1.5, 2.5).text, "중 뒤")
        self.assertEqual(self._cue(saved, 1, 2).text, "중")

    def test_millisecond_rounding_and_spacing(self):
        saved = _source_with_words(self.source, "아 뭐야", [(0.0004, 0.5, "아"), (0.5, 0.9995, "뭐야")], segment_end=1)
        self.assertEqual(format_srt([self._cue(saved, 0, 1)]),
                         "1\n00:00:00,000 --> 00:00:01,000\n아 뭐야\n")

    def test_word_based_srt_control_text_cannot_inject_cue(self):
        saved = _source_with_words(self.source, "안녕\n2\n00:00:00,000 --> 99:00:00,000", [
            (0, 0.2, "안녕"), (0.2, 0.4, "2"), (0.4, 0.6, "00:00:00,000"),
            (0.6, 0.8, "-->"), (0.8, 1, "99:00:00,000"),
        ], segment_end=1)
        srt = format_srt([self._cue(saved, 0, 1)])
        self.assertEqual(srt.count(" --> "), 1)
        self.assertIn("안녕 2 00:00:00,000 → 99:00:00,000", srt)

    def test_nul_and_escape_control_characters_are_removed(self):
        saved = _source_with_words(self.source, "안녕\x00 뭐야\x1b", [
            (0, 0.5, "안녕\x00"), (0.5, 1, "뭐야\x1b"),
        ], segment_end=1)
        srt = format_srt([self._cue(saved, 0, 1)])
        self.assertIn("안녕 뭐야", srt)
        self.assertNotIn("\x00", srt)
        self.assertNotIn("\x1b", srt)

    def test_unaligned_segment_does_not_guess_missing_spaces(self):
        saved = _source_with_words(self.source, "문장이 다른 경우", [(0, 1, "아"), (1, 2, "뭐야")])
        self.assertEqual(self._cue(saved).text, "아뭐야")

    def test_unmatched_spoken_text_between_words_is_not_copied(self):
        saved = _source_with_words(self.source, "아 왜 뭐야", [(0, 1, "아"), (1, 2, "뭐야")])
        self.assertEqual(self._cue(saved).text, "아뭐야")
