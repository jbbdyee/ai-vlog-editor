from unittest import TestCase

from app.services.memo_detector import DEFAULT_MEMO_RULES, detect_edit_memos
from app.services.stt_service import STTResult, TranscriptSegment, TranscriptWord


class MemoDetectorTests(TestCase):
    def test_ai_trigger_and_banggeum_reference_are_detected(self) -> None:
        segment = self._segment("AI야 방금 장면 꼭 살려줘")

        memos = detect_edit_memos((segment,))

        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].matched_trigger, "AI야")
        self.assertEqual(memos[0].matched_reference, "방금")
        self.assertEqual(memos[0].matched_action, "살려줘")
        self.assertEqual(memos[0].transcript_text, segment.text)

    def test_spoken_ai_trigger_and_jigeum_reference_are_detected(self) -> None:
        result = STTResult(
            text="에이아이야 지금 장면 꼭 살려줘",
            segments=(self._segment("에이아이야 지금 장면 꼭 살려줘"),),
            language="ko",
            language_probability=0.99,
        )

        memos = detect_edit_memos(result)

        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].matched_trigger, "에이아이야")
        self.assertEqual(memos[0].matched_reference, "지금")

    def test_observed_eval_01_ai_trigger_variant_is_detected(self) -> None:
        segment = self._segment(
            "에이아이아 지금 장면 꼭 살려줘.",
            start_seconds=15.8,
            end_seconds=18.72,
            words=(
                self._word(15.8, 16.56, "에이아이아"),
                self._word(16.56, 16.94, "지금"),
                self._word(16.94, 17.96, "장면"),
                self._word(17.96, 18.16, "꼭"),
                self._word(18.16, 18.72, "살려줘."),
            ),
        )

        memo = detect_edit_memos((segment,))[0]

        self.assertEqual(memo.start_seconds, 15.8)
        self.assertEqual(memo.end_seconds, 18.72)
        self.assertEqual(memo.matched_trigger, "에이아이아")
        self.assertEqual(memo.matched_reference, "지금")
        self.assertEqual(memo.matched_action, "살려줘")
        self.assertEqual(memo.trigger_match_type, "similarity")
        self.assertEqual(memo.trigger_similarity, 0.8)

    def test_eval_02_latin_trigger_variant_is_detected_by_similarity(self) -> None:
        segment = self._segment(
            "아 AIA 방금 장면 꼭 살려줘",
            start_seconds=31.44,
            end_seconds=36.32,
            words=(
                self._word(31.44, 32.84, "아"),
                self._word(32.84, 33.54, "AIA"),
                self._word(33.54, 34.42, "방금"),
                self._word(34.42, 35.28, "장면"),
                self._word(35.28, 35.68, "꼭"),
                self._word(35.68, 36.32, "살려줘"),
            ),
        )

        memo = detect_edit_memos((segment,))[0]

        self.assertNotIn("AIA", DEFAULT_MEMO_RULES.triggers)
        self.assertEqual(memo.start_seconds, 32.84)
        self.assertEqual(memo.matched_trigger, "AIA")
        self.assertEqual(memo.trigger_match_type, "similarity")
        self.assertAlmostEqual(memo.trigger_similarity, 8.0 / 11.0)

    def test_eval_05_split_trigger_variant_is_detected_by_similarity(self) -> None:
        segment = self._segment(
            "에이야 에야 방금 장면 꼭 살려줘",
            start_seconds=26.84,
            end_seconds=30.24,
            words=(
                self._word(26.84, 27.86, "에이야"),
                self._word(27.86, 28.2, "에야"),
                self._word(28.2, 28.82, "방금"),
                self._word(28.82, 29.22, "장면"),
                self._word(29.22, 29.48, "꼭"),
                self._word(29.48, 30.24, "살려줘"),
            ),
        )

        memo = detect_edit_memos((segment,))[0]

        self.assertNotIn("에이야 에야", DEFAULT_MEMO_RULES.triggers)
        self.assertEqual(memo.start_seconds, 26.84)
        self.assertEqual(memo.matched_trigger, "에이야 에야")
        self.assertEqual(memo.trigger_match_type, "similarity")
        self.assertEqual(memo.trigger_similarity, 0.6)

    def test_word_timestamp_uses_first_trigger_word_start(self) -> None:
        segment = self._segment(
            "에이아이야 지금 장면 꼭 살려줘",
            start_seconds=15.5,
            words=(
                self._word(15.8, 16.0, "에이"),
                self._word(16.0, 16.3, "아이야"),
                self._word(16.3, 16.6, "지금"),
                self._word(16.6, 17.0, "장면"),
                self._word(17.0, 17.2, "꼭"),
                self._word(17.2, 17.8, "살려줘"),
            ),
        )

        memo = detect_edit_memos((segment,))[0]

        self.assertEqual(memo.start_seconds, 15.8)

    def test_segment_timestamp_is_fallback_without_words(self) -> None:
        segment = self._segment(
            "AI야 방금 장면 꼭 살려줘",
            start_seconds=16.1,
            words=(),
        )

        memo = detect_edit_memos((segment,))[0]

        self.assertEqual(memo.start_seconds, 16.1)
        self.assertEqual(memo.end_seconds, segment.end_seconds)

    def test_general_conversation_is_not_detected(self) -> None:
        segment = self._segment("오늘 카페에서 지금 장면을 다시 이야기했어")

        self.assertEqual(detect_edit_memos((segment,)), ())

    def test_unrelated_word_before_reference_and_action_is_not_detected(self) -> None:
        segment = self._segment("친구야 방금 장면 꼭 살려줘")

        self.assertEqual(detect_edit_memos((segment,)), ())

    def test_short_similar_strings_do_not_match_trigger(self) -> None:
        for text in (
            "에이야 방금 장면 꼭 살려줘",
            "아이야 방금 장면 꼭 살려줘",
            "아이디어 방금 장면 꼭 살려줘",
        ):
            with self.subTest(text=text):
                self.assertEqual(detect_edit_memos((self._segment(text),)), ())

    def test_trigger_without_action_is_not_detected(self) -> None:
        segment = self._segment("AI야 방금 장면이 재미있었어")

        self.assertEqual(detect_edit_memos((segment,)), ())

    def test_reference_without_action_is_not_detected(self) -> None:
        segment = self._segment("방금 장면이 재미있었어")

        self.assertEqual(detect_edit_memos((segment,)), ())

    def test_repeated_rule_in_one_segment_creates_only_one_memo(self) -> None:
        segment = self._segment(
            "AI야 방금 장면 살려줘, AI야 지금 장면도 살려줘"
        )

        memos = detect_edit_memos((segment,))

        self.assertEqual(len(memos), 1)

    def test_out_of_order_phrases_are_not_detected(self) -> None:
        segment = self._segment("살려줘, 방금 말한 것처럼 AI야")

        self.assertEqual(detect_edit_memos((segment,)), ())

    @staticmethod
    def _segment(
        text: str,
        *,
        start_seconds: float = 15.5,
        end_seconds: float = 18.8,
        words: tuple[TranscriptWord, ...] = (),
    ) -> TranscriptSegment:
        return TranscriptSegment(
            start_seconds=start_seconds,
            end_seconds=end_seconds,
            text=text,
            words=words,
        )

    @staticmethod
    def _word(start: float, end: float, text: str) -> TranscriptWord:
        return TranscriptWord(
            start_seconds=start,
            end_seconds=end,
            text=text,
            probability=0.95,
        )
