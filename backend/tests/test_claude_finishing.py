import unittest
from types import SimpleNamespace
from uuid import uuid4

from backend.app.services import claude_finishing as finishing
from backend.app.services import cut_effects


def _line(start, end, text, speaker):
    return SimpleNamespace(start=start, end=end, text=text, speaker=speaker)


def _inputs(cut_specs):
    """cut_specs: (start, end, caption, lines) per cut, all from one source video."""
    source = uuid4()
    scenes, cuts, lines = {}, [], []
    for start, end, caption, cut_lines in cut_specs:
        candidate = uuid4()
        scenes[candidate] = SimpleNamespace(source_video_id=source, caption=caption)
        cuts.append(SimpleNamespace(candidate_id=candidate, start=start, end=end))
        lines.extend(cut_lines)
    return SimpleNamespace(scenes=scenes, cuts=tuple(cuts), lines={source: tuple(lines)})


REFERENCE = {"stats": {"cut_count": 20, "median_cut": 1.77, "cuts_per_minute": 31.5},
             "captions": {"stats": {"median_gap": 1.0, "median_chars": 5.5,
                                    "zone_share": {"위": 0.147, "가운데": 0.735, "아래": 0.118}}}}


class ClaudeFinishingTest(unittest.TestCase):
    def test_three_pictures_inside_the_cut(self):
        row = finishing.CutRow(1, uuid4(), uuid4(), 10.0, 14.0, "", "", "")
        self.assertEqual(finishing.picture_times(row), (10.6, 12.0, 13.4))

    def test_cut_rows_keep_speech_marks_and_my_effects(self):
        inputs = _inputs([(0.0, 4.0, "카페", [_line(1.0, 2.0, "대박", "me"), _line(5.0, 6.0, "다음 컷", "other")]),
                          (5.0, 8.0, "", [])])
        first = inputs.cuts[0].candidate_id
        effects = cut_effects.set_zoom({}, first, "zoom")
        rows = finishing.cut_rows(inputs, effects)
        self.assertEqual([row.number for row in rows], [1, 2])
        self.assertEqual(rows[0].speech, "[나] 대박")
        self.assertEqual(rows[0].existing, "확대")
        self.assertIn("이미 넣은 효과(그대로 둘 것): 확대", rows[0].line())
        self.assertEqual(rows[1].speech, "[남] 다음 컷")
        self.assertEqual(rows[1].existing, "")
        self.assertIn("화면 설명: (없음)", rows[1].line())

    def test_reference_numbers_from_todo33(self):
        lines = finishing.reference_lines(REFERENCE)
        self.assertEqual(lines[0], "한 컷 가운데 값 1.77초 (컷 20개, 1분에 31.5컷)")
        self.assertIn("자막(화면 글자)은 1.0초쯤마다 바뀜", lines)
        self.assertIn("자막 한 번에 5.5자 안팎", lines)
        self.assertIn("자막 위치는 화면 가운데 74%", lines)
        self.assertEqual(finishing.reference_lines(None), [])

    def test_header_carries_rules_brief_numbers_and_every_sound(self):
        header = finishing.header_text(["한 컷은 5.5초 안팎"], "학원 가는 장면은 꼭", ["자막 한 번에 5.5자 안팎"])
        for words in ("- 한 컷은 5.5초 안팎", "학원 가는 장면은 꼭", "- 자막 한 번에 5.5자 안팎", "쿵·뿅·휙·띵·띠용·찰칵"):
            self.assertIn(words, header)
        self.assertIn("(없음)", finishing.header_text([], "", []))

    def test_estimate_counts_pictures_chunks_and_price(self):
        rows = [finishing.CutRow(number, uuid4(), uuid4(), 0.0, 5.0, "가" * 50, "나" * 20, "")
                for number in range(1, 77)]
        guess = finishing.estimate("claude-sonnet-5-5", "머리글" * 100, rows)
        self.assertEqual(guess.pictures, 228)
        self.assertEqual(guess.chunks, 3)  # 33 + 33 + 10 cuts, at most 99 pictures per request
        text = 3 * len(finishing.SYSTEM) + 3 * 300 + sum(len(row.line()) for row in rows)
        self.assertEqual(guess.input_tokens, text + 228 * finishing.IMAGE_TOKENS)
        self.assertEqual(guess.output_tokens, 76 * 80 + 3 * 300)
        self.assertEqual(guess.output_tokens_high, guess.output_tokens + 76 * 150)
        self.assertAlmostEqual(guess.usd_low, (guess.input_tokens * 2 + guess.output_tokens * 10) / 1e6, places=4)
        self.assertGreater(guess.usd_high, guess.usd_low)


if __name__ == "__main__":
    unittest.main()
