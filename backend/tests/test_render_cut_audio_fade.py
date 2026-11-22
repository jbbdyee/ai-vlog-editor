"""TODO 38: sound fades out/in at every cut boundary, and the video length does not change."""

import array
import re
import shutil
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path
from unittest import TestCase, skipUnless

from backend.app.services.clip_renderer import RenderedClip
from backend.app.services.project_rendering import CUT_AUDIO_FADE_SECONDS, _concat_command

FFMPEG = shutil.which("ffmpeg")


def clip(path: Path, seconds: float) -> RenderedClip:
    return RenderedClip(path, path, Decimal(0), Decimal(str(seconds)), seconds, "h264", "aac")


def audio_filters(command: list[str]) -> list[str]:
    graph = command[command.index("-filter_complex") + 1]
    return [part for part in graph.split(";") if "aresample" in part]


class CutAudioFadeCommandTests(TestCase):
    def test_every_cut_fades_in_and_out_after_the_trim(self):
        clips = [clip(Path(f"{index}.mp4"), 3.0) for index in range(3)]
        command = _concat_command(clips, [True, False, True], Path("final.mp4"), "ffmpeg",
                                  audio_durations=[2.0, 3.0, 4.5])
        filters = audio_filters(command)
        self.assertEqual(len(filters), 3)
        for part, length in zip(filters, [2.0, 3.0, 4.5]):
            self.assertIn(f"atrim=duration={length:.6f},afade=t=in:d={CUT_AUDIO_FADE_SECONDS:.3f}", part)
            self.assertIn(f"afade=t=out:st={length - CUT_AUDIO_FADE_SECONDS:.6f}", part)

    def test_short_cut_fade_is_at_most_a_quarter(self):
        command = _concat_command([clip(Path("a.mp4"), 0.2)], [True], Path("final.mp4"), "ffmpeg",
                                  audio_durations=[0.2])
        fade = float(re.search(r"afade=t=in:d=([0-9.]+)", audio_filters(command)[0]).group(1))
        self.assertAlmostEqual(fade, 0.05)


@skipUnless(FFMPEG, "ffmpeg is not installed")
class CutAudioFadeRenderTests(TestCase):
    def test_boundary_is_quiet_and_length_is_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            clips = []
            for index in range(3):
                path = folder / f"tone-{index}.mp4"
                subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=gray:s=320x240:r=30:d=1",
                                "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=1",
                                "-c:v", "libx264", "-c:a", "aac", "-shortest", str(path)], check=True)
                clips.append(clip(path, 1.0))
            final = folder / "final.mp4"
            subprocess.run(_concat_command(clips, [True] * 3, final, FFMPEG, audio_durations=[1.0] * 3),
                           check=True, capture_output=True)
            raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(final), "-map", "0:a:0", "-ac", "1",
                                  "-f", "f32le", "-"], check=True, capture_output=True).stdout
            samples = array.array("f", raw)

            def loudest(start: float, end: float) -> float:
                return max(abs(value) for value in samples[int(start * 48000):int(end * 48000)])

            full = loudest(0.4, 0.6)                           # middle of a cut (lavfi sine is about 0.125)
            self.assertGreater(full, 0.1)
            self.assertLess(loudest(0.995, 1.005), full / 4)   # cut boundary 1 is much quieter
            self.assertLess(loudest(1.995, 2.005), full / 4)   # cut boundary 2 is much quieter
            video = subprocess.run([shutil.which("ffprobe") or "ffprobe","-v", "error", "-select_streams", "v:0",
                                    "-show_entries", "stream=duration", "-of", "csv=p=0", str(final)],
                                   check=True, capture_output=True, text=True).stdout
            self.assertAlmostEqual(float(video), 3.0, delta=1 / 30 + 0.001)
