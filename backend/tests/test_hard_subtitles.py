"""Synthetic-only Docker subtitle validation; no evaluation media is used."""

from pathlib import Path
import os
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from backend.app.services.hard_subtitles import HardSubtitleError, burn_hard_subtitles
from backend.app.services.media_probe import probe_media
from backend.app.services.project_rendering import render_project_edit_plan
import backend.tests.test_project_rendering as render_fixtures


class HardSubtitleTests(TestCase):
    def test_missing_font_preserves_inputs(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mp4, srt = root / "final.mp4", root / "final.srt"
            mp4.write_bytes(b"original")
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n안녕\n", encoding="utf-8")
            with self.assertRaises(HardSubtitleError) as error:
                burn_hard_subtitles(mp4, srt, root / "absent.otf")
            self.assertEqual(error.exception.code, "SUBTITLE_FONT_INVALID")
            self.assertEqual(mp4.read_bytes(), b"original")
            self.assertFalse((root / "final-subtitled.mp4").exists())

    def test_empty_srt_preserves_mp4(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mp4, srt = root / "final.mp4", root / "final.srt"
            mp4.write_bytes(b"original")
            srt.write_text("", encoding="utf-8")
            with self.assertRaises(HardSubtitleError) as error:
                burn_hard_subtitles(mp4, srt, root / "absent.otf")
            self.assertEqual(error.exception.code, "SUBTITLE_INPUT_MISSING")
            self.assertEqual(mp4.read_bytes(), b"original")

    def test_invalid_srt_encoding_preserves_mp4(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            mp4, srt = root / "final.mp4", root / "final.srt"
            mp4.write_bytes(b"original")
            srt.write_bytes(b"\xff\xfe")
            with self.assertRaises(HardSubtitleError) as error:
                burn_hard_subtitles(mp4, srt, root / "absent.otf")
            self.assertEqual(error.exception.code, "SUBTITLE_INPUT_INVALID")
            self.assertEqual(mp4.read_bytes(), b"original")

    def test_synthetic_korean_render(self):
        font = Path("evaluation/tmp/subtitle-font/NotoSansCJKkr-Regular.otf")
        if not font.is_file() or shutil.which("docker") is None or shutil.which("ffmpeg") is None:
            self.skipTest("Docker, FFmpeg and verified local font required")
        with TemporaryDirectory() as directory:
            root = Path(directory) / "한글 & spaces"
            root.mkdir()
            mp4, srt = root / "final.mp4", root / "final.srt"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                            "-i", "color=c=black:s=320x180:r=30:d=4", "-f", "lavfi",
                            "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
                            "-shortest", str(mp4)], check=True, capture_output=True)
            original = mp4.read_bytes()
            srt.write_text("1\n00:00:01,000 --> 00:00:02,000\n안녕 & Cutory\n두 번째 줄\n\n"
                           "2\n00:00:02,000 --> 00:00:03,000\n장면 경계\n", encoding="utf-8")
            output = burn_hard_subtitles(mp4, srt, font)
            self.assertEqual(mp4.read_bytes(), original)
            self.assertEqual(probe_media(output).video_codec, "h264")
            self.assertEqual(probe_media(output).audio_codec, "aac")
            self.assertAlmostEqual(probe_media(output).duration_seconds, 4, delta=0.1)
            def frame_bytes(at):
                return subprocess.run(["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(output),
                                       "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                                      capture_output=True, check=True).stdout
            bright = lambda at: sum(value > 32 for value in frame_bytes(at))
            self.assertLess(bright(0.5), 10)
            self.assertLess(bright(3.5), 10)
            self.assertGreater(bright(1.5), 100)
            self.assertGreater(bright(2.5), 100)
            output.unlink()
            with self.assertRaises(HardSubtitleError) as error:
                burn_hard_subtitles(mp4, srt, font, docker="missing-docker-executable")
            self.assertEqual(error.exception.code, "SUBTITLE_RENDER_FAILED")
            self.assertEqual(mp4.read_bytes(), original)
            self.assertTrue(srt.is_file())
            self.assertFalse(output.exists())


class ProjectHardSubtitleTests(TestCase):
    def setUp(self):
        self.fixture = render_fixtures.ProjectRenderingTests("test_subtitle_timeline_uses_measured_clip_duration")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def test_failure_keeps_project_mp4_and_srt(self):
        fixture = self.fixture
        selected = fixture.candidate(start=0, end=1)
        fixture.add_transcript(selected, 0.1, 0.9, "자막")
        fixture.plan([selected])
        with patch.dict(os.environ, {"CUTORY_SUBTITLE_FONT_PATH": "missing.otf"}):
            result = fixture.render(inspect_timeline=lambda _: 1.0)
        self.assertTrue(result.output_path.is_file())
        self.assertTrue(result.subtitle_path.is_file())
        self.assertIsNone(result.hard_subtitle_path)
        self.assertEqual(result.hard_subtitle_error_code, "SUBTITLE_FONT_INVALID")

    def test_synthetic_project_output_creates_burned_copy(self):
        font = Path("evaluation/tmp/subtitle-font/NotoSansCJKkr-Regular.otf")
        if not font.is_file() or shutil.which("docker") is None or shutil.which("ffmpeg") is None:
            self.skipTest("Docker, FFmpeg and verified local font required")
        fixture = self.fixture
        source = fixture.root / "source.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                        "color=c=black:s=320x180:r=30:d=2", "-f", "lavfi", "-i",
                        "sine=frequency=440:duration=2", "-c:v", "libx264", "-c:a", "aac",
                        "-shortest", str(source)], check=True, capture_output=True)
        selected = fixture.candidate(start=0, end=2, source_duration=2, source_file=source)
        fixture.add_transcript(selected, 0.5, 1.5, "한국어 자막")
        fixture.plan([selected])
        with patch.dict(os.environ, {"CUTORY_SUBTITLE_FONT_PATH": str(font)}):
            result = render_project_edit_plan(session_factory=fixture.factory,
                                              source_storage=fixture.storage,
                                              project_id=fixture.project_id,
                                              output_root=fixture.root / "output")
        self.assertTrue(result.output_path.is_file())
        self.assertTrue(result.subtitle_path.is_file())
        self.assertIsNone(result.hard_subtitle_error_code)
        self.assertTrue(result.hard_subtitle_path.is_file())
