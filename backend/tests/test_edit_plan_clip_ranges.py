"""TODO 8: the widened clip range from the story length fit is saved with the edit plan and used for rendering."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate,
    SceneAnalysisWorkStatus, SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.services.project_rendering import _load_segments, plan_snapshot


class EditPlanClipRangeTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(f"sqlite+pysqlite:///{Path(self.temporary.name) / 'plan.db'}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start()
        self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__()
        self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        with self.factory() as session:
            project = Project(name="clip ranges", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.commit()
            self.project = project.id
        self.first, self.second = self._candidate(10, 60.0), self._candidate(20, 30.0)
        self.url = f"/projects/{self.project}/scene-edit-plan"

    def _candidate(self, start, duration):
        with self.factory() as session:
            source = SourceVideo(project_id=self.project, original_filename="clip.mov",
                                 storage_reference=uuid4().hex, duration_seconds=duration)
            session.add(source)
            session.flush()
            work = SceneAnalysisWorkItem(
                project_id=self.project, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint=uuid4().hex, producer="test",
                producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint=uuid4().hex)
            session.add(work)
            session.flush()
            candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id,
                                       start_seconds=start, end_seconds=start + 4,
                                       discovery_method=SceneDiscoveryMethod.AUTONOMOUS, input_fingerprint="input")
            session.add(candidate)
            session.flush()
            session.add_all([
                SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                              evidence_type="AUDIO_ACTIVITY", payload={}, producer="test",
                              producer_version="1", source_reference="fake"),
            ])
            session.commit()
            return candidate.id

    def test_widened_ranges_are_saved_returned_and_rendered(self):
        ids = [str(self.second), str(self.first)]
        body = {"candidate_ids": ids, "clip_ranges": [{"start_seconds": 5.5, "end_seconds": 29.25}, None]}
        saved = self.client.put(self.url, json=body)
        self.assertEqual(saved.status_code, 200)
        expected = [{"start_seconds": 5.5, "end_seconds": 29.25}, None]
        self.assertEqual(saved.json()["clip_ranges"], expected)
        self.assertEqual(self.client.get(self.url).json()["clip_ranges"], expected)
        with self.factory() as session:
            segments = _load_segments(session, self.project)
        self.assertEqual([(s.start_seconds, s.end_seconds) for s in segments], [(5.5, 29.25), (10.0, 14.0)])
        self.assertEqual(plan_snapshot(segments)[0]["end_seconds"], 29.25)

    def test_saving_without_ranges_keeps_the_found_moment(self):
        self.assertEqual(self.client.put(self.url, json={"candidate_ids": [str(self.first)]}).status_code, 200)
        self.assertEqual(self.client.get(self.url).json()["clip_ranges"], [None])
        with self.factory() as session:
            segment = _load_segments(session, self.project)[0]
        self.assertEqual((segment.start_seconds, segment.end_seconds), (10.0, 14.0))

    def test_range_outside_the_video_or_mismatched_is_rejected_without_change(self):
        self.client.put(self.url, json={"candidate_ids": [str(self.first)]})
        for ranges in ([{"start_seconds": 5, "end_seconds": 31}],   # second video is 30 s long
                       [{"start_seconds": 8, "end_seconds": 8}],
                       [{"start_seconds": -1, "end_seconds": 8}],
                       []):
            response = self.client.put(self.url, json={"candidate_ids": [str(self.second)], "clip_ranges": ranges})
            self.assertEqual(response.status_code, 422, ranges)
        self.assertEqual(self.client.get(self.url).json()["candidate_ids"], [str(self.first)])
