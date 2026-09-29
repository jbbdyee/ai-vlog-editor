import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import Mock

from sqlalchemy import delete, select

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
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
from backend.app.services.media_probe import MediaInfo
from backend.app.services.memo_detector import EditMemo
from backend.app.services.source_processing import (
    SourceProcessingServices,
    SourceProcessingStateError,
    SourceStageExecutionError,
    process_source,
    reprocess_source_from,
    resume_source,
    retry_source_stage,
)
from backend.app.services.source_processing_state import (
    determine_resume_plan,
    recover_stale_running_stage,
)
from backend.app.services.stt_service import (
    STTError,
    STTResult,
    TranscriptSegment,
    TranscriptWord,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class SourceProcessingIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.storage = LocalSourceStorage(self.root / "originals")
        self.workspace = LocalProcessingWorkspace(self.root / "temporary")
        self.session = self.factory()
        project = Project(
            name="Source Processing PostgreSQL",
            split_policy=EpisodeSplitPolicy.SINGLE,
        )
        self.session.add(project)
        self.session.commit()
        stored = self.storage.store(
            project_id=project.id,
            file_object=_video_stream(),
            original_filename="integration.mp4",
            content_type="video/mp4",
        )
        source = SourceVideo(
            project=project,
            original_filename=stored.original_filename,
            storage_reference=stored.resource_reference,
            fingerprint=stored.fingerprint,
            fingerprint_algorithm=stored.fingerprint_algorithm,
            processing_status=SourceVideoStatus.READY,
            processing_stages=[
                ProcessingStage(
                    stage=stage, status=ProcessingStageStatus.PENDING
                )
                for stage in ProcessingStageKind
            ],
        )
        self.session.add(source)
        self.session.commit()
        self.project_id = project.id
        self.source_id = source.id

    def tearDown(self) -> None:
        self.session.rollback()
        self.session.execute(
            delete(EditMemoRecord).where(
                EditMemoRecord.source_video_id == self.source_id
            )
        )
        self.session.execute(
            delete(Transcript).where(Transcript.source_video_id == self.source_id)
        )
        self.session.execute(
            delete(ProcessingStage).where(
                ProcessingStage.source_video_id == self.source_id
            )
        )
        self.session.execute(
            delete(SourceVideo).where(SourceVideo.id == self.source_id)
        )
        self.session.execute(delete(Project).where(Project.id == self.project_id))
        self.session.commit()
        self.session.close()
        self.temporary_directory.cleanup()

    def test_stage_and_analysis_results_are_durable_in_postgresql(self) -> None:
        services = self._services()

        result = process_source(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            stt_model=object(),
            services=services,
        )
        self.session.close()
        self.session = self.factory()

        source = self.session.get(SourceVideo, self.source_id)
        stages = self.session.scalars(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == self.source_id
            )
        ).all()
        transcript = self.session.scalar(
            select(Transcript).where(Transcript.source_video_id == self.source_id)
        )
        memos = self.session.scalars(
            select(EditMemoRecord).where(
                EditMemoRecord.source_video_id == self.source_id
            )
        ).all()

        self.assertEqual(result.processing_status, SourceVideoStatus.COMPLETED)
        self.assertEqual(source.processing_status, SourceVideoStatus.COMPLETED)
        self.assertEqual(float(source.duration_seconds), 21.25)
        self.assertEqual({stage.status for stage in stages}, {ProcessingStageStatus.COMPLETED})
        self.assertEqual({stage.attempt_count for stage in stages}, {1})
        self.assertEqual({stage.input_fingerprint for stage in stages}, {source.fingerprint})
        self.assertIsNotNone(transcript)
        self.assertEqual(transcript.segments[0]["words"][0]["text"], "에이아이아")
        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].transcript_id, transcript.id)
        self.assertEqual(list((self.root / "temporary").rglob("*.wav")), [])
        self.assertTrue(self.storage.resolve(source.storage_reference).is_file())

    def test_restart_plan_retry_and_completed_duplicate_guard(self) -> None:
        failing_services = self._services()
        failing_services.transcribe.side_effect = STTError("simulated crash failure")
        with self.assertRaises(SourceStageExecutionError):
            process_source(
                session=self.session,
                storage=self.storage,
                workspace=self.workspace,
                source_video_id=self.source_id,
                services=failing_services,
            )
        self._restart_session()

        plan = determine_resume_plan(
            session=self.session, source_video_id=self.source_id
        )
        self.assertEqual(plan.start_stage, ProcessingStageKind.AUDIO_EXTRACTION)
        self.assertIn(ProcessingStageKind.STT, plan.invalid_stages)

        retry_services = self._services()
        completed = retry_source_stage(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            stage_kind=ProcessingStageKind.STT,
            services=retry_services,
        )
        self.assertEqual(completed.processing_status, SourceVideoStatus.COMPLETED)
        self._restart_session()

        duplicate_guard_services = self._services()
        resumed = resume_source(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            services=duplicate_guard_services,
        )
        self.assertEqual(resumed.processing_status, SourceVideoStatus.COMPLETED)
        duplicate_guard_services.probe.assert_not_called()
        duplicate_guard_services.extract.assert_not_called()
        duplicate_guard_services.transcribe.assert_not_called()
        duplicate_guard_services.detect_memos.assert_not_called()

    def test_reprocess_from_stt_replaces_persisted_results(self) -> None:
        first = process_source(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            services=self._services(),
        )
        old_transcript_id = first.transcript_id
        self._restart_session()

        second = reprocess_source_from(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            from_stage=ProcessingStageKind.STT,
            services=self._services(),
        )
        self._restart_session()

        transcripts = self.session.scalars(
            select(Transcript).where(Transcript.source_video_id == self.source_id)
        ).all()
        memos = self.session.scalars(
            select(EditMemoRecord).where(
                EditMemoRecord.source_video_id == self.source_id
            )
        ).all()
        self.assertNotEqual(second.transcript_id, old_transcript_id)
        self.assertEqual(len(transcripts), 1)
        self.assertEqual(len(memos), 1)
        self.assertEqual(memos[0].transcript_id, second.transcript_id)

    def test_crash_restart_stale_recovery_is_persisted_before_retry(self) -> None:
        source = self.session.get(SourceVideo, self.source_id)
        stages = {
            stage.stage: stage
            for stage in self.session.scalars(
                select(ProcessingStage).where(
                    ProcessingStage.source_video_id == self.source_id
                )
            ).all()
        }
        source.duration_seconds = 21.25
        source.video_codec = "hevc"
        source.audio_codec = "aac"
        source.format_name = "mov,mp4"
        for kind in (ProcessingStageKind.PROBE, ProcessingStageKind.AUDIO_EXTRACTION):
            stages[kind].status = ProcessingStageStatus.COMPLETED
            stages[kind].attempt_count = 1
            stages[kind].input_fingerprint = source.fingerprint
        stages[ProcessingStageKind.STT].status = ProcessingStageStatus.RUNNING
        stages[ProcessingStageKind.STT].attempt_count = 1
        stages[ProcessingStageKind.STT].started_at = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        )
        stages[ProcessingStageKind.STT].input_fingerprint = source.fingerprint
        source.processing_status = SourceVideoStatus.PROCESSING
        self.session.commit()
        self._restart_session()

        with self.assertRaises(SourceProcessingStateError):
            resume_source(
                session=self.session,
                storage=self.storage,
                workspace=self.workspace,
                source_video_id=self.source_id,
                services=self._services(),
            )
        recover_stale_running_stage(
            session=self.session,
            source_video_id=self.source_id,
            stage_kind=ProcessingStageKind.STT,
            stale_before=datetime.now(timezone.utc) - timedelta(hours=1),
        )
        self._restart_session()
        recovered = self.session.scalar(
            select(ProcessingStage).where(
                ProcessingStage.source_video_id == self.source_id,
                ProcessingStage.stage == ProcessingStageKind.STT,
            )
        )
        self.assertEqual(recovered.status, ProcessingStageStatus.FAILED)
        self.assertEqual(recovered.safe_error_code, "STALE_EXECUTION_RECOVERED")

        result = retry_source_stage(
            session=self.session,
            storage=self.storage,
            workspace=self.workspace,
            source_video_id=self.source_id,
            stage_kind=ProcessingStageKind.STT,
            services=self._services(),
        )
        self.assertEqual(result.processing_status, SourceVideoStatus.COMPLETED)

    def _extract_audio(self, source_path: Path, output_directory: Path) -> ExtractedAudio:
        output_directory.mkdir(parents=True, exist_ok=True)
        audio_path = output_directory / "integration.wav"
        audio_path.write_bytes(b"RIFF-integration")
        return ExtractedAudio(source_path, audio_path, 21.25, 16_000, 1, "pcm_s16le")

    def _services(self) -> SourceProcessingServices:
        return SourceProcessingServices(
            probe=Mock(
                return_value=MediaInfo(
                    21.25, True, True, "hevc", "aac", "mov,mp4"
                )
            ),
            extract=Mock(side_effect=self._extract_audio),
            transcribe=Mock(return_value=_transcript_result()),
            detect_memos=Mock(return_value=(_memo(),)),
        )

    def _restart_session(self) -> None:
        self.session.close()
        self.session = self.factory()


def _video_stream():
    from io import BytesIO

    return BytesIO(b"\x00\x00\x00\x18ftypisompostgres-processing")


def _transcript_result() -> STTResult:
    return STTResult(
        text="에이아이아 지금 장면 꼭 살려줘",
        segments=(
            TranscriptSegment(
                15.8,
                18.72,
                "에이아이아 지금 장면 꼭 살려줘",
                (TranscriptWord(15.8, 16.56, "에이아이아", 0.91),),
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
