import os
from unittest import TestCase, skipUnless

from sqlalchemy import delete, select

from backend.app.config import DatabaseSettings
from backend.app.database import create_database_engine, create_session_factory
from backend.app.models import (
    EditMemo,
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.memo_guided_discovery import (
    SelectionStatus,
    process_memo_guided_discovery,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class MemoGuidedDiscoveryIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        self.project_ids = []
        with self.factory() as session:
            self.project_ids = list(
                session.scalars(
                    select(Project.id).where(Project.name.like("Memo discovery %"))
                )
            )
        self._cleanup()
        self.project_ids = []

    def tearDown(self) -> None:
        self._cleanup()

    def _cleanup(self) -> None:
        with self.factory() as session:
            for project_id in self.project_ids:
                source_ids = select(SourceVideo.id).where(SourceVideo.project_id == project_id)
                candidate_ids = select(SceneCandidate.id).where(SceneCandidate.source_video_id.in_(source_ids))
                work_ids = select(SceneAnalysisWorkItem.id).where(SceneAnalysisWorkItem.project_id == project_id)
                session.execute(delete(SceneEvidence).where(SceneEvidence.scene_candidate_id.in_(candidate_ids)))
                session.execute(delete(SceneCandidate).where(SceneCandidate.source_video_id.in_(source_ids)))
                session.execute(delete(SceneAnalysisAttempt).where(SceneAnalysisAttempt.work_item_id.in_(work_ids)))
                session.execute(delete(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.project_id == project_id))
                session.execute(delete(EditMemo).where(EditMemo.source_video_id.in_(source_ids)))
                session.execute(delete(Transcript).where(Transcript.source_video_id.in_(source_ids)))
                session.execute(delete(SourceVideo).where(SourceVideo.project_id == project_id))
                session.execute(delete(Project).where(Project.id == project_id))
            session.commit()

    def test_selected_abstained_and_idempotent_results_survive_new_sessions(self) -> None:
        with self.factory() as session:
            selected_memo = self._graph(session, action="살려줘", name="selected")
            abstained_memo = self._graph(session, action="지워줘", name="abstained")
            selected = process_memo_guided_discovery(session, selected_memo.id)
            abstained = process_memo_guided_discovery(session, abstained_memo.id)
            repeated = process_memo_guided_discovery(session, selected_memo.id)
            selected_ids = (selected.work_item_id, selected.attempt_id, selected.candidate_id)
            abstained_ids = (abstained.work_item_id, abstained.attempt_id)
            selected_source_id = selected.source_video_id
            memo_text = selected_memo.transcript_text

        with self.factory() as session:
            work = session.get(SceneAnalysisWorkItem, selected_ids[0])
            attempt = session.get(SceneAnalysisAttempt, selected_ids[1])
            candidate = session.get(SceneCandidate, selected_ids[2])
            evidences = session.scalars(select(SceneEvidence).where(SceneEvidence.scene_candidate_id == candidate.id)).all()
            abstained_work = session.get(SceneAnalysisWorkItem, abstained_ids[0])
            abstained_attempt = session.get(SceneAnalysisAttempt, abstained_ids[1])
            self.assertEqual(candidate.source_video_id, selected_source_id)
            self.assertEqual(candidate.discovery_method, SceneDiscoveryMethod.MEMO_GUIDED)
            self.assertEqual((float(candidate.start_seconds), float(candidate.end_seconds)), (12.0, 15.0))
            self.assertEqual({item.evidence_type for item in evidences}, {"USER_MEMO", "TEMPORAL_REFERENCE", "TRANSCRIPT_MATCH", "SEMANTIC_SELECTION"})
            self.assertEqual(work.status, SceneAnalysisWorkStatus.COMPLETED)
            self.assertEqual(attempt.status, SceneAnalysisAttemptStatus.COMPLETED)
            self.assertEqual(abstained_work.status, SceneAnalysisWorkStatus.COMPLETED)
            self.assertEqual(abstained_attempt.status, SceneAnalysisAttemptStatus.COMPLETED)
            self.assertTrue(abstained_work.result_reference.startswith("abstain:"))
            self.assertEqual(selected.candidate_id, repeated.candidate_id)
            self.assertEqual(session.scalar(select(SceneCandidate).where(SceneCandidate.analysis_work_item_id == work.id).with_only_columns(SceneCandidate.id)), candidate.id)
            self.assertNotIn(memo_text, str([item.payload for item in evidences]))

    def _graph(self, session, *, action: str, name: str) -> EditMemo:
        project = Project(name=f"Memo discovery {name}", split_policy=EpisodeSplitPolicy.SINGLE)
        source = SourceVideo(project=project, original_filename="source.mov", storage_reference=f"projects/{name}/source.mov", fingerprint=f"sha-{name}", fingerprint_algorithm="sha256", duration_seconds=21, processing_status=SourceVideoStatus.COMPLETED)
        segments = [
            {"start_seconds": 12.0, "end_seconds": 15.0, "text": "여행 장면", "words": []},
            {"start_seconds": 16.0, "end_seconds": 18.0, "text": "AI야 방금 장면 꼭 살려줘", "words": []},
        ]
        transcript = Transcript(source_video=source, text="여행 장면 AI야", language="ko", language_probability=1, segments=segments)
        memo = EditMemo(source_video=source, transcript=transcript, start_seconds=16, end_seconds=18, transcript_text="AI야 방금 장면 꼭 살려줘", matched_trigger="AI야", matched_reference="방금", matched_action=action, trigger_match_type="exact", trigger_similarity=1)
        session.add(project)
        session.commit()
        self.project_ids.append(project.id)
        return memo
