"""TODO 40-3: "여기 효과음 쿵" is saved per cut and the finished video gets the sound, 8 dB under the speech."""

import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path
from uuid import uuid4

from backend.app.services import cut_effects, sound_effects
from backend.app.services import longform_chat as chat
from backend.tests.test_longform_chat import _inputs

FFMPEG = shutil.which("ffmpeg")


class SoundTests(unittest.TestCase):
    def test_every_sound_is_made_short_and_below_full_scale(self):
        for name in sound_effects.NAMES:
            sound = sound_effects.make(name)
            self.assertTrue(0.1 <= sound.seconds <= 1.0, name)
            self.assertAlmostEqual(max(abs(s) for s in sound.samples), sound_effects.PEAK, places=3)
            self.assertLess(sound.level_db, 0)

    def test_gain_puts_the_sound_8_db_under_the_speech(self):
        sound = sound_effects.make("쿵")
        gain = sound_effects.gain_for(sound, -12.0)
        self.assertAlmostEqual(sound.level_db + gain, -20.0, places=1)
        # Silent or quietly recorded video: never below MIN_DB. Loud speech: never pushed past full scale.
        self.assertAlmostEqual(sound.level_db + sound_effects.gain_for(sound, None), sound_effects.MIN_DB, 1)
        self.assertAlmostEqual(sound.level_db + sound_effects.gain_for(sound, -33.9), sound_effects.MIN_DB, 1)
        self.assertLess(sound_effects.gain_for(sound, 5.0), 0)

    def test_speech_level_ignores_the_pauses(self):
        speaking, pause = 10 ** (-25 / 10), 10 ** (-70 / 10)
        self.assertAlmostEqual(sound_effects.body_level([speaking] * 40 + [pause] * 60), -25.0, places=1)
        self.assertIsNone(sound_effects.body_level([]))
        self.assertIsNone(sound_effects.body_level([0.0] * 10))

    def test_mix_filter_reuses_one_file_per_sound(self):
        events = [sound_effects.SoundEvent("쿵", 0.5), sound_effects.SoundEvent("띵", 1.0),
                  sound_effects.SoundEvent("쿵", 2.25)]
        names, graph = sound_effects.mix_filter(events, {"쿵": -10.0, "띵": -12.0})
        self.assertEqual(names, ["쿵", "띵"])
        self.assertIn("asplit=2", graph)
        self.assertIn("adelay=2250:all=1", graph)
        self.assertIn("amix=inputs=4:duration=first", graph)


class SentenceTests(unittest.TestCase):
    def test_sound_sentences(self):
        self.assertEqual(cut_effects.sound_request("여기 효과음 쿵", 2, 1.25),
                         cut_effects.SoundRequest(2, 1.25, "쿵", True))
        self.assertEqual(cut_effects.sound_request("3번에 효과음 띠용 넣어", 2, 1.0),
                         cut_effects.SoundRequest(3, 0.0, "띠용", True))
        self.assertEqual(cut_effects.sound_request("[01:02] 여기 찰칵 소리", 1, 0.5),
                         cut_effects.SoundRequest(1, 0.5, "찰칵", True))
        self.assertEqual(cut_effects.sound_request("효과음 빼", 2, 1.0), cut_effects.SoundRequest(2, 0.0, None, False))
        self.assertEqual(cut_effects.sound_request("2번 효과음 쿵 빼", None, None),
                         cut_effects.SoundRequest(2, 0.0, "쿵", False))
        self.assertEqual(cut_effects.sound_request("여기 효과음 넣어", 1, 0.0),
                         cut_effects.SoundRequest(1, 0.0, None, True))

    def test_other_sentences_are_not_sounds(self):
        for message in ("소리 줄여", "여기 '벌렁' 띄워", "3번 확대", "2번 빼"):
            self.assertIs(cut_effects.sound_request(message, 1, 0.0), False, message)

    def test_sounds_are_placed_by_cut_start(self):
        effects = [{"sounds": [{"name": "쿵", "at": 1.0}]}, None, {"sounds": [{"name": "띵", "at": 9.0}]}]
        events = cut_effects.sound_events(effects, [3.0, 2.0, 4.0])
        self.assertEqual(events, [sound_effects.SoundEvent("쿵", 1.0), sound_effects.SoundEvent("띵", 8.95)])


class ChatTests(unittest.TestCase):
    def test_sound_is_saved_at_the_paused_second_and_undo_removes_it(self):
        inputs = _inputs()
        saved = []
        with tempfile.TemporaryDirectory() as root, \
                unittest.mock.patch.object(chat, "load_inputs", return_value=inputs), \
                unittest.mock.patch.object(chat, "_save_plan", side_effect=lambda s, p, cuts: saved.append(cuts)):
            project, folder = uuid4(), Path(root)
            second = inputs.cuts[1].candidate_id
            begin = chat.starts(inputs.cuts)[1]
            chat.send_message(None, folder, project, "여기 효과음 쿵", begin + 1.5, brain=None)
            chat.send_message(None, folder, project, "여기 '벌렁' 띄워", begin + 1.5, brain=None)
            effects = cut_effects.load_effects(folder, project)
            self.assertEqual(cut_effects.sounds_of(effects, second), [{"name": "쿵", "at": 1.5}])
            self.assertEqual(len(cut_effects.texts_of(effects, second)), 1)  # words and sounds live side by side
            self.assertIn("1.5초에 효과음 쿵", chat.load_chat(folder, project)["messages"][1]["text"])
            unclear = chat.send_message(None, folder, project, "2번 효과음 넣어", None, brain=None)
            self.assertEqual(unclear.done, ())
            chat.send_message(None, folder, project, "2번 효과음 빼", None, brain=None)
            self.assertEqual(cut_effects.sounds_of(cut_effects.load_effects(folder, project), second), [])
            self.assertEqual(saved, [])  # the plan is untouched
            chat.undo(None, folder, project)
            self.assertEqual(len(cut_effects.sounds_of(cut_effects.load_effects(folder, project), second)), 1)


@unittest.skipUnless(FFMPEG, "ffmpeg is not installed")
class MixTests(unittest.TestCase):
    def test_sounds_are_mixed_without_changing_the_length_or_picture(self):
        with tempfile.TemporaryDirectory() as root:
            video = Path(root) / "final.mp4"
            subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x180:r=30:d=2",
                            "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=2",
                            "-c:v", "libx264", "-c:a", "aac", "-shortest", str(video)], check=True)
            before = sound_effects.speech_level(video, FFMPEG)
            gains = sound_effects.mix_sounds(video, [sound_effects.SoundEvent("쿵", 0.3),
                                                     sound_effects.SoundEvent("찰칵", 1.0)], FFMPEG)
            self.assertEqual(set(gains), {"쿵", "찰칵"})
            after = sound_effects.speech_level(video, FFMPEG)
            self.assertGreater(after, before - 0.5)  # the speech is not turned down
            self.assertLess(after, before + 2.0)  # and the sounds do not drown it
            duration = subprocess.run([shutil.which("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                                       "format=duration", "-of", "csv=p=0", str(video)],
                                      check=True, capture_output=True, text=True).stdout.strip()
            self.assertAlmostEqual(float(duration), 2.0, delta=0.1)
            self.assertEqual([path.name for path in Path(root).iterdir()], ["final.mp4"])  # no leftovers


if __name__ == "__main__":
    unittest.main()
