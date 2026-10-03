from __future__ import annotations

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
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
    SourceVideoStatus,
)
from backend.app.services.shot_structure import (
    ShotStructureError,
    ShotDetectionConfig,
    build_shot_structure_result,
    process_shot_evidence,
    shot_config_fingerprint,
    shot_input_fingerprint,
)
from backend.app.services.scene_processing_state import (
    AUTONOMOUS_PROMOTION,
    SHOT_EVIDENCE,
    SceneWorkSpec,
    determine_scene_resume_plan,
)


@skipUnless(
    os.environ.get("RUN_DATABASE_INTEGRATION_TESTS") == "1",
    "Set RUN_DATABASE_INTEGRATION_TESTS=1 with local PostgreSQL running.",
)
class ShotStructureIntegrationTests(TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.engine = create_database_engine(DatabaseSettings.from_environment())
        cls.factory = create_session_factory(cls.engine)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        with self.factory() as session:
            project = Project(name="Shot integration", split_policy=EpisodeSplitPolicy.SINGLE)
            source = SourceVideo(
                project=project,
                original_filename="shot.mov",
                storage_reference="projects/integration/shot.mov",
                fingerprint="shot-integration-source",
                fingerprint_algorithm="sha256",
                duration_seconds=4,
                processing_status=SourceVideoStatus.COMPLETED,
            )
            session.add(project)
            promotion = SceneAnalysisWorkItem(
                project=project,
                source_video=source,
                work_type=AUTONOMOUS_PROMOTION,
                status=SceneAnalysisWorkStatus.COMPLETED,
                input_fingerprint="promotion-input",
                config_fingerprint="promotion-config",
                producer="test",
                producer_version="v1",
                result_reference="autonomous:candidates:1",
                result_fingerprint="promotion-result",
            )
            candidate = SceneCandidate(
                source_video=source,
                analysis_work_item=promotion,
                start_seconds=1,
                end_seconds=3,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                confidence=None,
                input_fingerprint="candidate-input",
                result_fingerprint="candidate-result",
            )
            session.add_all([promotion, candidate])
            session.flush()
            session.add_all(
                [
                    SceneAnalysisWorkResultCandidate(
                        work_item_id=promotion.id, scene_candidate_id=candidate.id
                    ),
                    SceneEvidence(
                        scene_candidate_id=candidate.id,
                        modality=SceneEvidenceModality.AUDIO,
                        evidence_type="AUDIO_ACTIVITY",
                        payload={},
                        producer="test",
                        producer_version="v1",
                    ),
                ]
            )
            session.commit()
            self.project_id = project.id
            self.source_id = source.id
            self.candidate_id = candidate.id

    def tearDown(self) -> None:
        with self.factory() as session:
            work_ids = select(SceneAnalysisWorkItem.id).where(
                SceneAnalysisWorkItem.project_id == self.project_id
            )
            session.execute(
                delete(SceneEvidence).where(
                    SceneEvidence.scene_candidate_id == self.candidate_id
                )
            )
            session.execute(
                delete(SceneAnalysisWorkResultCandidate).where(
                    SceneAnalysisWorkResultCandidate.work_item_id.in_(work_ids)
                )
            )
            session.execute(
                delete(SceneAnalysisAttempt).where(
                    SceneAnalysisAttempt.work_item_id.in_(work_ids)
                )
            )
            session.execute(delete(SceneCandidate).where(SceneCandidate.id == self.candidate_id))
            session.execute(
                delete(SceneAnalysisWorkItem).where(
                    SceneAnalysisWorkItem.project_id == self.project_id
                )
            )
            session.execute(delete(SourceVideo).where(SourceVideo.id == self.source_id))
            session.execute(delete(Project).where(Project.id == self.project_id))
            session.commit()

    def test_postgresql_durability_reuse_and_config_reprocess(self) -> None:
        calls = 0

        def analyzer(source_id, duration):
            nonlocal calls
            calls += 1
            return build_shot_structure_result(source_id, duration, ((2.0, 50),))

        with self.factory() as session:
            first = process_shot_evidence(session, self.source_id, analyzer=analyzer)
            second = process_shot_evidence(session, self.source_id, analyzer=analyzer)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
        with self.factory() as session:
            work = session.get(SceneAnalysisWorkItem, first.work_item_id)
            self.assertIsNotNone(work.result_reference)
            evidence = session.scalar(
                select(SceneEvidence).where(
                    SceneEvidence.scene_candidate_id == self.candidate_id,
                    SceneEvidence.modality == SceneEvidenceModality.SHOT,
                )
            )
            self.assertIsNotNone(evidence)
            changed = process_shot_evidence(
                session,
                self.source_id,
                analyzer=analyzer,
                config=ShotDetectionConfig(threshold_percent=12),
            )
            self.assertNotEqual(first.work_item_id, changed.work_item_id)
        self.assertEqual(calls, 2)

    def test_zero_boundary_is_durable_and_source_change_invalidates(self) -> None:
        with self.factory() as session:
            result = process_shot_evidence(
                session,
                self.source_id,
                analyzer=lambda source_id, duration: build_shot_structure_result(
                    source_id, duration, ()
                ),
            )
            self.assertEqual(result.boundary_count, 0)
            self.assertEqual(result.interval_count, 1)
        with self.factory() as session:
            work = session.get(SceneAnalysisWorkItem, result.work_item_id)
            self.assertEqual(work.status, SceneAnalysisWorkStatus.COMPLETED)
            source = session.get(SourceVideo, self.source_id)
            source.fingerprint = "changed-shot-source"
            session.commit()
            spec = SceneWorkSpec(
                self.project_id,
                SHOT_EVIDENCE,
                shot_input_fingerprint(source),
                shot_config_fingerprint(ShotDetectionConfig()),
                "shot-structure",
                "ffmpeg-scdet-v0.1",
                self.source_id,
            )
            plan = determine_scene_resume_plan(session, (spec,))
            self.assertEqual(plan.execution_specs, (spec,))
            self.assertIn(result.work_item_id, plan.invalid_work_items)

    def test_detector_failure_isolated_from_existing_candidate(self) -> None:
        def failure(source_id, duration):
            raise ShotStructureError("detector failed")

        with self.factory() as session:
            with self.assertRaises(ShotStructureError):
                process_shot_evidence(session, self.source_id, analyzer=failure)
        with self.factory() as session:
            self.assertIsNotNone(session.get(SceneCandidate, self.candidate_id))
            failed = session.scalar(
                select(SceneAnalysisWorkItem).where(
                    SceneAnalysisWorkItem.source_video_id == self.source_id,
                    SceneAnalysisWorkItem.work_type == SHOT_EVIDENCE,
                )
            )
            self.assertEqual(failed.status, SceneAnalysisWorkStatus.FAILED)
