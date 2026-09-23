from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from app.services.candidate_generator import SceneCandidate
from app.services.clip_renderer import ClipRenderError, render_clip
from app.services.media_probe import MediaInfo


class ClipRendererTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_path = self.root / "source.MOV"
        self.source_path.touch()
        self.output_directory = self.root / "missing" / "clips"
        self.candidate = SceneCandidate(5.0, 10.8, 15.8)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_candidate_renders_mp4_and_creates_output_directory(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.side_effect = [self._source_info(), self._clip_info()]

        def create_clip(command, **kwargs):
            Path(command[-1]).write_bytes(b"rendered-mp4")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_clip

        rendered = render_clip(
            self.source_path,
            self.candidate,
            self.output_directory,
        )

        self.assertTrue(self.output_directory.is_dir())
        self.assertTrue(rendered.clip_path.is_file())
        self.assertEqual(rendered.clip_path.suffix, ".mp4")
        self.assertEqual(UUID(rendered.clip_path.stem).hex, rendered.clip_path.stem)
        self.assertEqual(rendered.source_path, self.source_path)
        self.assertEqual(rendered.start_seconds, 10.8)
        self.assertEqual(rendered.end_seconds, 15.8)
        self.assertEqual(rendered.duration_seconds, 5.04)
        self.assertEqual(rendered.video_codec, "h264")
        self.assertEqual(rendered.audio_codec, "aac")

        command = run_mock.call_args.args[0]
        self.assertEqual(command[command.index("-ss") + 1], "10.8")
        self.assertEqual(command[command.index("-t") + 1], "5.0")
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(command[command.index("-c:a") + 1], "aac")
        self.assertIn("+faststart", command)
        self.assertNotIn("shell", run_mock.call_args.kwargs)

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_existing_output_file_is_preserved(self, probe_mock, run_mock) -> None:
        probe_mock.side_effect = [self._source_info(), self._clip_info()]
        self.output_directory.mkdir(parents=True)
        existing = self.output_directory / "existing.mp4"
        existing.write_bytes(b"keep-me")

        def create_clip(command, **kwargs):
            Path(command[-1]).write_bytes(b"new-clip")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_clip

        rendered = render_clip(
            self.source_path,
            self.candidate,
            self.output_directory,
        )

        self.assertEqual(existing.read_bytes(), b"keep-me")
        self.assertNotEqual(rendered.clip_path, existing)

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_missing_source_is_rejected_before_probe_and_ffmpeg(
        self, probe_mock, run_mock
    ) -> None:
        missing = self.root / "missing.mov"

        with self.assertRaisesRegex(ClipRenderError, "does not exist"):
            render_clip(missing, self.candidate, self.output_directory)

        probe_mock.assert_not_called()
        run_mock.assert_not_called()

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_invalid_candidate_is_rejected_before_ffmpeg(
        self, probe_mock, run_mock
    ) -> None:
        invalid_candidates = (
            SceneCandidate(5.0, -1.0, 5.0),
            SceneCandidate(5.0, 5.0, 5.0),
            SceneCandidate(5.0, 6.0, 5.0),
            SceneCandidate(0.0, 1.0, 2.0),
            SceneCandidate(5.0, float("nan"), 5.0),
            SceneCandidate(5.0, 1.0, float("inf")),
            SceneCandidate(5.0, "1", 5.0),  # type: ignore[arg-type]
        )

        for candidate in invalid_candidates:
            with self.subTest(candidate=candidate):
                with self.assertRaises(ClipRenderError):
                    render_clip(self.source_path, candidate, self.output_directory)

        probe_mock.assert_not_called()
        run_mock.assert_not_called()

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_candidate_beyond_source_duration_is_rejected(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._source_info(duration=12.0)

        with self.assertRaisesRegex(ClipRenderError, "exceeds"):
            render_clip(self.source_path, self.candidate, self.output_directory)

        run_mock.assert_not_called()
        self.assertFalse(self.output_directory.exists())

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_missing_ffmpeg_is_project_error_and_removes_reserved_output(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._source_info()
        run_mock.side_effect = FileNotFoundError("ffmpeg was not found")

        with self.assertRaisesRegex(ClipRenderError, "Could not start FFmpeg"):
            render_clip(self.source_path, self.candidate, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_ffmpeg_failure_removes_partial_output(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._source_info()

        def fail_after_write(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "encode failed")

        run_mock.side_effect = fail_after_write

        with self.assertRaisesRegex(ClipRenderError, "encode failed"):
            render_clip(self.source_path, self.candidate, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @patch("app.services.clip_renderer.subprocess.run")
    @patch("app.services.clip_renderer.probe_media")
    def test_empty_success_output_is_rejected_and_removed(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._source_info()
        run_mock.return_value = subprocess.CompletedProcess([], 0, "", "")

        with self.assertRaisesRegex(ClipRenderError, "usable clip"):
            render_clip(self.source_path, self.candidate, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @staticmethod
    def _source_info(duration: float = 20.95) -> MediaInfo:
        return MediaInfo(
            duration_seconds=duration,
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="hevc",
            audio_codec="aac",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )

    @staticmethod
    def _clip_info() -> MediaInfo:
        return MediaInfo(
            duration_seconds=5.04,
            has_video_stream=True,
            has_audio_stream=True,
            video_codec="h264",
            audio_codec="aac",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )
