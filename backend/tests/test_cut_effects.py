"""TODO 40: "이 컷 확대" / "천천히 줌" (40-1) and "여기 '벌렁' 띄워" / "여기 (근데 갑자기) 넣어" (40-2) are saved per cut
and the finished video shows them."""

import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from backend.app.services import cut_effects
from backend.app.services import longform_chat as chat
from backend.app.services.clip_renderer import RenderedClip
from backend.app.services.project_rendering import _concat_command, _concat_commands
from backend.tests.test_longform_chat import _inputs

FFMPEG = shutil.which("ffmpeg")


def clip(path: Path, seconds: float) -> RenderedClip:
    return RenderedClip(path, path, Decimal(0), Decimal(str(seconds)), seconds, "h264", "aac")


def video_filters(command: list[str]) -> list[str]:
    graph = command[command.index("-filter_complex") + 1]
    return [part for part in graph.split(";") if ":v:0]" in part]


class SentenceTests(unittest.TestCase):
    def test_zoom_sentences(self):
        self.assertEqual(cut_effects.zoom_request("3번 확대해 줘", None), (3, "zoom"))
        self.assertEqual(cut_effects.zoom_request("[00:12] 이 컷 얼굴 쪽 확대", 2), (2, "zoom"))
        self.assertEqual(cut_effects.zoom_request("여기 천천히 줌", 4), (4, "push"))
        self.assertEqual(cut_effects.zoom_request("2번 확대 빼", 5), (2, None))
        self.assertEqual(cut_effects.zoom_request("확대", None), (None, "zoom"))

    def test_other_sentences_are_not_zoom(self):
        self.assertIs(cut_effects.zoom_request("3번 빼", 1), False)
        self.assertIs(cut_effects.zoom_request("여기 짧게", 1), False)

    def test_word_sentences(self):
        request = cut_effects.text_request("[00:08] 여기 '벌렁' 띄워", 2, 1.46)
        self.assertEqual(request, cut_effects.TextRequest(2, 1.46, "react", "벌렁"))
        self.assertEqual(cut_effects.text_request("여기 “??” 띄워 줘", 2, 0.5).words, "??")
        narration = cut_effects.text_request("여기 (근데 갑자기) 넣어", 2, 3.0)
        self.assertEqual((narration.kind, narration.words, narration.at), ("narr", "근데 갑자기", 3.0))
        # A numbered cut that is not the paused one starts at the cut start.
        self.assertEqual(cut_effects.text_request("3번에 '헉' 붙여", 2, 3.0).at, 0.0)
        self.assertEqual(cut_effects.text_request("여기 글자 빼", 2, 1.0), cut_effects.TextRequest(2, 0.0, None, None))
        self.assertEqual(cut_effects.text_request("2번 내레이션 지워", None, None).kind, "narr")
        # "여기 '확대' 띄워" is a word, not a zoom; plain zoom/cut sentences are not words.
        self.assertEqual(cut_effects.text_request("여기 '확대' 띄워", 1, 0.0).kind, "react")
        self.assertIs(cut_effects.text_request("3번 확대", 1, 0.0), False)
        self.assertIs(cut_effects.text_request("3번 빼", 1, 0.0), False)
        self.assertEqual(cut_effects.clean_words("{\\an1}벌렁"), "an1벌렁")


