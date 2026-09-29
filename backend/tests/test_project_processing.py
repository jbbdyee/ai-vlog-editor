from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock
from time import sleep
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from backend.app.database import Base
from backend.app.models import (
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
    ProjectNotFoundError,
    ProjectSourceOutcome,
    process_project,
)
from backend.app.services.source_processing import (
    SourceProcessingResult,
    SourceProcessingStateError,
    SourceStageExecutionError,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace
from backend.app.storage.source_storage import LocalSourceStorage


class ProjectProcessingTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.engine = create_engine(
            f"sqlite+pysqlite:///{self.root / 'project-processing.db'}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.storage = LocalSourceStorage(self.root / "originals")
        self.workspace = LocalProcessingWorkspace(self.root / "temporary")
        with self.factory() as session:
            project = Project(
                name="Project runner", split_policy=EpisodeSplitPolicy.SINGLE
            )
            session.add(project)
            session.commit()
            self.project_id = project.id

    def tearDown(self) -> None:
        self.engine.dispose()
        self.temporary_directory.cleanup()

    def test_missing_and_empty_project_semantics(self) -> None:
        with self.assertRaises(ProjectNotFoundError):
            process_project(
                session_factory=self.factory,
                storage=self.storage,
                workspace=self.workspace,
                project_id=uuid4(),
            )

        result = self._run(self._processor())

        self.assertEqual(result.project_status, ProjectStatus.CREATED)
        self.assertEqual(result.summary.total_sources, 0)
        self.assertEqual(result.summary.progress_ratio, 0.0)

    def test_selection_is_deterministic_and_preserves_failed_and_running(self) -> None:
        ready_first = self._source("z-last-name.mp4", offset=0)
        reused = self._source("a-first-name.mp4", offset=1)
        failed = self._source("failed.mp4", offset=2)
        running = self._source("running.mp4", offset=3)
        ready_last = self._source("middle.mp4", offset=4)
        self._complete(reused)
        self._fail(failed)
        self._running(running)
        calls: list = []

        result = self._run(self._processor(calls=calls), max_concurrency=1)

        self.assertEqual(calls, [ready_first, ready_last])
        self.assertEqual(
            [item.source_video_id for item in result.sources],
            [ready_first, reused, failed, running, ready_last],
        )
        self.assertEqual(
            [item.outcome for item in result.sources],
            [
                ProjectSourceOutcome.PROCESSED,
                ProjectSourceOutcome.REUSED,
                ProjectSourceOutcome.FAILED,
                ProjectSourceOutcome.BLOCKED,
                ProjectSourceOutcome.PROCESSED,
            ],
        )
        self.assertEqual(result.summary.processed_count, 2)
        self.assertEqual(result.summary.reused_count, 1)
        self.assertEqual(result.summary.completed_count, 3)
        self.assertEqual(result.summary.failed_count, 1)
        self.assertEqual(result.summary.blocked_count, 1)
        self.assertEqual(result.project_status, ProjectStatus.PROCESSING)

    def test_one_source_failure_does_not_stop_later_sources(self) -> None:
        source_ids = [self._source(f"source-{index}.mp4", offset=index) for index in range(3)]
        calls: list = []
        result = self._run(
            self._processor(calls=calls, fail_source_id=source_ids[1])
        )

        self.assertEqual(calls, source_ids)
        self.assertEqual(
            [item.outcome for item in result.sources],
            [
                ProjectSourceOutcome.PROCESSED,
                ProjectSourceOutcome.FAILED,
                ProjectSourceOutcome.PROCESSED,
            ],
        )
        self.assertEqual(result.summary.completed_count, 2)
        self.assertEqual(result.summary.failed_count, 1)
        self.assertEqual(result.project_status, ProjectStatus.COMPLETED_WITH_WARNINGS)
        with self.factory() as session:
            self.assertEqual(
                session.get(Project, self.project_id).status,
                ProjectStatus.COMPLETED_WITH_WARNINGS,
            )
            self.assertEqual(
                session.get(SourceVideo, source_ids[2]).processing_status,
                SourceVideoStatus.COMPLETED,
            )

    def test_bounded_concurrency_uses_independent_sessions_and_rerun_reuses(self) -> None:
        source_ids = [self._source(f"source-{index}.mp4", offset=index) for index in range(12)]
        active = 0
        peak = 0
        lock = Lock()
        sessions: list[Session] = []

        def processor(*, session: Session, source_video_id, **_kwargs):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
                sessions.append(session)
            sleep(0.01)
            try:
                return self._mark_completed(session, source_video_id)
            finally:
                with lock:
                    active -= 1

        first = self._run(processor, max_concurrency=2)
        second_calls: list = []
        second = self._run(self._processor(calls=second_calls), max_concurrency=2)

        self.assertEqual(first.summary.completed_count, 12)
        self.assertLessEqual(peak, 2)
        self.assertGreater(peak, 1)
        self.assertEqual(len({id(session) for session in sessions}), len(source_ids))
        self.assertEqual(second.summary.processed_count, 0)
        self.assertEqual(second.summary.reused_count, 12)
        self.assertEqual(second_calls, [])

    def test_invalid_max_concurrency_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._run(self._processor(), max_concurrency=0)

    def test_concurrent_state_conflict_is_blocked_instead_of_marked_failed(self) -> None:
        source_id = self._source("race.mp4", offset=0)

        def conflicting_processor(**_kwargs):
            raise SourceProcessingStateError("Stage is no longer executable.")

        result = self._run(conflicting_processor)

        self.assertEqual(result.sources[0].source_video_id, source_id)
        self.assertEqual(result.sources[0].outcome, ProjectSourceOutcome.BLOCKED)
        self.assertEqual(result.summary.failed_count, 0)
        self.assertEqual(result.summary.blocked_count, 1)
        self.assertEqual(result.project_status, ProjectStatus.PROCESSING)

    def _run(self, processor, *, max_concurrency=1):
        return process_project(
            session_factory=self.factory,
            storage=self.storage,
            workspace=self.workspace,
            project_id=self.project_id,
            max_concurrency=max_concurrency,
            source_processor=processor,
        )

    def _source(self, filename: str, *, offset: int):
        with self.factory() as session:
            source = SourceVideo(
                project_id=self.project_id,
                original_filename=filename,
                storage_reference=f"projects/{self.project_id.hex}/sources/{offset}.mp4",
                fingerprint=f"fingerprint-{offset}",
                fingerprint_algorithm="sha256",
                processing_status=SourceVideoStatus.READY,
                created_at=datetime.now(timezone.utc) + timedelta(seconds=offset),
                processing_stages=[
                    ProcessingStage(
                        stage=stage, status=ProcessingStageStatus.PENDING
                    )
                    for stage in ProcessingStageKind
                ],
            )
            session.add(source)
            session.commit()
            return source.id

    def _complete(self, source_id) -> None:
        with self.factory() as session:
            self._mark_completed(session, source_id)

    def _fail(self, source_id) -> None:
        with self.factory() as session:
            source = session.get(SourceVideo, source_id)
            stage = self._stages(session, source_id)[ProcessingStageKind.PROBE]
            source.processing_status = SourceVideoStatus.FAILED
            stage.status = ProcessingStageStatus.FAILED
            stage.safe_error_code = "PROBE_FAILED"
            session.commit()

    def _running(self, source_id) -> None:
        with self.factory() as session:
            source = session.get(SourceVideo, source_id)
            stage = self._stages(session, source_id)[ProcessingStageKind.STT]
            source.processing_status = SourceVideoStatus.PROCESSING
            stage.status = ProcessingStageStatus.RUNNING
            stage.started_at = datetime.now(timezone.utc)
            session.commit()

    def _processor(self, *, calls=None, fail_source_id=None):
        def processor(*, session: Session, source_video_id, **_kwargs):
            if calls is not None:
                calls.append(source_video_id)
            if source_video_id == fail_source_id:
                source = session.get(SourceVideo, source_video_id)
                stage = self._stages(session, source_video_id)[ProcessingStageKind.PROBE]
                source.processing_status = SourceVideoStatus.FAILED
                stage.status = ProcessingStageStatus.FAILED
                stage.safe_error_code = "PROBE_FAILED"
                session.commit()
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
                text="test",
                language="ko",
                language_probability=1.0,
                segments=[],
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

    @staticmethod
    def _stages(session, source_id):
        return {
            stage.stage: stage
            for stage in session.scalars(
                select(ProcessingStage).where(
                    ProcessingStage.source_video_id == source_id
                )
            ).all()
        }
