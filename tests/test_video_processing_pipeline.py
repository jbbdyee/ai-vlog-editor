from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from app.services.audio_extractor import ExtractedAudio
from app.services.candidate_generator import SceneCandidate
from app.services.clip_renderer import ClipRenderError, RenderedClip
from app.services.media_probe import MediaInfo
from app.services.memo_detector import EditMemo
from app.services.scene_selector import (
    FixedWindowSceneSelector,
    SceneSelectionContext,
    SceneSelectionError,
    SceneSelectionResult,
)
from app.services.stt_service import STTError, STTResult, TranscriptSegment
from app.services.video_processing_pipeline import (
    PipelineExecutionError,
    PipelineStage,
    PipelineStatus,
    VideoProcessingInput,
    VideoProcessingPipeline,
)


class FixedWindowSceneSelectorTests(TestCase):
    def setUp(self) -> None:
        self.candidates = (
            SceneCandidate(5.0, 10.0, 15.0),
            SceneCandidate(10.0, 5.0, 15.0),
            SceneCandidate(7.5, 7.5, 15.0),
        )

    def test_selects_exact_requested_window_without_modifying_candidate(self) -> None:
        selector = FixedWindowSceneSelector(window_seconds=5.0)

        result = selector.select(self._context(self.candidates))

        self.assertIs(result.candidate, self.candidates[0])
        self.assertEqual(result.strategy_name, "fixed_window")
        self.assertEqual(result.selected_source_id, "window:5.0")
        self.assertEqual(result.reasoning_code, "FIXED_WINDOW_SELECTED")
        self.assertIsNone(result.reasoning_summary)

    def test_custom_window_can_be_selected(self) -> None:
        result = FixedWindowSceneSelector(window_seconds=7.5).select(
            self._context(self.candidates)
        )

        self.assertIs(result.candidate, self.candidates[2])

    def test_missing_window_is_rejected(self) -> None:
        selector = FixedWindowSceneSelector(window_seconds=30.0)

        with self.assertRaisesRegex(SceneSelectionError, "No generated candidate"):
            selector.select(self._context(self.candidates))

    def test_duplicate_matching_windows_are_rejected(self) -> None:
        duplicate = SceneCandidate(5.0, 9.5, 14.5)

        with self.assertRaisesRegex(SceneSelectionError, "Multiple"):
            FixedWindowSceneSelector(window_seconds=5.0).select(
                self._context(self.candidates + (duplicate,))
            )

    def test_invalid_window_values_are_rejected(self) -> None:
        for value in (0, -1, float("nan"), float("inf"), "5", True):
            with self.subTest(value=value):
                with self.assertRaises(SceneSelectionError):
                    FixedWindowSceneSelector(window_seconds=value)  # type: ignore[arg-type]

    @staticmethod
    def _context(
        candidates: tuple[SceneCandidate, ...]
    ) -> SceneSelectionContext:
        source = Path("source.mov")
        audio = ExtractedAudio(source, Path("audio.wav"), 20.0, 16_000, 1, "pcm_s16le")
        info = MediaInfo(20.0, True, True, "hevc", "aac", "mov")
        memo = _memo(15.0, 18.0, "AI야 방금 장면 꼭 살려줘")
        transcript = STTResult(memo.transcript_text, (), "ko", 1.0)
        return SceneSelectionContext(
            source_video_path=source,
            extracted_audio=audio,
            media_info=info,
            transcript=transcript,
            memo=memo,
            fixed_candidates=candidates,
        )


class VideoProcessingPipelineTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.source_path = self.root / "source.MOV"
        self.source_path.write_bytes(b"source-must-remain")
        self.output_directory = self.root / "outputs"
        self.stt_model = Mock(name="stt_model")
        self.selector = Mock(name="scene_selector")
        self.pipeline = VideoProcessingPipeline(
            selector=self.selector,
            stt_model=self.stt_model,
        )

        patch_targets = {
            "probe": "app.services.video_processing_pipeline.probe_media",
            "extract": "app.services.video_processing_pipeline.extract_audio",
            "transcribe": "app.services.video_processing_pipeline.transcribe_audio",
            "detect": "app.services.video_processing_pipeline.detect_edit_memos",
            "generate": "app.services.video_processing_pipeline.generate_candidates",
            "render": "app.services.video_processing_pipeline.render_clip",
        }
        self.mocks: dict[str, Mock] = {}
        for name, target in patch_targets.items():
            patcher = patch(target)
            self.mocks[name] = patcher.start()
            self.addCleanup(patcher.stop)

        self.media_info = MediaInfo(20.0, True, True, "hevc", "aac", "mov")
        self.transcript = STTResult(
            "AI야 방금 장면 꼭 살려줘",
            (TranscriptSegment(15.0, 18.0, "AI야 방금 장면 꼭 살려줘"),),
            "ko",
            1.0,
        )
        self.memo = _memo(15.0, 18.0, self.transcript.text)
        self.candidates = (
            SceneCandidate(5.0, 10.0, 15.0),
            SceneCandidate(10.0, 5.0, 15.0),
        )
        self._configure_happy_path((self.memo,))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_happy_path_calls_services_in_order_and_requests_word_timestamps(self) -> None:
        events: list[str] = []
        for name in ("probe", "extract", "transcribe", "detect", "generate", "render"):
            original = self.mocks[name].side_effect
            original_return = self.mocks[name].return_value

            def record(
                *args,
                _name=name,
                _original=original,
                _return=original_return,
                **kwargs,
            ):
                events.append(_name)
                return _original(*args, **kwargs) if _original else _return

            self.mocks[name].side_effect = record
        self.selector.select.side_effect = lambda context: (
            events.append("select") or _selection(context.fixed_candidates[0])
        )

        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.COMPLETED)
        self.assertEqual(events, ["probe", "extract", "transcribe", "detect", "generate", "select", "render"])
        self.mocks["transcribe"].assert_called_once_with(
            self._audio_path(), model=self.stt_model, word_timestamps=True
        )
        audio_output = self.mocks["extract"].call_args.args[1]
        clip_output = self.mocks["render"].call_args.args[2]
        self.assertEqual(audio_output.name, "audio")
        self.assertEqual(clip_output.name, "clips")
        self.assertEqual(audio_output.parent, clip_output.parent)
        self.assertEqual(audio_output.parent.parent, self.output_directory)
        self.assertEqual(len(result.memo_results), 1)
        self.assertIsNone(result.extracted_audio)
        self.assertFalse(self._audio_path().exists())

    def test_audio_stream_missing_stops_before_downstream_services(self) -> None:
        self.mocks["probe"].return_value = MediaInfo(
            20.0, True, False, "hevc", None, "mov"
        )

        with self.assertRaises(PipelineExecutionError) as raised:
            self.pipeline.process(self._input())

        self.assertEqual(raised.exception.stage, PipelineStage.MEDIA_PROBE)
        self.mocks["extract"].assert_not_called()
        self.mocks["transcribe"].assert_not_called()
        self.selector.select.assert_not_called()
        self.mocks["render"].assert_not_called()

    def test_stt_failure_cleans_audio_and_does_not_select_or_render(self) -> None:
        self.mocks["transcribe"].side_effect = STTError("unsafe provider detail")

        with self.assertRaises(PipelineExecutionError) as raised:
            self.pipeline.process(self._input())

        self.assertEqual(raised.exception.stage, PipelineStage.STT)
        self.assertEqual(raised.exception.cause_type, "STTError")
        self.assertNotIn("unsafe provider detail", raised.exception.safe_message)
        self.assertFalse(self._audio_path().exists())
        self.selector.select.assert_not_called()
        self.mocks["render"].assert_not_called()

    def test_no_edit_memo_is_normal_result_without_selection_or_render(self) -> None:
        self.mocks["detect"].return_value = ()

        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.NO_EDIT_MEMO)
        self.assertEqual(result.memo_results, ())
        self.selector.select.assert_not_called()
        self.mocks["render"].assert_not_called()

    def test_selector_abstain_returns_no_scene_selected_without_render(self) -> None:
        self.selector.select.return_value = _selection(None)

        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.NO_SCENE_SELECTED)
        self.assertIsNone(result.memo_results[0].rendered_clip)
        self.mocks["render"].assert_not_called()

    def test_selector_exception_is_wrapped_without_fallback(self) -> None:
        self.selector.select.side_effect = SceneSelectionError("selection failed")

        with self.assertRaises(PipelineExecutionError) as raised:
            self.pipeline.process(self._input())

        self.assertEqual(raised.exception.stage, PipelineStage.CANDIDATE_SELECTION)
        self.assertEqual(raised.exception.cause_type, "SceneSelectionError")
        self.assertFalse(self._audio_path().exists())
        self.mocks["render"].assert_not_called()
        self.selector.select.assert_called_once()

    def test_render_failure_is_wrapped_and_audio_is_cleaned(self) -> None:
        self.mocks["render"].side_effect = ClipRenderError("render failed")

        with self.assertRaises(PipelineExecutionError) as raised:
            self.pipeline.process(self._input())

        self.assertEqual(raised.exception.stage, PipelineStage.CLIP_RENDERING)
        self.assertEqual(raised.exception.cause_type, "ClipRenderError")
        self.assertFalse(self._audio_path().exists())

    def test_keep_intermediate_audio_preserves_audio_and_result(self) -> None:
        result = self.pipeline.process(self._input(keep_audio=True))

        self.assertIsNotNone(result.extracted_audio)
        self.assertTrue(self._audio_path().is_file())

    @patch(
        "app.services.video_processing_pipeline._remove_intermediate_audio",
        side_effect=OSError("cleanup failed"),
    )
    def test_cleanup_failure_is_a_warning_not_pipeline_failure(self, _remove) -> None:
        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.COMPLETED)
        self.assertEqual(
            result.warnings,
            ("Could not remove the intermediate audio file.",),
        )

    def test_multiple_memos_preserve_order_and_links(self) -> None:
        second_memo = _memo(18.0, 19.0, "AI야 지금 장면 꼭 살려줘")
        first_candidates = (SceneCandidate(5.0, 10.0, 15.0),)
        second_candidates = (SceneCandidate(5.0, 13.0, 18.0),)
        first_clip = self._rendered_clip(first_candidates[0], "first.mp4")
        second_clip = self._rendered_clip(second_candidates[0], "second.mp4")
        self.mocks["detect"].return_value = (self.memo, second_memo)
        self.mocks["generate"].side_effect = (first_candidates, second_candidates)
        self.selector.select.side_effect = (
            _selection(first_candidates[0]),
            _selection(second_candidates[0]),
        )
        self.mocks["render"].side_effect = (first_clip, second_clip)

        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.COMPLETED)
        self.assertEqual(
            tuple(item.memo for item in result.memo_results),
            (self.memo, second_memo),
        )
        self.assertEqual(
            tuple(item.rendered_clip for item in result.memo_results),
            (first_clip, second_clip),
        )
        self.assertEqual(self.selector.select.call_count, 2)
        self.assertEqual(self.mocks["render"].call_count, 2)

    def test_mixed_abstain_and_render_is_completed(self) -> None:
        second_memo = _memo(18.0, 19.0, "AI야 지금 장면 꼭 살려줘")
        second_candidates = (SceneCandidate(5.0, 13.0, 18.0),)
        self.mocks["detect"].return_value = (self.memo, second_memo)
        self.mocks["generate"].side_effect = (self.candidates, second_candidates)
        self.selector.select.side_effect = (
            _selection(None),
            _selection(second_candidates[0]),
        )

        result = self.pipeline.process(self._input())

        self.assertEqual(result.status, PipelineStatus.COMPLETED)
        self.assertIsNone(result.memo_results[0].rendered_clip)
        self.assertIsNotNone(result.memo_results[1].rendered_clip)
        self.mocks["render"].assert_called_once()

    def test_timings_include_each_executed_stage_and_total(self) -> None:
        result = self.pipeline.process(self._input())

        stages = tuple(timing.stage for timing in result.timings)
        self.assertEqual(
            stages,
            (
                PipelineStage.OUTPUT_PREPARATION,
                PipelineStage.MEDIA_PROBE,
                PipelineStage.AUDIO_EXTRACTION,
                PipelineStage.STT,
                PipelineStage.MEMO_DETECTION,
                PipelineStage.CANDIDATE_GENERATION,
                PipelineStage.CANDIDATE_SELECTION,
                PipelineStage.CLIP_RENDERING,
                PipelineStage.TOTAL,
            ),
        )
        self.assertTrue(all(timing.duration_seconds >= 0 for timing in result.timings))

    def test_source_video_is_never_removed(self) -> None:
        self.pipeline.process(self._input())

        self.assertEqual(self.source_path.read_bytes(), b"source-must-remain")

    def _configure_happy_path(self, memos: tuple[EditMemo, ...]) -> None:
        self.mocks["probe"].return_value = self.media_info

        def extract(_source, output_directory):
            output_directory.mkdir(parents=True, exist_ok=True)
            self._audio_path().write_bytes(b"RIFF-test")
            return ExtractedAudio(
                self.source_path,
                self._audio_path(),
                20.0,
                16_000,
                1,
                "pcm_s16le",
            )

        self.mocks["extract"].side_effect = extract
        self.mocks["transcribe"].return_value = self.transcript
        self.mocks["detect"].return_value = memos
        self.mocks["generate"].return_value = self.candidates
        self.selector.select.side_effect = None
        self.selector.select.return_value = _selection(self.candidates[0])
        self.mocks["render"].side_effect = lambda source, candidate, output: (
            self._rendered_clip(candidate, "clip.mp4")
        )

    def _input(self, *, keep_audio: bool = False) -> VideoProcessingInput:
        return VideoProcessingInput(
            source_video_path=self.source_path,
            output_directory=self.output_directory,
            keep_intermediate_audio=keep_audio,
        )

    def _audio_path(self) -> Path:
        return self.root / "mock-audio.wav"

    def _rendered_clip(
        self, candidate: SceneCandidate, filename: str
    ) -> RenderedClip:
        return RenderedClip(
            source_path=self.source_path,
            clip_path=self.root / filename,
            start_seconds=candidate.start_seconds,
            end_seconds=candidate.end_seconds,
            duration_seconds=candidate.end_seconds - candidate.start_seconds,
            video_codec="h264",
            audio_codec="aac",
        )


def _memo(start: float, end: float, text: str) -> EditMemo:
    return EditMemo(
        start_seconds=start,
        end_seconds=end,
        transcript_text=text,
        matched_trigger="AI야",
        matched_reference="방금",
        matched_action="살려줘",
    )


def _selection(candidate: SceneCandidate | None) -> SceneSelectionResult:
    return SceneSelectionResult(
        strategy_name="test_selector",
        candidate=candidate,
        selected_source_id=None if candidate is None else "test-source",
        reasoning_code=("NO_SELECTION" if candidate is None else "TEST_SELECTED"),
        reasoning_summary=None,
    )
