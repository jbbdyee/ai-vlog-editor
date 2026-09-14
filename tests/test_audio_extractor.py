from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.audio_extractor import AudioExtractionError, extract_audio
from app.services.media_probe import MediaInfo


class AudioExtractorTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_path = self.root / "source.MOV"
        self.source_path.touch()
        self.output_directory = self.root / "missing" / "audio"

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_mov_or_mp4_is_extracted_to_wav_and_directory_is_created(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._media_info()

        def create_wav(command, **kwargs):
            Path(command[-1]).write_bytes(b"RIFF-test-wave")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_wav

        for extension in (".MOV", ".mp4"):
            with self.subTest(extension=extension):
                source = self.root / f"source{extension}"
                source.touch()
                extracted = extract_audio(source, self.output_directory)

                self.assertTrue(self.output_directory.is_dir())
                self.assertEqual(extracted.source_path, source)
                self.assertEqual(extracted.audio_path.suffix, ".wav")
                self.assertTrue(extracted.audio_path.is_file())
                self.assertEqual(extracted.duration_seconds, 20.95)
                self.assertEqual(extracted.sample_rate_hz, 16_000)
                self.assertEqual(extracted.channels, 1)
                self.assertEqual(extracted.codec, "pcm_s16le")

        command = run_mock.call_args.args[0]
        self.assertIn("-nostdin", command)
        self.assertIn("-y", command)
        self.assertEqual(command[command.index("-map") + 1], "0:a:0")
        self.assertEqual(command[command.index("-acodec") + 1], "pcm_s16le")
        self.assertEqual(command[command.index("-ar") + 1], "16000")
        self.assertEqual(command[command.index("-ac") + 1], "1")
        self.assertNotIn("shell", run_mock.call_args.kwargs)

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_existing_output_is_not_overwritten(self, probe_mock, run_mock) -> None:
        probe_mock.return_value = self._media_info()
        self.output_directory.mkdir(parents=True)
        existing = self.output_directory / "existing.wav"
        existing.write_bytes(b"keep-me")

        def create_wav(command, **kwargs):
            Path(command[-1]).write_bytes(b"new-wave")
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_wav

        extracted = extract_audio(self.source_path, self.output_directory)

        self.assertEqual(existing.read_bytes(), b"keep-me")
        self.assertNotEqual(extracted.audio_path, existing)

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_video_without_audio_is_rejected_before_ffmpeg(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._media_info(has_audio_stream=False)

        with self.assertRaisesRegex(AudioExtractionError, "no audio stream"):
            extract_audio(self.source_path, self.output_directory)

        run_mock.assert_not_called()
        self.assertFalse(self.output_directory.exists())

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_missing_input_is_rejected_before_probe_or_ffmpeg(
        self, probe_mock, run_mock
    ) -> None:
        missing = self.root / "missing.mp4"

        with self.assertRaisesRegex(AudioExtractionError, "does not exist"):
            extract_audio(missing, self.output_directory)

        probe_mock.assert_not_called()
        run_mock.assert_not_called()

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_missing_ffmpeg_is_project_error_and_leaves_no_output(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._media_info()
        run_mock.side_effect = FileNotFoundError("ffmpeg was not found")

        with self.assertRaisesRegex(AudioExtractionError, "Could not start FFmpeg"):
            extract_audio(self.source_path, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_ffmpeg_failure_removes_partial_output(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._media_info()

        def fail_after_partial_write(command, **kwargs):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, "", "decode failed")

        run_mock.side_effect = fail_after_partial_write

        with self.assertRaisesRegex(AudioExtractionError, "decode failed"):
            extract_audio(self.source_path, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @patch("app.services.audio_extractor.subprocess.run")
    @patch("app.services.audio_extractor.probe_media")
    def test_zero_length_output_is_rejected_and_removed(
        self, probe_mock, run_mock
    ) -> None:
        probe_mock.return_value = self._media_info()

        def create_empty_wav(command, **kwargs):
            Path(command[-1]).touch()
            return subprocess.CompletedProcess(command, 0, "", "")

        run_mock.side_effect = create_empty_wav

        with self.assertRaisesRegex(AudioExtractionError, "usable audio file"):
            extract_audio(self.source_path, self.output_directory)

        self.assertEqual(list(self.output_directory.iterdir()), [])

    @staticmethod
    def _media_info(*, has_audio_stream: bool = True) -> MediaInfo:
        return MediaInfo(
            duration_seconds=20.95,
            has_video_stream=True,
            has_audio_stream=has_audio_stream,
            video_codec="hevc",
            audio_codec="aac" if has_audio_stream else None,
            format_name="mov,mp4,m4a,3gp,3g2,mj2",
        )
