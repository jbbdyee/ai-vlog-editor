"""TODO 40-1: "이 컷 확대" / "천천히 줌" are saved per cut and the finished video zooms that cut."""

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


if __name__ == "__main__":
    unittest.main()
