from dataclasses import fields
import math
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from app.services.transcript_scene_retriever import TranscriptBlock
from app.services.visual_motion_refiner import (
    VisualBoundaryConfig,
    VisualBoundaryRefinementResult,
    VisualBoundaryStatus,
    _MotionScore,
    _build_motion_intervals,
    refine_visual_boundary,
)


class VisualMotionRefinerTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.video = self.root / "source.mov"
        self.video.write_bytes(b"local fixture")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_single_connected_motion_episode_is_refined(self) -> None:
        frames = self._brightness_frames(40, ((10, 18),))
        result = self._run(frames, block=self._block(2.2, 3.5), memo=6.0)

        self.assertEqual(result.status, VisualBoundaryStatus.REFINED)
        self.assertIsNotNone(result.selected_interval)
        self.assertEqual(result.to_scene_candidate().start_seconds, result.refined_start_seconds)

    def test_static_frames_return_no_signal_with_zero_mad_policy(self) -> None:
        result = self._run(self._solid_frames(30, 0), block=self._block(2.0, 3.0))

        self.assertEqual(result.status, VisualBoundaryStatus.NO_SIGNAL)
        self.assertEqual(result.median_absolute_deviation, 0.0)
        self.assertGreater(result.activity_threshold, result.motion_score_median)

    def test_multiple_connected_episodes_are_ambiguous(self) -> None:
        frames = self._brightness_frames(40, ((5, 10), (22, 28)))
        result = self._run(frames, block=self._block(1.0, 5.8), memo=7.0)

        self.assertEqual(result.status, VisualBoundaryStatus.AMBIGUOUS_SIGNAL)
        self.assertIsNone(result.selected_interval)
        self.assertGreaterEqual(
            sum(interval.overlaps_selected_block for interval in result.activity_intervals),
            2,
        )

    def test_short_motion_spike_is_removed(self) -> None:
        intervals, signals = _build_motion_intervals(
            (_MotionScore(timestamp_seconds=2.0, score=0.5),),
            block_start=1.0,
            block_end=3.0,
            sample_fps=5,
            minimum_duration=0.4,
            maximum_gap=0.6,
        )

        self.assertEqual(intervals, ())
        self.assertEqual(signals, ())

    def test_quiet_gap_at_limit_is_merged(self) -> None:
        intervals, _ = _build_motion_intervals(
            (
                _MotionScore(1.0, 0.4),
                _MotionScore(1.2, 0.5),
                _MotionScore(2.0, 0.6),
                _MotionScore(2.2, 0.4),
            ),
            block_start=1.0,
            block_end=2.0,
            sample_fps=5,
            minimum_duration=0.4,
            maximum_gap=0.6,
        )

        self.assertEqual(len(intervals), 1)
        self.assertAlmostEqual(intervals[0].start_seconds, 0.8)
        self.assertAlmostEqual(intervals[0].end_seconds, 2.2)

    def test_motion_not_connected_to_selected_block_is_ignored(self) -> None:
        frames = self._brightness_frames(40, ((5, 10),))
        result = self._run(frames, block=self._block(4.5, 5.5), memo=7.0)

        self.assertEqual(result.status, VisualBoundaryStatus.NO_SIGNAL)
        self.assertTrue(result.activity_intervals)
        self.assertFalse(any(i.overlaps_selected_block for i in result.activity_intervals))

    def test_search_and_candidate_stay_within_video_boundaries(self) -> None:
        frames = self._brightness_frames(25, ((1, 7), (17, 23)))
        start_result = self._run(
            frames, block=self._block(0.1, 1.2), memo=5.0, duration=5.0
        )
        end_result = self._run(
            frames, block=self._block(3.6, 4.8), memo=5.0, duration=5.0
        )

        self.assertEqual(start_result.search_start_seconds, 0.0)
        self.assertGreaterEqual(start_result.refined_start_seconds or 0.0, 0.0)
        self.assertLessEqual(end_result.refined_end_seconds or 5.0, 5.0)

    def test_missing_video_and_invalid_numbers_return_invalid_input(self) -> None:
        missing = refine_visual_boundary(
            self.root / "missing.mov",
            video_duration_seconds=5.0,
            selected_block=self._block(1.0, 2.0),
            previous_block_end_seconds=None,
            next_block_start_seconds=None,
            memo_start_seconds=4.0,
        )
        self.assertEqual(missing.status, VisualBoundaryStatus.INVALID_INPUT)

        for value in (float("nan"), float("inf"), True, "5"):
            with self.subTest(value=value):
                result = refine_visual_boundary(
                    self.video,
                    video_duration_seconds=value,  # type: ignore[arg-type]
                    selected_block=self._block(1.0, 2.0),
                    previous_block_end_seconds=None,
                    next_block_start_seconds=None,
                    memo_start_seconds=4.0,
                )
                self.assertEqual(result.status, VisualBoundaryStatus.INVALID_INPUT)

    def test_invalid_block_search_range_and_config_are_rejected(self) -> None:
        cases = (
            {"selected_block": self._block(2.0, 2.0)},
            {"previous_block_end_seconds": 2.5},
            {"next_block_start_seconds": 1.5},
            {"config": VisualBoundaryConfig(sample_fps=0)},
            {"config": VisualBoundaryConfig(threshold_mad_multiplier=math.nan)},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                arguments = {
                    "video_duration_seconds": 5.0,
                    "selected_block": self._block(2.0, 3.0),
                    "previous_block_end_seconds": None,
                    "next_block_start_seconds": None,
                    "memo_start_seconds": 4.0,
                }
                arguments.update(changes)
                result = refine_visual_boundary(self.video, **arguments)  # type: ignore[arg-type]
                self.assertEqual(result.status, VisualBoundaryStatus.INVALID_INPUT)

    def test_malformed_or_insufficient_frame_stream_is_processing_failure(self) -> None:
        for stream in (b"not pgm", self._pgm_stream((bytes(320),))):
            with self.subTest(size=len(stream)):
                result = self._run_stream(stream, block=self._block(1.0, 2.0))
                self.assertEqual(result.status, VisualBoundaryStatus.PROCESSING_FAILED)

    def test_truncated_frame_bytes_are_processing_failure(self) -> None:
        stream = b"P5\n160 2\n255\n" + bytes(319)
        result = self._run_stream(stream, block=self._block(1.0, 2.0))

        self.assertEqual(result.status, VisualBoundaryStatus.PROCESSING_FAILED)
        self.assertIn("truncated", result.failure_reason or "")

    def test_missing_ffmpeg_and_nonzero_exit_are_processing_failures(self) -> None:
        with patch("app.services.visual_motion_refiner.subprocess.run", side_effect=OSError("missing")):
            missing = self._call(block=self._block(1.0, 2.0))
        self.assertEqual(missing.status, VisualBoundaryStatus.PROCESSING_FAILED)

        failed_process = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=1, stdout=b"", stderr=b"decode failed"
        )
        with patch("app.services.visual_motion_refiner.subprocess.run", return_value=failed_process):
            failed = self._call(block=self._block(1.0, 2.0))
        self.assertEqual(failed.status, VisualBoundaryStatus.PROCESSING_FAILED)
        self.assertIn("decode failed", failed.failure_reason or "")

    def test_same_input_produces_same_result_and_shell_is_not_used(self) -> None:
        stream = self._pgm_stream(self._brightness_frames(30, ((8, 16),)))
        completed = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout=stream, stderr=b""
        )
        with patch("app.services.visual_motion_refiner.subprocess.run", return_value=completed) as run:
            first = self._call(block=self._block(1.8, 3.2))
            second = self._call(block=self._block(1.8, 3.2))

        self.assertEqual(first, second)
        self.assertNotIn("shell", run.call_args.kwargs)
        self.assertIsInstance(run.call_args.args[0], list)

    def test_ground_truth_is_absent_from_result_and_function_schema(self) -> None:
        result_fields = {field.name for field in fields(VisualBoundaryRefinementResult)}
        self.assertNotIn("ground_truth", result_fields)
        self.assertNotIn("iou", result_fields)
        self.assertNotIn("coverage", result_fields)
        self.assertNotIn("ground_truth", refine_visual_boundary.__annotations__)

    def _run(
        self,
        frames: tuple[bytes, ...],
        *,
        block: TranscriptBlock,
        memo: float = 6.0,
        duration: float = 8.0,
    ) -> VisualBoundaryRefinementResult:
        return self._run_stream(
            self._pgm_stream(frames), block=block, memo=memo, duration=duration
        )

    def _run_stream(
        self,
        stream: bytes,
        *,
        block: TranscriptBlock,
        memo: float = 6.0,
        duration: float = 8.0,
    ) -> VisualBoundaryRefinementResult:
        completed = subprocess.CompletedProcess(
            args=["ffmpeg"], returncode=0, stdout=stream, stderr=b""
        )
        with patch("app.services.visual_motion_refiner.subprocess.run", return_value=completed):
            return self._call(block=block, memo=memo, duration=duration)

    def _call(
        self,
        *,
        block: TranscriptBlock,
        memo: float = 4.0,
        duration: float = 5.0,
    ) -> VisualBoundaryRefinementResult:
        return refine_visual_boundary(
            self.video,
            video_duration_seconds=duration,
            selected_block=block,
            previous_block_end_seconds=None,
            next_block_start_seconds=None,
            memo_start_seconds=memo,
        )

    @staticmethod
    def _block(start: float, end: float) -> TranscriptBlock:
        return TranscriptBlock("block-0001", start, end, ("segment-0001",), "반응")

    @staticmethod
    def _solid_frames(count: int, brightness: int) -> tuple[bytes, ...]:
        return tuple(bytes([brightness]) * 320 for _ in range(count))

    def _brightness_frames(
        self, count: int, bursts: tuple[tuple[int, int], ...]
    ) -> tuple[bytes, ...]:
        values = [0] * count
        for start, end in bursts:
            for index in range(start, end):
                values[index] = 100 if index % 2 else 0
        return tuple(bytes([value]) * 320 for value in values)

    @staticmethod
    def _pgm_stream(frames: tuple[bytes, ...]) -> bytes:
        return b"".join(b"P5\n160 2\n255\n" + frame for frame in frames)
