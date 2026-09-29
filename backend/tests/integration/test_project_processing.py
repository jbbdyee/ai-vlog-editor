from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import sleep
from unittest import TestCase, skipUnless

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EditMemo,
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    ProjectStatus,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.project_processing import (
    ProjectSourceOutcome,
    process_project,
)
from backend.app.services.source_processing import (
    SourceProcessingResult,
    SourceStageExecutionError,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class ProjectProcessingIntegrationTests(TestCase):
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
        with self.factory() as session:
            project = Project(
                name="Project runner PostgreSQL",
                split_policy=EpisodeSplitPolicy.SINGLE,
            )
            session.add(project)
            session.commit()
            self.project_id = project.id

    def tearDown(self) -> None:
        with self.factory() as session:
            source_ids = select(SourceVideo.id).where(
                SourceVideo.project_id == self.project_id
            )
            session.execute(
                delete(EditMemo).where(EditMemo.source_video_id.in_(source_ids))
            )
            session.execute(
                delete(Transcript).where(Transcript.source_video_id.in_(source_ids))
            )
            session.execute(
                delete(ProcessingStage).where(
                    ProcessingStage.source_video_id.in_(source_ids)
                )
            )
            session.execute(
                delete(SourceVideo).where(SourceVideo.project_id == self.project_id)
            )
            session.execute(delete(Project).where(Project.id == self.project_id))
            session.commit()
        self.temporary_directory.cleanup()

    def test_restart_selection_reuses_completed_blocks_running_and_processes_ready(self) -> None:
        ready_a, completed, failed, running, ready_b = self._sources(5)
        with self.factory() as session:
            self._mark_completed(session, completed)
            self._mark_failed(session, failed)
            source = session.get(SourceVideo, running)
            source.processing_status = SourceVideoStatus.PROCESSING
            stage = self._stages(session, running)[ProcessingStageKind.STT]
            stage.status = ProcessingStageStatus.RUNNING
            stage.started_at = datetime.now(timezone.utc)
            session.commit()
        calls: list = []

        result = self._run(self._processor(calls=calls), max_concurrency=2)

        self.assertEqual(calls, [ready_a, ready_b])
        self.assertEqual(result.summary.completed_count, 3)
        self.assertEqual(result.summary.reused_count, 1)
        self.assertEqual(result.summary.failed_count, 1)
        self.assertEqual(result.summary.blocked_count, 1)
        self.assertEqual(result.project_status, ProjectStatus.PROCESSING)
        with self.factory() as session:
            self.assertEqual(
                session.get(SourceVideo, running).processing_status,
                SourceVideoStatus.PROCESSING,
            )
            self.assertEqual(
                self._stages(session, running)[ProcessingStageKind.STT].status,
                ProcessingStageStatus.RUNNING,
            )

    def test_ten_sources_preserve_partial_failure_and_continue(self) -> None:
        source_ids = self._sources(10)
        calls: list = []

        result = self._run(
            self._processor(calls=calls, fail_source_id=source_ids[4]),
            max_concurrency=1,
        )

        self.assertEqual(calls, list(source_ids))
        self.assertEqual(result.summary.processed_count, 10)
        self.assertEqual(result.summary.completed_count, 9)
        self.assertEqual(result.summary.failed_count, 1)
        self.assertEqual(result.project_status, ProjectStatus.COMPLETED_WITH_WARNINGS)
        self.assertEqual(result.sources[4].outcome, ProjectSourceOutcome.FAILED)
        self.assertEqual(result.sources[-1].outcome, ProjectSourceOutcome.PROCESSED)

    def test_120_sources_are_bounded_durable_and_reused_on_second_run(self) -> None:
        source_ids = self._sources(120)
        active = 0
        peak = 0
        lock = Lock()

        def processor(*, session: Session, source_video_id, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            sleep(0.002)
            try:
                return self._mark_completed(session, source_video_id)
            finally:
                with lock:
                    active -= 1

        first = self._run(processor, max_concurrency=2)
        rerun_calls: list = []
        second = self._run(self._processor(calls=rerun_calls), max_concurrency=2)

        self.assertEqual(first.summary.total_sources, 120)
        self.assertEqual(first.summary.completed_count, 120)
        self.assertLessEqual(peak, 2)
        self.assertGreater(peak, 1)
        self.assertEqual(second.summary.reused_count, 120)
        self.assertEqual(second.summary.processed_count, 0)
        self.assertEqual(rerun_calls, [])
        with self.factory() as session:
            self.assertEqual(
                session.scalar(
                    select(Project.status).where(Project.id == self.project_id)
                ),
                ProjectStatus.COMPLETED,
            )
            self.assertEqual(
                len(
                    session.scalars(
                        select(SourceVideo.id).where(
                            SourceVideo.project_id == self.project_id,
                            SourceVideo.processing_status
                            == SourceVideoStatus.COMPLETED,
                        )
                    ).all()
                ),
                len(source_ids),
            )

    def _run(self, processor, *, max_concurrency):
        return process_project(
            session_factory=self.factory,
            storage=self.storage,
            workspace=self.workspace,
            project_id=self.project_id,
            max_concurrency=max_concurrency,
            source_processor=processor,
        )

    def _sources(self, count: int):
        with self.factory() as session:
            created = datetime.now(timezone.utc)
            sources = []
            for index in range(count):
                source = SourceVideo(
                    project_id=self.project_id,
                    original_filename=f"source-{index}.mp4",
                    storage_reference=(
                        f"projects/{self.project_id.hex}/sources/{index}.mp4"
                    ),
                    fingerprint=f"postgres-fingerprint-{index}",
                    fingerprint_algorithm="sha256",
                    processing_status=SourceVideoStatus.READY,
                    created_at=created + timedelta(microseconds=index),
                    processing_stages=[
                        ProcessingStage(
                            stage=stage, status=ProcessingStageStatus.PENDING
                        )
                        for stage in ProcessingStageKind
                    ],
                )
                session.add(source)
                sources.append(source)
            session.commit()
            return tuple(source.id for source in sources)

    def _processor(self, *, calls=None, fail_source_id=None):
        def processor(*, session: Session, source_video_id, **_kwargs):
            if calls is not None:
                calls.append(source_video_id)
            if source_video_id == fail_source_id:
                self._mark_failed(session, source_video_id)
                raise SourceStageExecutionError(
                    stage=ProcessingStageKind.PROBE,
                    safe_error_code="PROBE_FAILED",
                    safe_message="PROBE processing failed.",
                    warnings=[],
                )
            return self._mark_completed(session, source_video_id)

        return processor

    def _mark_completed(self, session: Session, source_id):
        source = session.get(SourceVideo, source_id)
        source.duration_seconds = 1.0
        source.video_codec = "h264"
        source.audio_codec = "aac"
        source.format_name = "mov,mp4"
        source.processing_status = SourceVideoStatus.COMPLETED
        for stage in self._stages(session, source_id).values():
            stage.status = ProcessingStageStatus.COMPLETED
            stage.input_fingerprint = source.fingerprint
        if source.transcript is None:
            source.transcript = Transcript(
                text="test", language="ko", language_probability=1.0, segments=[]
            )
        session.commit()
        return SourceProcessingResult(
            source_video_id=source.id,
            processing_status=SourceVideoStatus.COMPLETED,
            completed_stages=tuple(ProcessingStageKind),
            transcript_id=source.transcript.id,
            memo_count=0,
            warnings=(),
        )

    def _mark_failed(self, session: Session, source_id) -> None:
        source = session.get(SourceVideo, source_id)
        stage = self._stages(session, source_id)[ProcessingStageKind.PROBE]
        source.processing_status = SourceVideoStatus.FAILED
        stage.status = ProcessingStageStatus.FAILED
        stage.safe_error_code = "PROBE_FAILED"
        session.commit()

    @staticmethod
    def _stages(session: Session, source_id):
        return {
            stage.stage: stage
            for stage in session.scalars(
                select(ProcessingStage).where(
                    ProcessingStage.source_video_id == source_id
                )
            ).all()
        }
