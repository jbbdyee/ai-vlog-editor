from pathlib import Path
from unittest import TestCase
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.routers.videos import PROCESS_OUTPUT_DIRECTORY
from app.services.candidate_generator import SceneCandidate
from app.services.clip_renderer import RenderedClip
from app.services.media_probe import MediaInfo
from app.services.memo_detector import EditMemo
from app.services.scene_selector import SceneSelectionResult
from app.services.stt_service import STTResult, TranscriptSegment
from app.services.video_processing_pipeline import (
    MemoProcessingResult,
    PipelineExecutionError,
    PipelineStage,
    PipelineStageTiming,
    PipelineStatus,
    VideoProcessingResult,
)
from app.services.video_storage import StoredVideo, VideoValidationError


MOV_CONTENT = b"\x00\x00\x00\x18ftypqt  \x00\x00\x00\x00qt  "
STORED_VIDEO_ID = "a" * 32
STORED_FILENAME = f"{STORED_VIDEO_ID}.mov"


class _TrackingSemaphore:
    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self):
        self.enter_count += 1
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        self.exit_count += 1
        return False


class VideoProcessAPITests(TestCase):
    def setUp(self) -> None:
        self.stt_model = object()
        self.load_model_patcher = patch(
            "app.main.load_model", return_value=self.stt_model
        )
        self.load_model_mock = self.load_model_patcher.start()
        self.addCleanup(self.load_model_patcher.stop)

        self.save_patcher = patch("app.routers.videos.save_video_file")
        self.save_mock = self.save_patcher.start()
        self.addCleanup(self.save_patcher.stop)
        self.save_mock.return_value = StoredVideo(
            original_filename="eval.mov",
            stored_filename=STORED_FILENAME,
            content_type="video/quicktime",
            video_id=STORED_VIDEO_ID,
        )

        self.pipeline_patcher = patch("app.routers.videos.VideoProcessingPipeline")
        self.pipeline_class_mock = self.pipeline_patcher.start()
        self.addCleanup(self.pipeline_patcher.stop)
        self.pipeline_mock = self.pipeline_class_mock.return_value
        self.pipeline_mock.process.return_value = self._completed_result()

        self.client_context = TestClient(app)
        self.client = self.client_context.__enter__()
        self.addCleanup(self.client_context.__exit__, None, None, None)

    def test_lifespan_loads_model_once_and_sets_shared_state(self) -> None:
        self.load_model_mock.assert_called_once_with()
        self.assertIs(app.state.stt_model, self.stt_model)
        self.assertEqual(app.state.pipeline_semaphore._value, 1)

    def test_happy_path_uses_threadpool_shared_model_and_safe_response(self) -> None:
        calls: list[object] = []

        async def run_now(function, *args, **kwargs):
            calls.append(function)
            return function(*args, **kwargs)

        with patch(
            "app.routers.videos.run_in_threadpool",
            new=AsyncMock(side_effect=run_now),
        ):
            response = self._post(window="5.0")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [self.save_mock, self.pipeline_mock.process])
        self.save_mock.assert_called_once()
        constructor_arguments = self.pipeline_class_mock.call_args.kwargs
        self.assertEqual(constructor_arguments["selector"].window_seconds, 5.0)
        self.assertIs(constructor_arguments["stt_model"], self.stt_model)

        processing_input = self.pipeline_mock.process.call_args.args[0]
        self.assertEqual(processing_input.source_video_path.name, STORED_FILENAME)
        self.assertEqual(processing_input.output_directory.name, "api")
        self.assertFalse(processing_input.keep_intermediate_audio)

        body = response.json()
        self.assertEqual(body["video_id"], STORED_VIDEO_ID)
        self.assertEqual(body["status"], "COMPLETED")
        self.assertEqual(body["memos"][0]["selection"]["strategy_name"], "fixed_window")
        self.assertEqual(body["memos"][0]["rendered_clip"]["clip_id"], "b" * 32)
        self.assertEqual(body["memos"][0]["rendered_clip"]["filename"], f"{'b' * 32}.mp4")
        self.assertEqual(
            body["memos"][0]["rendered_clip"]["download_url"],
            f"/videos/clips/{'c' * 32}/{'b' * 32}",
        )
        serialized = response.text
        for local_prefix in ("/Users/", "/home/", "C:\\\\"):
            self.assertNotIn(local_prefix, serialized)

    def test_all_supported_windows_are_accepted(self) -> None:
        for window in (5.0, 10.0, 15.0, 30.0):
            with self.subTest(window=window):
                self.pipeline_class_mock.reset_mock()
                response = self._post(window=str(window))
                self.assertEqual(response.status_code, 200)
                selector = self.pipeline_class_mock.call_args.kwargs["selector"]
                self.assertEqual(selector.window_seconds, window)

    def test_invalid_windows_return_422_before_upload(self) -> None:
        for window in ("0", "-5", "7", "nan", "inf", "true"):
            with self.subTest(window=window):
                self.save_mock.reset_mock()
                response = self._post(window=window)
                self.assertEqual(response.status_code, 422)
                self.save_mock.assert_not_called()

    def test_window_is_required(self) -> None:
        response = self.client.post(
            "/videos/process",
            files={"file": ("eval.mov", MOV_CONTENT, "video/quicktime")},
        )

        self.assertEqual(response.status_code, 422)
        self.save_mock.assert_not_called()

    def test_video_validation_error_returns_415(self) -> None:
        self.save_mock.side_effect = VideoValidationError("invalid video")

        response = self._post(window="5")

        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.json()["detail"], "invalid video")
        self.pipeline_class_mock.assert_not_called()

    def test_no_edit_memo_is_http_200(self) -> None:
        self.pipeline_mock.process.return_value = self._result(
            status=PipelineStatus.NO_EDIT_MEMO,
            memo_results=(),
        )

        response = self._post(window="5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "NO_EDIT_MEMO")
        self.assertEqual(response.json()["memos"], [])

    def test_no_scene_selected_is_http_200(self) -> None:
        self.pipeline_mock.process.return_value = self._result(
            status=PipelineStatus.NO_SCENE_SELECTED,
            memo_results=(self._memo_result(candidate=None),),
        )

        response = self._post(window="5")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "NO_SCENE_SELECTED")
        self.assertIsNone(body["memos"][0]["selection"]["candidate"])
        self.assertIsNone(body["memos"][0]["rendered_clip"])

    def test_stt_failure_returns_safe_500(self) -> None:
        self.pipeline_mock.process.side_effect = self._pipeline_error(PipelineStage.STT)

        response = self._post(window="5")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"],
            {
                "code": "PIPELINE_STT_FAILED",
                "stage": "stt",
                "message": "Video processing failed during stt.",
            },
        )
        self.assertNotIn("secret raw cause", response.text)

    def test_source_and_media_probe_failures_return_422(self) -> None:
        for stage in (PipelineStage.SOURCE_VALIDATION, PipelineStage.MEDIA_PROBE):
            with self.subTest(stage=stage):
                self.pipeline_mock.process.side_effect = self._pipeline_error(stage)
                response = self._post(window="5")
                self.assertEqual(response.status_code, 422)
                self.assertEqual(response.json()["detail"]["stage"], stage.value)

    def test_candidate_selection_failure_returns_500_without_fallback(self) -> None:
        self.pipeline_mock.process.side_effect = self._pipeline_error(
            PipelineStage.CANDIDATE_SELECTION
        )

        response = self._post(window="5")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(
            response.json()["detail"]["code"],
            "PIPELINE_CANDIDATE_SELECTION_FAILED",
        )
        self.pipeline_mock.process.assert_called_once()

    def test_clip_rendering_failure_returns_500(self) -> None:
        self.pipeline_mock.process.side_effect = self._pipeline_error(
            PipelineStage.CLIP_RENDERING
        )

        response = self._post(window="5")

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.json()["detail"]["stage"], "clip_rendering")

    def test_model_is_reused_across_requests(self) -> None:
        first = self._post(window="5")
        second = self._post(window="10")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.load_model_mock.assert_called_once_with()
        self.assertEqual(self.pipeline_class_mock.call_count, 2)
        for constructor_call in self.pipeline_class_mock.call_args_list:
            self.assertIs(constructor_call.kwargs["stt_model"], self.stt_model)

    def test_process_uses_application_semaphore(self) -> None:
        semaphore = _TrackingSemaphore()
        app.state.pipeline_semaphore = semaphore

        response = self._post(window="5")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(semaphore.enter_count, 1)
        self.assertEqual(semaphore.exit_count, 1)

    def _post(self, *, window: str):
        return self.client.post(
            "/videos/process",
            files={"file": ("eval.mov", MOV_CONTENT, "video/quicktime")},
            data={"window_seconds": window},
        )

    @staticmethod
    def _pipeline_error(stage: PipelineStage) -> PipelineExecutionError:
        error = PipelineExecutionError(
            stage=stage,
            cause_type="SensitiveInternalError",
            safe_message=f"Video processing failed during {stage.value}.",
        )
        error.__cause__ = RuntimeError("secret raw cause")
        return error

    def _completed_result(self) -> VideoProcessingResult:
        return self._result(
            status=PipelineStatus.COMPLETED,
            memo_results=(self._memo_result(candidate=SceneCandidate(5.0, 10.8, 15.8)),),
        )

    def _result(
        self,
        *,
        status: PipelineStatus,
        memo_results: tuple[MemoProcessingResult, ...],
    ) -> VideoProcessingResult:
        return VideoProcessingResult(
            status=status,
            source_path=Path("/Users/private/source.mov"),
            media_info=MediaInfo(20.95, True, True, "hevc", "aac", "mov,mp4"),
            extracted_audio=None,
            transcript=STTResult(
                text="AI야 방금 장면 꼭 살려줘",
                segments=(
                    TranscriptSegment(15.8, 18.72, "AI야 방금 장면 꼭 살려줘"),
                ),
                language="ko",
                language_probability=1.0,
            ),
            memo_results=memo_results,
            timings=(PipelineStageTiming(PipelineStage.TOTAL, 1.5),),
            warnings=(),
        )

    def _memo_result(
        self, *, candidate: SceneCandidate | None
    ) -> MemoProcessingResult:
        memo = EditMemo(
            start_seconds=15.8,
            end_seconds=18.72,
            transcript_text="AI야 방금 장면 꼭 살려줘",
            matched_trigger="AI야",
            matched_reference="방금",
            matched_action="살려줘",
        )
        generated = (
            SceneCandidate(5.0, 10.8, 15.8),
            SceneCandidate(10.0, 5.8, 15.8),
        )
        selection = SceneSelectionResult(
            strategy_name="fixed_window",
            candidate=candidate,
            selected_source_id=None if candidate is None else "window:5.0",
            reasoning_code=(
                "NO_SELECTION" if candidate is None else "FIXED_WINDOW_SELECTED"
            ),
            reasoning_summary=None,
        )
        clip = None
        if candidate is not None:
            clip = RenderedClip(
                source_path=Path("/Users/private/source.mov"),
                clip_path=(
                    PROCESS_OUTPUT_DIRECTORY
                    / ("c" * 32)
                    / "clips"
                    / f"{'b' * 32}.mp4"
                ),
                start_seconds=candidate.start_seconds,
                end_seconds=candidate.end_seconds,
                duration_seconds=candidate.end_seconds - candidate.start_seconds,
                video_codec="h264",
                audio_codec="aac",
            )
        return MemoProcessingResult(
            memo=memo,
            generated_candidates=generated,
            selection=selection,
            rendered_clip=clip,
        )
