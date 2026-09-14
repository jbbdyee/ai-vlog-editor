import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.media_probe import MediaProbeError, probe_media


class MediaProbeTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.media_directory = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("app.services.media_probe.subprocess.run")
    def test_mov_metadata_with_video_and_audio_is_parsed(self, run_mock) -> None:
        media_path = self._create_file("sample.MOV")
        run_mock.return_value = self._successful_result(
            duration="12.345000",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            streams=[
                {"codec_type": "video", "codec_name": "h264"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        )

        info = probe_media(media_path)

        self.assertEqual(info.duration_seconds, 12.345)
        self.assertTrue(info.has_video_stream)
        self.assertTrue(info.has_audio_stream)
        self.assertEqual(info.video_codec, "h264")
        self.assertEqual(info.audio_codec, "aac")
        self.assertEqual(info.format_name, "mov,mp4,m4a,3gp,3g2,mj2")
        self._assert_safe_command(run_mock, media_path)

    @patch("app.services.media_probe.subprocess.run")
    def test_mp4_metadata_with_video_and_audio_is_parsed(self, run_mock) -> None:
        media_path = self._create_file("sample.mp4")
        run_mock.return_value = self._successful_result(
            duration="7.25",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            streams=[
                {"codec_type": "audio", "codec_name": "opus"},
                {"codec_type": "video", "codec_name": "hevc"},
            ],
        )

        info = probe_media(media_path)

        self.assertEqual(info.duration_seconds, 7.25)
        self.assertEqual(info.video_codec, "hevc")
        self.assertEqual(info.audio_codec, "opus")

    @patch("app.services.media_probe.subprocess.run")
    def test_video_without_audio_is_parsed(self, run_mock) -> None:
        media_path = self._create_file("silent.mp4")
        run_mock.return_value = self._successful_result(
            duration="3.0",
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
            streams=[{"codec_type": "video", "codec_name": "h264"}],
        )

        info = probe_media(media_path)

        self.assertTrue(info.has_video_stream)
        self.assertFalse(info.has_audio_stream)
        self.assertIsNone(info.audio_codec)

    @patch("app.services.media_probe.subprocess.run")
    def test_missing_file_raises_before_ffprobe_runs(self, run_mock) -> None:
        missing_path = self.media_directory / "missing.mov"

        with self.assertRaisesRegex(MediaProbeError, "does not exist"):
            probe_media(missing_path)

        run_mock.assert_not_called()

    @patch("app.services.media_probe.subprocess.run")
    def test_ffprobe_failure_is_project_error(self, run_mock) -> None:
        media_path = self._create_file("broken.mp4")
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="Invalid data found"
        )

        with self.assertRaisesRegex(MediaProbeError, "ffprobe failed"):
            probe_media(media_path)

    @patch("app.services.media_probe.subprocess.run")
    def test_ffprobe_start_failure_is_project_error(self, run_mock) -> None:
        media_path = self._create_file("sample.mp4")
        run_mock.side_effect = FileNotFoundError("ffprobe was not found")

        with self.assertRaisesRegex(MediaProbeError, "Could not start ffprobe"):
            probe_media(media_path)

    @patch("app.services.media_probe.subprocess.run")
    def test_invalid_ffprobe_json_is_project_error(self, run_mock) -> None:
        media_path = self._create_file("broken.mov")
        run_mock.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )

        with self.assertRaisesRegex(MediaProbeError, "invalid JSON"):
            probe_media(media_path)

    def _create_file(self, filename: str) -> Path:
        path = self.media_directory / filename
        path.touch()
        return path

    @staticmethod
    def _successful_result(
        *, duration: str, format_name: str, streams: list[dict[str, str]]
    ) -> subprocess.CompletedProcess[str]:
        stdout = json.dumps(
            {
                "format": {"duration": duration, "format_name": format_name},
                "streams": streams,
            }
        )
        return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")

    def _assert_safe_command(self, run_mock, media_path: Path) -> None:
        run_mock.assert_called_once_with(
            [
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
