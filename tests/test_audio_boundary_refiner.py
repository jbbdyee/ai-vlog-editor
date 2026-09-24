from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
import math
import struct
import wave

from app.services.audio_boundary_refiner import (
    AudioBoundaryConfig,
    AudioBoundaryRefinementError,
    BoundaryEvidence,
    RefinedSceneCandidate,
    refine_scene_boundary,
)
from app.services.transcript_scene_retriever import TranscriptBlock


class AudioBoundaryRefinerTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_activity_before_reaction_expands_start(self) -> None:
        path = self._wav("before.wav", 5.0, ((1.0, 2.5, 6000),))
        result = self._refine(path, self._block(2.0, 2.5))

        self.assertAlmostEqual(result.candidate.start_seconds, 1.0, places=2)
        self.assertAlmostEqual(result.candidate.end_seconds, 2.5, places=2)
        self.assertEqual(result.candidate.start_evidence, BoundaryEvidence.ENERGY_ONSET)

    def test_activity_after_reaction_expands_end(self) -> None:
        path = self._wav("after.wav", 5.0, ((2.0, 3.5, 6000),))
        result = self._refine(path, self._block(2.0, 2.5))

        self.assertAlmostEqual(result.candidate.start_seconds, 2.0, places=2)
        self.assertAlmostEqual(result.candidate.end_seconds, 3.5, places=2)
        self.assertEqual(result.candidate.end_evidence, BoundaryEvidence.ENERGY_OFFSET)

    def test_internal_quiet_boundary_trims_selected_block_start(self) -> None:
        path = self._wav("trim.wav", 5.0, ((2.8, 3.8, 6000),))
        result = self._refine(path, self._block(2.0, 3.5))

        self.assertAlmostEqual(result.candidate.start_seconds, 2.8, places=2)
        self.assertAlmostEqual(result.candidate.end_seconds, 3.8, places=2)

    def test_no_activity_is_rejected_without_fallback(self) -> None:
        path = self._wav("silent.wav", 5.0, ())
        with self.assertRaisesRegex(AudioBoundaryRefinementError, "No valid audio"):
            self._refine(path, self._block(2.0, 2.5))

    def test_short_noise_spike_is_removed(self) -> None:
        path = self._wav("spike.wav", 5.0, ((2.0, 2.04, 12000),))
        with self.assertRaisesRegex(AudioBoundaryRefinementError, "No valid audio"):
            self._refine(path, self._block(2.0, 2.5))

    def test_short_quiet_gap_merges_activity(self) -> None:
        path = self._wav(
            "merge.wav", 5.0, ((1.5, 2.0, 6000), (2.2, 2.8, 6000))
        )
        result = self._refine(path, self._block(1.8, 2.5))

        self.assertEqual(len(result.activity_intervals), 1)
        self.assertAlmostEqual(result.candidate.start_seconds, 1.5, places=2)
        self.assertAlmostEqual(result.candidate.end_seconds, 2.8, places=2)

    def test_video_boundaries_clip_search_and_candidate(self) -> None:
        path = self._wav("edges.wav", 5.0, ((0.0, 0.4, 6000), (4.6, 5.0, 6000)))
        start_result = self._refine(path, self._block(0.1, 0.3), memo=1.0)
        end_result = self._refine(path, self._block(4.7, 4.9), memo=5.0)

        self.assertEqual(start_result.candidate.start_seconds, 0.0)
        self.assertEqual(end_result.candidate.end_seconds, 5.0)

    def test_invalid_wav_is_rejected(self) -> None:
        path = self.root / "invalid.wav"
        path.write_bytes(b"not a wav")
        with self.assertRaisesRegex(AudioBoundaryRefinementError, "Could not read"):
            self._refine(path, self._block(2.0, 2.5))

    def test_nan_inf_wrong_types_and_invalid_config_are_rejected(self) -> None:
        path = self._wav("valid.wav", 5.0, ((2.0, 2.5, 6000),))
        invalid_values = (float("nan"), float("inf"), "10", True)
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(AudioBoundaryRefinementError):
                    self._refine(path, self._block(2.0, 2.5), duration=value)

        configs = (
            AudioBoundaryConfig(frame_duration_ms=0),
            AudioBoundaryConfig(energy_margin_db=math.nan),
            AudioBoundaryConfig(minimum_activity_duration_seconds=0),
            AudioBoundaryConfig(maximum_quiet_gap_seconds=-1),
        )
        for config in configs:
            with self.subTest(config=config):
                with self.assertRaises(AudioBoundaryRefinementError):
                    self._refine(path, self._block(2.0, 2.5), config=config)

    def test_same_input_produces_same_result(self) -> None:
        path = self._wav("stable.wav", 5.0, ((1.0, 2.8, 6000),))
        first = self._refine(path, self._block(2.0, 2.5))
        second = self._refine(path, self._block(2.0, 2.5))

        self.assertEqual(first, second)

    def test_ground_truth_is_not_part_of_input_or_output_schema(self) -> None:
        field_names = {field.name for field in fields(RefinedSceneCandidate)}
        self.assertNotIn("ground_truth", field_names)
        self.assertNotIn("iou", field_names)
        self.assertNotIn("coverage", field_names)

    def _refine(
        self,
        path: Path,
        block: TranscriptBlock,
        *,
        duration: object = 5.0,
        memo: float = 4.5,
        config: AudioBoundaryConfig = AudioBoundaryConfig(),
    ):
        return refine_scene_boundary(
            path,
            video_duration_seconds=duration,  # type: ignore[arg-type]
            selected_block=block,
            previous_block_end_seconds=None,
            next_block_start_seconds=None,
            memo_start_seconds=memo,
            config=config,
        )

    @staticmethod
    def _block(start: float, end: float) -> TranscriptBlock:
        return TranscriptBlock("block-0001", start, end, ("segment-0001",), "반응")

    def _wav(
        self,
        name: str,
        duration: float,
        activities: tuple[tuple[float, float, int], ...],
    ) -> Path:
        sample_rate = 16_000
        samples = [100] * round(duration * sample_rate)
        for start, end, amplitude in activities:
            for index in range(round(start * sample_rate), round(end * sample_rate)):
                samples[index] = amplitude if index % 2 == 0 else -amplitude
        path = self.root / name
        with wave.open(str(path), "wb") as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(struct.pack(f"<{len(samples)}h", *samples))
        return path
