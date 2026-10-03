import os
from unittest import TestCase, skipUnless

from sqlalchemy import delete, select

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.autonomous_discovery import (
    AnalysisInterval,
    AnalysisUnitType,
    ModalityAnalysis,
    SignalEvidence,
    process_autonomous_discovery,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class AutonomousDiscoveryIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.factory() as session:
            ids = list(session.scalars(select(Project.id).where(Project.name.like("Autonomous integration%"))))
        self.project_ids = ids
        self._cleanup()
        self.project_ids = []

    def tearDown(self) -> None:
        self._cleanup()

    def test_candidate_evidence_partial_failure_dedupe_and_memo_merge_are_durable(self) -> None:
        with self.factory() as session:
            source = self._graph(session)
            memo_candidate = SceneCandidate(source_video_id=source.id, start_seconds=16, end_seconds=20, discovery_method=SceneDiscoveryMethod.MEMO_GUIDED, confidence=None, input_fingerprint="memo-lineage")
            session.add(memo_candidate)
            session.commit()
            result = process_autonomous_discovery(
                session,
                source.id,
                audio_analyzer=lambda: ModalityAnalysis((_fact(source.id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),)),
                visual_analyzer=lambda: (_ for _ in ()).throw(RuntimeError("visual unavailable")),
            )
            repeated = process_autonomous_discovery(session, source.id)
            candidate_id = result.candidate_ids[0]
            work_ids = result.work_item_ids

        with self.factory() as session:
            candidate = session.get(SceneCandidate, candidate_id)
            evidences = session.scalars(select(SceneEvidence).where(SceneEvidence.scene_candidate_id == candidate_id)).all()
            works = session.scalars(select(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.id.in_(work_ids))).all()
            attempts = session.scalars(select(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id.in_(work_ids))).all()
            self.assertEqual(candidate.discovery_method, SceneDiscoveryMethod.MEMO_GUIDED)
            self.assertEqual((float(candidate.start_seconds), float(candidate.end_seconds)), (16.0, 20.0))
            self.assertEqual({item.modality for item in evidences}, {SceneEvidenceModality.TRANSCRIPT, SceneEvidenceModality.AUDIO})
            self.assertEqual(len(works), 4)
            self.assertEqual(len(attempts), 4)
            self.assertIn("VISUAL_EVIDENCE_FAILED", result.warnings)
            self.assertEqual(repeated.candidate_ids, result.candidate_ids)
            self.assertNotIn("C:\\", str([item.payload for item in evidences]))

    def _graph(self, session):
        project = Project(name="Autonomous integration selected", split_policy=EpisodeSplitPolicy.SINGLE)
        source = SourceVideo(project=project, original_filename="source.mov", storage_reference="projects/integration/source.mov", fingerprint="autonomous-source", fingerprint_algorithm="sha256", duration_seconds=48, processing_status=SourceVideoStatus.COMPLETED)
        source.transcript = Transcript(text="일반 대화 우와 대박", language="ko", language_probability=1, segments=[{"start_seconds": 8, "end_seconds": 16, "text": "일반 대화", "words": []}, {"start_seconds": 16, "end_seconds": 20, "text": "우와 대박", "words": []}])
        session.add(project)
        session.commit()
        self.project_ids.append(project.id)
        return source

    def _cleanup(self) -> None:
        with self.factory() as session:
            for project_id in self.project_ids:
                source_ids = select(SourceVideo.id).where(SourceVideo.project_id == project_id)
                candidate_ids = select(SceneCandidate.id).where(SceneCandidate.source_video_id.in_(source_ids))
                work_ids = select(SceneAnalysisWorkItem.id).where(SceneAnalysisWorkItem.project_id == project_id)
                session.execute(delete(SceneEvidence).where(SceneEvidence.scene_candidate_id.in_(candidate_ids)))
                session.execute(
                    delete(SceneAnalysisWorkResultCandidate).where(
                        SceneAnalysisWorkResultCandidate.scene_candidate_id.in_(
                            select(SceneCandidate.id).where(SceneCandidate.source_video_id.in_(source_ids))
                        )
                    )
                )
                session.execute(delete(SceneCandidate).where(SceneCandidate.source_video_id.in_(source_ids)))
                session.execute(delete(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id.in_(work_ids)))
                session.execute(delete(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.project_id == project_id))
                session.execute(delete(Transcript).where(Transcript.source_video_id.in_(source_ids)))
                session.execute(delete(SourceVideo).where(SourceVideo.project_id == project_id))
                session.execute(delete(Project).where(Project.id == project_id))
            session.commit()


def _fact(source_id, start, end, modality, evidence_type):
    return SignalEvidence(
        AnalysisInterval(source_id, start, end, AnalysisUnitType.AUDIO_ACTIVITY, "integration", "v1"),
        modality,
        evidence_type,
        {"measurement": 1},
    )
