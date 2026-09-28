import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless

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
    process_source,
)
from backend.app.services.stt_service import STTResult, TranscriptSegment, TranscriptWord
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
        services = SourceProcessingServices(
            probe=lambda _path: MediaInfo(
                21.25, True, True, "hevc", "aac", "mov,mp4"
            ),
            extract=self._extract_audio,
            transcribe=lambda _path, **_kwargs: _transcript_result(),
            detect_memos=lambda _result: (_memo(),),
        )

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

    def _extract_audio(self, source_path: Path, output_directory: Path) -> ExtractedAudio:
        output_directory.mkdir(parents=True, exist_ok=True)
        audio_path = output_directory / "integration.wav"
        audio_path.write_bytes(b"RIFF-integration")
        return ExtractedAudio(source_path, audio_path, 21.25, 16_000, 1, "pcm_s16le")


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
