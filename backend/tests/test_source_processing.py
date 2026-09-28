from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import (
    EditMemo as EditMemoRecord,
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.audio_extractor import ExtractedAudio
from backend.app.services.media_probe import MediaInfo, MediaProbeError
from backend.app.services.memo_detector import EditMemo, MemoDetectionError
from backend.app.services.source_processing import (
    SourceProcessingServices,
    SourceProcessingStateError,
    SourceStageExecutionError,
    process_source,
)
from backend.app.services.stt_service import (
    STTError,
    STTResult,
    TranscriptSegment,
    TranscriptWord,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


class SourceProcessingTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.session = self.factory()
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.storage = LocalSourceStorage(self.root / "originals")
        self.workspace = LocalProcessingWorkspace(self.root / "temporary")
        self.source = self._create_source()
        self.stt_model = object()
        self.events: list[str] = []
        self.services = self._happy_services()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_happy_path_persists_results_transitions_and_cleans_temporary_audio(self) -> None:
        original_path = self.storage.resolve(self.source.storage_reference)
        with patch.object(
            self.session, "commit", wraps=self.session.commit
        ) as commit:
            result = self._process()

        self.assertEqual(
            self.events, ["probe", "extract", "transcribe", "detect"]
        )
        self.assertEqual(commit.call_count, 8)
        self.assertEqual(result.processing_status, SourceVideoStatus.COMPLETED)
        self.assertEqual(result.completed_stages, tuple(ProcessingStageKind))
        self.assertEqual(result.memo_count, 1)
        self.assertEqual(result.warnings, ())
        self.assertNotIn(str(self.root), repr(result))

        self.session.refresh(self.source)
        self.assertEqual(float(self.source.duration_seconds), 21.25)
        self.assertEqual(self.source.video_codec, "hevc")
        self.assertEqual(self.source.audio_codec, "aac")
        self.assertEqual(self.source.format_name, "mov,mp4")
        self.assertEqual(self.source.processing_status, SourceVideoStatus.COMPLETED)
        self.assertTrue(original_path.is_file())
        self.assertEqual(list((self.root / "temporary").rglob("*.wav")), [])
        self.assertFalse(
            (
                self.root
                / "temporary"
                / "projects"
                / self.source.project_id.hex
                / "sources"
                / self.source.id.hex
            ).exists()
        )

        transcript = self.session.scalar(
            select(Transcript).where(Transcript.source_video_id == self.source.id)
        )
        memos = self.session.scalars(
            select(EditMemoRecord).where(
                EditMemoRecord.source_video_id == self.source.id
            )
        ).all()
        self.assertIsNotNone(transcript)
        self.assertEqual(transcript.text, "에이아이아 지금 장면 꼭 살려줘")
        self.assertEqual(transcript.language, "ko")
        self.assertEqual(float(transcript.language_probability), 0.98)
        self.assertEqual(transcript.segments[0]["start_seconds"], 15.8)
        self.assertEqual(transcript.segments[0]["words"][0]["text"], "에이아이아")
        self.assertEqual(transcript.segments[0]["words"][0]["probability"], 0.91)
        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].transcript_id, transcript.id)
        self.assertEqual(memos[0].matched_action, "살려줘")
        self.services.transcribe.assert_called_once_with(
            self._audio_path(), model=self.stt_model, word_timestamps=True
        )
        self._assert_all_stage_inputs_match_source()

    def test_probe_failure_is_persisted_and_blocks_downstream(self) -> None:
        self.services.probe.side_effect = MediaProbeError(
            "unsafe absolute path C:\\private\\source.mov"
        )

        error = self._assert_stage_failure(ProcessingStageKind.PROBE)

        self.assertEqual(error.safe_error_code, "PROBE_FAILED")
        self.assertNotIn("private", error.safe_message)
        self.services.extract.assert_not_called()
        self.services.transcribe.assert_not_called()
        self.services.detect_memos.assert_not_called()

    def test_audio_failure_blocks_stt_and_memo(self) -> None:
        self.services.extract.side_effect = RuntimeError("unsafe ffmpeg detail")

        self._assert_stage_failure(ProcessingStageKind.AUDIO_EXTRACTION)

        self.services.transcribe.assert_not_called()
        self.services.detect_memos.assert_not_called()
        self.assertIsNone(self.source.transcript)

    def test_stt_failure_persists_no_transcript_and_blocks_memo(self) -> None:
        self.services.transcribe.side_effect = STTError("unsafe model detail")

        self._assert_stage_failure(ProcessingStageKind.STT)

        self.services.detect_memos.assert_not_called()
        self.assertIsNone(
            self.session.scalar(
                select(Transcript).where(Transcript.source_video_id == self.source.id)
            )
        )

    def test_memo_failure_keeps_durable_transcript(self) -> None:
        self.services.detect_memos.side_effect = MemoDetectionError(
            "unsafe transcript detail"
        )

        self._assert_stage_failure(ProcessingStageKind.MEMO_DETECTION)

        transcript = self.session.scalar(
            select(Transcript).where(Transcript.source_video_id == self.source.id)
        )
        self.assertIsNotNone(transcript)
        self.assertEqual(transcript.text, "에이아이아 지금 장면 꼭 살려줘")
        self.assertEqual(
            self.session.scalars(
                select(EditMemoRecord).where(
                    EditMemoRecord.source_video_id == self.source.id
                )
            ).all(),
            [],
        )

    def test_zero_memos_is_a_completed_result(self) -> None:
        self.services.detect_memos.side_effect = lambda _result: (
            self.events.append("detect") or ()
        )

        result = self._process()

        self.assertEqual(result.processing_status, SourceVideoStatus.COMPLETED)
        self.assertEqual(result.memo_count, 0)
        self.assertEqual(
            self.session.scalars(select(EditMemoRecord)).all(), []
        )

    def test_invalid_stage_state_is_rejected_before_any_service_runs(self) -> None:
        probe_stage = self._stage(ProcessingStageKind.PROBE)
        probe_stage.status = ProcessingStageStatus.COMPLETED
        self.session.commit()

        with self.assertRaises(SourceProcessingStateError):
            self._process()

        self.services.probe.assert_not_called()
        self.services.extract.assert_not_called()
        self.services.transcribe.assert_not_called()
        self.services.detect_memos.assert_not_called()
        self.assertEqual(self.source.processing_status, SourceVideoStatus.READY)

    def test_cleanup_failure_is_returned_as_safe_warning_and_original_remains(self) -> None:
        original_path = self.storage.resolve(self.source.storage_reference)
        with patch.object(
            self.workspace,
            "cleanup_source",
            side_effect=OSError("unsafe local path"),
        ):
            result = self._process()

        self.assertEqual(result.processing_status, SourceVideoStatus.COMPLETED)
        self.assertEqual(
            result.warnings,
            ("Could not remove the source temporary workspace.",),
        )
        self.assertTrue(original_path.is_file())

    def _create_source(self) -> SourceVideo:
        project = Project(
            name="Source Processing Unit",
            split_policy=EpisodeSplitPolicy.SINGLE,
        )
        self.session.add(project)
        self.session.commit()
        stored = self.storage.store(
            project_id=project.id,
            file_object=_video_stream(),
            original_filename="source.mp4",
            content_type="video/mp4",
        )
        source = SourceVideo(
            project=project,
            original_filename=stored.original_filename,
            storage_reference=stored.resource_reference,
            fingerprint=stored.fingerprint,
            fingerprint_algorithm=stored.fingerprint_algorithm,
            processing_status=SourceVideoStatus.READY,
        )
        source.processing_stages = [
            ProcessingStage(
                stage=stage, status=ProcessingStageStatus.PENDING
            )
            for stage in ProcessingStageKind
        ]
        self.session.add(source)
        self.session.commit()
        return source

    def _happy_services(self) -> SourceProcessingServices:
        probe = Mock(return_value=MediaInfo(21.25, True, True, "hevc", "aac", "mov,mp4"))
        extract = Mock(side_effect=self._extract_audio)
        transcribe = Mock(return_value=_transcript_result())
        detect = Mock(return_value=(_memo(),))
        for event_name, service in (
            ("probe", probe),
            ("extract", extract),
            ("transcribe", transcribe),
            ("detect", detect),
        ):
            original_side_effect = service.side_effect
            original_return_value = service.return_value

            def record(*args, _name=event_name, _side_effect=original_side_effect, _return=original_return_value, **kwargs):
                self.events.append(_name)
                stage = {
                    "probe": ProcessingStageKind.PROBE,
                    "extract": ProcessingStageKind.AUDIO_EXTRACTION,
                    "transcribe": ProcessingStageKind.STT,
                    "detect": ProcessingStageKind.MEMO_DETECTION,
                }[_name]
                self.assertEqual(
                    self._stage(stage).status, ProcessingStageStatus.RUNNING
                )
                return _side_effect(*args, **kwargs) if _side_effect else _return

            service.side_effect = record
        return SourceProcessingServices(probe, extract, transcribe, detect)

    def _extract_audio(self, source_path: Path, output_directory: Path) -> ExtractedAudio:
        output_directory.mkdir(parents=True, exist_ok=True)
        self._audio_path().write_bytes(b"RIFF-audio")
        return ExtractedAudio(source_path, self._audio_path(), 21.25, 16_000, 1, "pcm_s16le")

    def _audio_path(self) -> Path:
        return (
            self.root
            / "temporary"
            / "projects"
            / self.source.project_id.hex
            / "sources"
            / self.source.id.hex
            / "audio"
            / "source.wav"
        )

    def _process(self):
        return process_source(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source.id,
            stt_model=self.stt_model,
            services=self.services,
        )

    def _assert_stage_failure(
        self, expected_stage: ProcessingStageKind
    ) -> SourceStageExecutionError:
        with self.assertRaises(SourceStageExecutionError) as raised:
            self._process()
        self.session.refresh(self.source)
        failed_stage = self._stage(expected_stage)
        self.assertEqual(failed_stage.status, ProcessingStageStatus.FAILED)
        self.assertEqual(failed_stage.safe_error_code, f"{expected_stage.value}_FAILED")
        self.assertEqual(
            failed_stage.safe_error_message,
            f"{expected_stage.value} processing failed.",
        )
        self.assertIsNotNone(failed_stage.started_at)
        self.assertIsNotNone(failed_stage.completed_at)
        self.assertEqual(self.source.processing_status, SourceVideoStatus.FAILED)
        for stage in ProcessingStageKind:
            if tuple(ProcessingStageKind).index(stage) > tuple(ProcessingStageKind).index(expected_stage):
                self.assertEqual(self._stage(stage).status, ProcessingStageStatus.PENDING)
        return raised.exception

    def _stage(self, kind: ProcessingStageKind) -> ProcessingStage:
        return self.session.scalar(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == self.source.id,
                ProcessingStage.stage == kind,
            )
        )

    def _assert_all_stage_inputs_match_source(self) -> None:
        stages = self.session.scalars(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == self.source.id
            )
        ).all()
        self.assertEqual({stage.status for stage in stages}, {ProcessingStageStatus.COMPLETED})
        self.assertEqual({stage.attempt_count for stage in stages}, {1})
        self.assertEqual({stage.input_fingerprint for stage in stages}, {self.source.fingerprint})


def _video_stream():
    from io import BytesIO

    return BytesIO(b"\x00\x00\x00\x18ftypisomsource-processing")


def _transcript_result() -> STTResult:
    return STTResult(
        text="에이아이아 지금 장면 꼭 살려줘",
        segments=(
            TranscriptSegment(
                start_seconds=15.8,
                end_seconds=18.72,
                text="에이아이아 지금 장면 꼭 살려줘",
                words=(
                    TranscriptWord(15.8, 16.56, "에이아이아", 0.91),
                    TranscriptWord(16.56, 16.94, "지금", 0.95),
                    TranscriptWord(16.94, 17.96, "장면", 0.94),
                    TranscriptWord(17.96, 18.16, "꼭", 0.92),
                    TranscriptWord(18.16, 18.72, "살려줘", 0.96),
                ),
            ),
        ),
        language="ko",
        language_probability=0.98,
    )


def _memo() -> EditMemo:
    return EditMemo(
        start_seconds=15.8,
        end_seconds=18.72,
        transcript_text="에이아이아 지금 장면 꼭 살려줘",
        matched_trigger="에이아이아",
        matched_reference="지금",
        matched_action="살려줘",
        trigger_match_type="similarity",
        trigger_similarity=0.8,
    )
