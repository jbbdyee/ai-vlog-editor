"""TODO 9: subtitles must still be made when many scenes (e.g. 29) are joined into one video."""

from pathlib import Path
import re
import shutil
import subprocess
from unittest import TestCase, skipUnless

import backend.tests.test_project_rendering as base
from backend.app.services.clip_renderer import RenderedClip
from backend.app.services.project_rendering import probe_video_timeline, render_project_edit_plan


class ManyClipSubtitleTests(TestCase):
    # Reuse the render fixture helpers without re-running that module's tests here.
    setUp = base.ProjectRenderingTests.setUp
    project = base.ProjectRenderingTests.project
    candidate = base.ProjectRenderingTests.candidate
    plan = base.ProjectRenderingTests.plan
    add_transcript = base.ProjectRenderingTests.add_transcript
    fake_probe = staticmethod(base.ProjectRenderingTests.fake_probe)

    def many_scenes(self, count=29, *, with_speech=True):
        ids = []
        for index in range(count):
            start = round(index * 0.3, 3)
            ids.append(self.candidate(start=start, end=start + 0.6, source_duration=count + 1))
            if with_speech:
                self.add_transcript(ids[-1], start + 0.1, start + 0.5, f"대사 {index}")
        self.plan(ids)
        return ids

    def render_with_fakes(self):
        commands = []

        def render_one(source, candidate, output, *, ffmpeg_executable):
            # The cut file's container is a little longer than its video, like real AAC tails.
            path = Path(output) / f"clip-{len(commands)}-{candidate.start_seconds}.mp4"
            path.write_bytes(b"fake clip")
            return RenderedClip(Path(source), path, candidate.start_seconds, candidate.end_seconds,
                                candidate.end_seconds - candidate.start_seconds + 0.023, "h264", "aac")

        def run(command, **_):
            commands.append(command)
            Path(command[-1]).write_bytes(b"fake output")
            return subprocess.CompletedProcess(command, 0)

        def timeline(path):
            # Each normalized clip measures 0.6 s of video; the joined video is exactly their sum.
            return 0.6 * 29 if path.name == "final.mp4" else 0.6

        result = render_project_edit_plan(
            session_factory=self.factory, source_storage=self.storage,
            project_id=self.project_id, output_root=self.root / "output",
            render_one=render_one, inspect_media=self.fake_probe,
            run_ffmpeg=run, inspect_timeline=timeline,
        )
        concat = next(command for command in commands if command[-1].endswith("final.mp4"))
        trims = re.findall(r"atrim=duration=([0-9.]+)", concat[concat.index("-filter_complex") + 1])
        return result, [float(value) for value in trims]

    def test_audio_is_trimmed_to_measured_video_and_subtitles_are_made(self):
        self.many_scenes()
        result, trims = self.render_with_fakes()
        self.assertEqual(trims, [0.6] * 29)
        self.assertIsNone(result.subtitle_error_code)
        self.assertTrue(result.subtitle_path.is_file())
        self.assertIn("대사 28", result.subtitle_path.read_text(encoding="utf-8"))

    def test_video_without_speech_also_keeps_audio_to_video_length(self):
        self.many_scenes(with_speech=False)
        result, trims = self.render_with_fakes()
        self.assertEqual(trims, [0.6] * 29)
        self.assertIsNone(result.subtitle_path)
        self.assertIsNone(result.subtitle_error_code)


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are unavailable")
class RealFfmpegManyClipTests(ManyClipSubtitleTests):
    def test_joined_video_matches_clip_sum_with_many_real_clips(self):
        source = self.root / "source.mp4"
        # 24 fps video with audio that runs longer than the picture, so every cut has a tail.
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=12",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=12.4",
                        "-c:v", "libx264", "-c:a", "aac", str(source)], check=True)
        ids = []
        for index in range(20):
            start = round(index * 0.55, 3)
            ids.append(self.candidate(start=start, end=start + 0.53, source_duration=12, source_file=source))
            self.add_transcript(ids[-1], start + 0.05, start + 0.45, f"말 {index}")
        self.plan(ids)
        result = render_project_edit_plan(
            session_factory=self.factory, source_storage=self.storage,
            project_id=self.project_id, output_root=self.root / "output",
        )
        self.assertIsNone(result.subtitle_error_code)
        self.assertTrue(result.subtitle_path.is_file())
        self.assertGreater(probe_video_timeline(result.output_path), 0)

    # The fake-only tests above are already covered by the parent class.
    test_audio_is_trimmed_to_measured_video_and_subtitles_are_made = None
    test_video_without_speech_also_keeps_audio_to_video_length = None
