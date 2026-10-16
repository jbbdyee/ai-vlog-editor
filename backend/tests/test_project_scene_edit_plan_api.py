"""Media-free persistence and active-result conflict tests for MVP-04."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectSceneEditPlanItem, SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus, SceneCandidate,
    SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)


class ProjectSceneEditPlanApiTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.engine = create_engine(
            f"sqlite+pysqlite:///{Path(self.temporary.name) / 'plan.db'}",
            connect_args={"check_same_thread": False},
        )
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
        self.project = self._project()

    def _project(self):
        with self.factory() as session:
            row = Project(name="plan test", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(row)
            session.commit()
            return row.id

    def _candidates(self, project_id, starts):
        with self.factory() as session:
            ids = []
            for start in starts:
                source = SourceVideo(project_id=project_id, original_filename="fake.mov", storage_reference=uuid4().hex)
                session.add(source)
                session.flush()
                work = SceneAnalysisWorkItem(
                    project_id=project_id, source_video_id=source.id,
                    work_type="AUTONOMOUS_PROMOTION", status=SceneAnalysisWorkStatus.COMPLETED,
                    input_fingerprint=uuid4().hex, producer="test", producer_version="1",
                    result_reference="autonomous:candidates:1", result_fingerprint=uuid4().hex,
                )
                session.add(work)
                session.flush()
                candidate = SceneCandidate(
                    source_video_id=source.id, analysis_work_item_id=work.id,
                    start_seconds=start, end_seconds=start + 1,
                    discovery_method=SceneDiscoveryMethod.AUTONOMOUS, input_fingerprint="input",
                )
                session.add(candidate)
                session.flush()
                session.add_all([
                    SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                    SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                                  evidence_type="AUDIO_ACTIVITY", payload={}, producer="test",
                                  producer_version="1", source_reference="fake"),
                ])
                ids.append(candidate.id)
            session.commit()
            return ids

    def _url(self, project=None):
        return f"/projects/{project or self.project}/scene-edit-plan"

    def test_empty_plan_and_missing_project(self):
        self.assertEqual(self.client.get(self._url()).json()["candidate_ids"], [])
        self.assertEqual(self.client.put(self._url(), json={"candidate_ids": []}).status_code, 200)
        self.assertEqual(self.client.get(self._url(uuid4())).status_code, 404)

    def test_selection_exclusion_order_persistence_and_multiple_sources(self):
        first, second, third = self._candidates(self.project, (2, 5, 9))
        url = self._url()
        selected = [str(third), str(first)]
        self.assertEqual(self.client.put(url, json={"candidate_ids": selected}).json()["candidate_ids"], selected)
        self.assertEqual(self.client.get(url).json()["candidate_ids"], selected)
        reordered = [str(first), str(third), str(second)]
        self.assertEqual(self.client.put(url, json={"candidate_ids": reordered}).json()["candidate_ids"], reordered)
        self.assertEqual(self.client.put(url, json={"candidate_ids": [str(second)]}).json()["candidate_ids"], [str(second)])
        with self.factory() as session:
            self.assertEqual(session.query(ProjectSceneEditPlanItem).count(), 1)
        self.assertEqual(self.client.get(url).json()["candidate_ids"], [str(second)])
        self.assertEqual(len(self.client.get(f"/projects/{self.project}/scene-candidates").json()["candidates"]), 3)

    def test_invalid_foreign_and_duplicate_candidates_are_rejected_without_mutation(self):
        active = self._candidates(self.project, (1,))[0]
        other = self._project()
        foreign = self._candidates(other, (2,))[0]
        url = self._url()
        self.assertEqual(self.client.put(url, json={"candidate_ids": [str(active)]}).status_code, 200)
        for ids in ([str(foreign)], [str(uuid4())], [str(active), str(active)]):
            response = self.client.put(url, json={"candidate_ids": ids})
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["detail"]["code"], "SCENE_EDIT_PLAN_CANDIDATE_CONFLICT")
            self.assertEqual(self.client.get(url).json()["candidate_ids"], [str(active)])

    def test_reanalysis_conflict_is_visible_and_requires_explicit_resolution(self):
        old = self._candidates(self.project, (1,))[0]
        self.assertEqual(self.client.put(self._url(), json={"candidate_ids": [str(old)]}).status_code, 200)
        with self.factory() as session:
            old_source = session.get(SceneCandidate, old).source_video_id
            work = session.query(SceneAnalysisWorkItem).filter_by(source_video_id=old_source).one()
            work.status = SceneAnalysisWorkStatus.FAILED
            session.commit()
        plan = self.client.get(self._url()).json()
        self.assertEqual(plan["candidate_ids"], [str(old)])
        self.assertEqual(plan["invalid_candidate_ids"], [str(old)])
        self.assertEqual(self.client.put(self._url(), json={"candidate_ids": [str(old)]}).status_code, 409)
        self.assertEqual(self.client.put(self._url(), json={"candidate_ids": []}).status_code, 200)

    def test_project_data_isolation_and_existing_scene_api(self):
        own = self._candidates(self.project, (1,))[0]
        other = self._project()
        foreign = self._candidates(other, (2,))[0]
        self.client.put(self._url(), json={"candidate_ids": [str(own)]})
        self.assertEqual(self.client.get(self._url(other)).json()["candidate_ids"], [])
        self.assertEqual(self.client.get(f"/projects/{other}/scene-candidates").json()["candidates"][0]["candidate_id"], str(foreign))
