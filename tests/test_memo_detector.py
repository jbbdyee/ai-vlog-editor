from unittest import TestCase

from app.services.memo_detector import detect_edit_memos
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
