import json
from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from backend.app.services import longform_captions as lc
from backend.app.services.llm_edit_interpreter import LLMEditError


SRT = """1
00:00:08,134 --> 00:00:09,578
옆에서 옆에서 들어와서

2
00:00:51,638 --> 00:00:53,713
아 근데 너무 열심히 하는 거ikan

3
00:01:30,000 --> 00:01:32,000
🎵

4
00:02:10,000 --> 00:02:12,500
오늘 진짜 힘들었다
"""


class ParseTest(unittest.TestCase):
    def test_reads_lines_and_drops_glued_latin_and_empty(self):
        cues = lc.parse_srt(SRT)
        self.assertEqual([c.text for c in cues], ["옆에서 옆에서 들어와서", "아 근데 너무 열심히 하는 거", "오늘 진짜 힘들었다"])
        self.assertAlmostEqual(cues[0].start, 8.134)
        self.assertAlmostEqual(cues[2].end, 132.5)

    def test_drops_lines_misheard_over_music(self):
        # Real lines from the dance lesson render (TODO 9 SRT, 40 lines).
        rows = ["음...", "음...", "sex", "совсем 조", "1 2 2 4 6 7 8 9 na na na", "구독과 힘이",
                "넌 길어져", "넌 길어져", "가만히 tener", "몸에서 너무 빨라요"]
        srt = "\n\n".join(f"{i + 1}\n00:00:{i:02d},000 --> 00:00:{i:02d},900\n{row}" for i, row in enumerate(rows))
        self.assertEqual([c.text for c in lc.parse_srt(srt)], ["넌 길어져", "가만히 tener", "몸에서 너무 빨라요"])

    def test_keeps_real_english_words(self):
        self.assertEqual(lc.clean_line("오늘 OOTD 공개"), "오늘 OOTD 공개")


class ThoughtTest(unittest.TestCase):
    def setUp(self):
        self.cues = lc.parse_srt(SRT)

    def answer(self, thoughts):
        def complete(system, user, schema):
            self.prompt, self.schema = user, schema
            return json.dumps({"thoughts": thoughts}, ensure_ascii=False)
        return complete

    def test_budget_follows_length(self):
        self.assertEqual(lc.thought_budget(30), 1)
        self.assertEqual(lc.thought_budget(180), 4)
        self.assertEqual(lc.thought_budget(99999), lc.MAX_THOUGHTS)

    def test_keeps_good_thoughts_and_drops_copies_long_ones_and_crowding(self):
        thoughts = lc.write_thoughts(self.cues, 180, self.answer([
            {"line": 0, "thought": "벌써 다리 후들"},
            {"line": 1, "thought": "너무 열심히 하는"},  # copy of the spoken line
            {"line": 2, "thought": "집에 가고 싶다 진짜 너무너무 많이"},  # too long
            {"line": 2, "thought": "(집에 가고 싶다)"},
        ]))
        self.assertEqual([t.text for t in thoughts], ["벌써 다리 후들", "집에 가고 싶다"])
        self.assertAlmostEqual(thoughts[0].end, 8.134 + lc.THOUGHT_MIN_SECONDS)
        self.assertEqual(self.schema["properties"]["thoughts"]["maxItems"], 4)
        self.assertIn("[1] 00:51 아 근데 너무 열심히 하는 거", self.prompt)

    def test_thoughts_too_close_together_keep_the_first(self):
        cues = [lc.Cue(10, 11, "하나"), lc.Cue(15, 16, "둘")]
        thoughts = lc.write_thoughts(cues, 600, self.answer([{"line": 0, "thought": "좋다"},
                                                             {"line": 1, "thought": "배고파"}]))
        self.assertEqual([t.text for t in thoughts], ["좋다"])

    def test_no_ai_or_broken_ai_means_no_thoughts(self):
        self.assertEqual(lc.write_thoughts(self.cues, 180, None), [])

        def broken(*_):
            raise LLMEditError("LLM_UNAVAILABLE")
        self.assertEqual(lc.write_thoughts(self.cues, 180, broken), [])
        self.assertEqual(lc.write_thoughts(self.cues, 180, lambda *_: "not json"), [])


class AssTest(unittest.TestCase):
    def test_lines_bottom_centre_and_thoughts_on_the_right(self):
        text = lc.build_ass([lc.Cue(1, 2.5, "안녕")], [lc.Thought(1, 3.5, "설렌다")], 1920, 1080)
        self.assertIn("PlayResX: 1920", text)
        self.assertIn("Dialogue: 0,0:00:01.00,0:00:02.50,Line,,0,0,0,,안녕", text)
        self.assertIn("Thought,,0,0,0,,{\\pos(1786,931)\\frz4\\fad(150,150)}설렌다", text)
        line_style = next(row for row in text.splitlines() if row.startswith("Style: Line"))
        self.assertEqual(line_style.split(",")[18], "2")  # bottom centre


@unittest.skipIf(shutil.which("ffmpeg") is None, "FFmpeg required")
class BurnTest(unittest.TestCase):
    def test_burns_a_checked_copy_and_records_it(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            video, srt = root / "final.mp4", root / "final.srt"
            subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=640x360:r=30:d=3",
                            "-f", "lavfi", "-i", "sine=frequency=440:duration=3", "-c:v", "libx264", "-c:a", "aac",
                            "-shortest", str(video)], check=True, capture_output=True)
            srt.write_text("1\n00:00:00,500 --> 00:00:02,000\n한국어 자막\n", encoding="utf-8")
            engine = ("ollama", "test", lambda *_: json.dumps({"thoughts": [{"line": 0, "thought": "떨린다"}]}))
            done = lc.burn_captions(video, srt, root / "out", "abc", engine=engine)
            self.assertTrue(done.path.is_file())
            self.assertAlmostEqual(done.duration_seconds, 3.0, delta=0.1)
            self.assertEqual(done.thoughts, ("떨린다",))
            saved = lc.saved_video(root / "out")
            self.assertEqual((saved.render_id, saved.line_count, saved.thought_engine), ("abc", 1, "ollama/test"))

    def test_no_lines_is_refused(self):
        with TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "final.mp4").write_bytes(b"x")
            (root / "final.srt").write_text("", encoding="utf-8")
            with self.assertRaises(lc.CaptionError) as caught:
                lc.burn_captions(root / "final.mp4", root / "final.srt", root / "out", "abc")
            self.assertEqual(caught.exception.code, "CAPTION_NO_LINES")


class JobTest(unittest.TestCase):
    def test_job_reports_failure_code(self):
        project = uuid4()

        def burn(*_, **__):
            raise lc.CaptionError("CAPTION_BURN_FAILED")
        self.assertIsNone(lc.start_captioning(project, Path("v"), Path("s"), "r", Path("."), burn=burn,
                                              engine=None, background=False))
        state = lc.job_state(project)
        self.assertEqual((state.status, state.error_code), ("FAILED", "CAPTION_BURN_FAILED"))


if __name__ == "__main__":
    unittest.main()