class ChatTests(unittest.TestCase):
    def test_zoom_is_saved_without_changing_plan_and_undo_removes_it(self):
        inputs = _inputs()
        saved = []
        with tempfile.TemporaryDirectory() as root, \
                unittest.mock.patch.object(chat, "load_inputs", return_value=inputs), \
                unittest.mock.patch.object(chat, "_save_plan", side_effect=lambda s, p, cuts: saved.append(list(cuts))):
            project, folder = uuid4(), Path(root)
            result = chat.send_message(None, folder, project, "2번 확대", None, brain=None)
            second = inputs.cuts[1].candidate_id
            self.assertEqual(result.changed, frozenset({second}))
            self.assertEqual(saved, [])  # the plan is untouched
            self.assertEqual(cut_effects.zoom_of(cut_effects.load_effects(folder, project), second), "zoom")
            chat.send_message(None, folder, project, "[00:07] 여기 천천히 줌", 7.0, brain=None)  # 7s = cut 2
            self.assertEqual(cut_effects.zoom_of(cut_effects.load_effects(folder, project), second), "push")
            again = chat.send_message(None, folder, project, "2번 천천히 줌", None, brain=None)
            self.assertEqual(again.done, ())
            self.assertIn("바뀐 것 없음", chat.load_chat(folder, project)["messages"][-1]["text"])
            chat.undo(None, folder, project)
            self.assertEqual(cut_effects.zoom_of(cut_effects.load_effects(folder, project), second), "zoom")
            chat.send_message(None, folder, project, "2번 확대 빼", None, brain=None)
            self.assertEqual(cut_effects.load_effects(folder, project), {})

    def test_words_are_saved_at_the_paused_second_and_undo_removes_them(self):
        inputs = _inputs()
        saved = []
        with tempfile.TemporaryDirectory() as root, \
                unittest.mock.patch.object(chat, "load_inputs", return_value=inputs), \
                unittest.mock.patch.object(chat, "_save_plan", side_effect=lambda s, p, cuts: saved.append(cuts)):
            project, folder = uuid4(), Path(root)
            second = inputs.cuts[1].candidate_id
            begin = chat.starts(inputs.cuts)[1]
            chat.send_message(None, folder, project, "여기 '벌렁' 띄워", begin + 1.5, brain=None)
            chat.send_message(None, folder, project, "여기 (근데 갑자기) 넣어", begin + 2.0, brain=None)
            chat.send_message(None, folder, project, "2번 확대", None, brain=None)
            effects = cut_effects.load_effects(folder, project)
            self.assertEqual(cut_effects.texts_of(effects, second),
                             [{"kind": "react", "text": "벌렁", "at": 1.5},
                              {"kind": "narr", "text": "근데 갑자기", "at": 2.0}])
            self.assertEqual(cut_effects.zoom_of(effects, second), "zoom")  # words and zoom live side by side
            self.assertIn("1.5초에 리액션 글자 벌렁", chat.load_chat(folder, project)["messages"][1]["text"])
            again = chat.send_message(None, folder, project, "2번 '벌렁' 띄워", None, brain=None)
            self.assertEqual(again.done, ())
            chat.send_message(None, folder, project, "2번 내레이션 빼", None, brain=None)
            self.assertEqual([item["kind"] for item in cut_effects.texts_of(cut_effects.load_effects(folder, project),
                                                                            second)], ["react"])
            self.assertEqual(saved, [])  # the plan is untouched
            chat.undo(None, folder, project)
            self.assertEqual(len(cut_effects.texts_of(cut_effects.load_effects(folder, project), second)), 2)
            chat.send_message(None, folder, project, "2번 글자 빼", None, brain=None)
            self.assertEqual(cut_effects.texts_of(cut_effects.load_effects(folder, project), second), [])

    def test_unknown_cut_changes_nothing(self):
        with tempfile.TemporaryDirectory() as root, \
                unittest.mock.patch.object(chat, "load_inputs", return_value=_inputs()):
            result = chat.send_message(None, Path(root), uuid4(), "9번 확대", None, brain=None)
            self.assertEqual(result.done, ())


class RenderCommandTests(unittest.TestCase):
    def test_each_cut_gets_its_own_zoom(self):
        clips = [clip(Path(f"{index}.mp4"), 2.0) for index in range(3)]
        command = _concat_command(clips, [True] * 3, Path("final.mp4"), "ffmpeg", audio_durations=[2.0] * 3,
                                  effects=[{"zoom": "zoom"}, {"zoom": "push"}, None])
        first, second, third = video_filters(command)
        self.assertIn("crop=948:534:166:", first)
        self.assertIn("zoompan=z='1+0.15*on/60'", second)
        self.assertNotIn("crop=", third)
        self.assertNotIn("zoompan", third)

    def test_long_plan_groups_keep_effects_in_order(self):
        clips = [clip(Path("x" * 700 + f"{index}.mp4"), 1.0) for index in range(45)]
        effects = [None] * 45
        effects[42] = {"zoom": "zoom"}
        with tempfile.TemporaryDirectory() as root:
            commands = _concat_commands(clips, [True] * 45, Path(root) / "final.mp4", "ffmpeg", Path(root),
                                        effects=effects)
        self.assertGreater(len(commands), 2)
        self.assertFalse(any("crop=" in part for part in video_filters(commands[0])))
        self.assertIn("crop=", video_filters(commands[1])[2])


