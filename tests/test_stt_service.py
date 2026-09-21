from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from app.services.stt_service import (
    DEFAULT_COMPUTE_TYPE,
    DEFAULT_DEVICE,
    DEFAULT_LANGUAGE,
    DEFAULT_MODEL_NAME,
    STTError,
    load_model,
    transcribe_audio,
)


class STTServiceTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.audio_path = self.root / "eval_01.wav"
        self.audio_path.write_bytes(b"RIFF-test-wave")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_transcription_returns_segment_structure(self) -> None:
        model = Mock()
        model.transcribe.return_value = (
            iter(
                [
                    SimpleNamespace(start=0.5, end=2.0, text=" 첫 문장", words=None),
                    SimpleNamespace(start=16.1, end=18.8, text="AI야 방금 장면 꼭 살려줘", words=None),
                ]
            ),
            SimpleNamespace(language="ko", language_probability=0.98),
        )

        result = transcribe_audio(self.audio_path, model=model)

        self.assertEqual(result.text, "첫 문장 AI야 방금 장면 꼭 살려줘")
        self.assertEqual(result.language, "ko")
        self.assertEqual(result.language_probability, 0.98)
        self.assertEqual(len(result.segments), 2)
        self.assertEqual(result.segments[1].start_seconds, 16.1)
        self.assertEqual(result.segments[1].end_seconds, 18.8)
        self.assertEqual(result.segments[1].text, "AI야 방금 장면 꼭 살려줘")
        self.assertEqual(result.segments[1].words, ())
        model.transcribe.assert_called_once_with(
            str(self.audio_path), language=DEFAULT_LANGUAGE, word_timestamps=False
        )

    def test_word_timestamps_are_optional(self) -> None:
        model = Mock()
        model.transcribe.return_value = (
            iter(
                [
                    SimpleNamespace(
                        start=16.0,
                        end=17.0,
                        text="AI야",
                        words=[
                            SimpleNamespace(
                                start=16.0,
                                end=16.6,
                                word=" AI야",
                                probability=0.91,
                            )
                        ],
                    )
                ]
            ),
            SimpleNamespace(language="ko", language_probability=0.99),
        )

        result = transcribe_audio(
            self.audio_path, model=model, word_timestamps=True
        )

        word = result.segments[0].words[0]
        self.assertEqual(word.text, "AI야")
        self.assertEqual(word.start_seconds, 16.0)
        self.assertEqual(word.end_seconds, 16.6)
        self.assertEqual(word.probability, 0.91)

    def test_empty_audio_is_rejected_before_model_use(self) -> None:
        empty_audio = self.root / "empty.wav"
        empty_audio.touch()
        model = Mock()

        with self.assertRaisesRegex(STTError, "empty"):
            transcribe_audio(empty_audio, model=model)

        model.transcribe.assert_not_called()

    def test_non_wav_input_is_rejected_before_model_use(self) -> None:
        invalid_audio = self.root / "audio.txt"
        invalid_audio.write_bytes(b"not wave")
        model = Mock()

        with self.assertRaisesRegex(STTError, "must be WAV"):
            transcribe_audio(invalid_audio, model=model)

        model.transcribe.assert_not_called()

    @patch("app.services.stt_service.WhisperModel")
    def test_model_loading_failure_is_project_error(self, model_class) -> None:
        model_class.side_effect = RuntimeError("download failed")

        with self.assertRaisesRegex(STTError, "Could not load"):
            load_model()

        model_class.assert_called_once_with(
            DEFAULT_MODEL_NAME,
            device=DEFAULT_DEVICE,
            compute_type=DEFAULT_COMPUTE_TYPE,
        )

    def test_transcribe_failure_is_project_error(self) -> None:
        model = Mock()
        model.transcribe.side_effect = RuntimeError("decode failed")

        with self.assertRaisesRegex(STTError, "transcription failed"):
            transcribe_audio(self.audio_path, model=model)

    def test_lazy_segment_failure_is_project_error(self) -> None:
        model = Mock()

        def failing_segments():
            raise RuntimeError("decode failed while iterating")
            yield

        model.transcribe.return_value = (
            failing_segments(),
            SimpleNamespace(language="ko", language_probability=1.0),
        )

        with self.assertRaisesRegex(STTError, "transcription failed"):
            transcribe_audio(self.audio_path, model=model)