class TextTimingTests(unittest.TestCase):
    def test_words_are_placed_by_cut_start_and_kept_inside_the_cut(self):
        effects = [{"texts": [{"kind": "react", "text": "벌렁", "at": 1.0}]}, None,
                   {"texts": [{"kind": "narr", "text": "근데 갑자기", "at": 3.9},
                              {"kind": "react", "text": "??", "at": 3.9}]}]
        events = cut_effects.text_events(effects, [4.0, 2.5, 4.0])
        self.assertEqual([(e.kind, e.start, e.end, e.text) for e in events], [
            ("react", 1.0, 2.2, "벌렁"),
            ("narr", 9.5, 10.5, "(근데 갑자기)"),  # paused near the end: still shown for 1 s
            ("react", 10.1, 10.5, "??"),  # cut ends before 1.2 s
        ])

    def test_narration_sits_above_the_spoken_captions(self):
        from backend.app.services import longform_captions
        height = 720
        narration_bottom = height - cut_effects.narr_margin(height)
        # Long-form captions: two lines of bold white letters from the bottom margin up.
        line_size, margin = round(58 * height / 1080), round(56 * height / 1080)
        self.assertLess(narration_bottom, height - margin - 2 * line_size * 1.25)
        # SRT burn-in (libass defaults scaled from 288 lines): font 16, bottom margin 20, two lines.
        self.assertLess(narration_bottom, height - (20 + 2 * 16 * 1.25) * height / 288)
        ass = cut_effects.build_text_ass([cut_effects.TextEvent("react", 1, 2.2, "벌렁"),
                                          cut_effects.TextEvent("narr", 1, 4, "(근데)")], 1280, height)
        self.assertIn("Style: Narr,Pretendard ExtraBold", ass)
        self.assertIn("\\pos(973,187)", ass)
        self.assertIn(",React,,0,0,0,,{\\an5", ass)
        self.assertTrue(longform_captions.build_ass)  # the captions it is measured against


@unittest.skipUnless(FFMPEG, "ffmpeg is not installed")
class RenderTests(unittest.TestCase):
    def test_zoomed_cuts_keep_their_length(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            clips = []
            for index in range(2):
                path = folder / f"clip-{index}.mp4"
                subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:r=30:d=1",
                                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)], check=True)
                clips.append(clip(path, 1.0))
            final = folder / "final.mp4"
            subprocess.run(_concat_command(clips, [True] * 2, final, FFMPEG, audio_durations=[1.0] * 2,
                                           effects=[{"zoom": "zoom"}, {"zoom": "push"}]),
                           check=True, capture_output=True)
            video = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=duration,width,height", "-of", "csv=p=0", str(final)],
                                   check=True, capture_output=True, text=True).stdout.strip().split(",")
            self.assertEqual(video[:2], ["1280", "720"])
            self.assertAlmostEqual(float(video[2]), 2.0, delta=1 / 30 + 0.001)

    def test_words_are_burned_without_changing_the_length(self):
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "final.mp4"
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=1280x720:r=30:d=2",
                            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
                            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)], check=True)
            before = video.read_bytes()
            cut_effects.burn_texts(video, [cut_effects.TextEvent("react", 0.2, 1.4, "벌렁"),
                                           cut_effects.TextEvent("narr", 0.2, 2.0, "(근데 갑자기)")],
                                   1280, 720, FFMPEG)
            self.assertNotEqual(video.read_bytes(), before)
            duration = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                                       "format=duration", "-of", "csv=p=0", str(video)],
                                      check=True, capture_output=True, text=True).stdout.strip()
            self.assertAlmostEqual(float(duration), 2.0, delta=0.1)
            self.assertEqual([path.name for path in Path(root).iterdir()], ["final.mp4"])  # no leftovers


if __name__ == "__main__":
    unittest.main()
