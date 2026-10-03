from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from unittest import TestCase
from uuid import UUID

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkResultCandidate,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
)
from backend.app.services.scene_fingerprints import canonical_fingerprint
from backend.app.services.scene_processing_state import (
    AUTONOMOUS_PROMOTION,
    AUDIO_EVIDENCE,
    SceneResumeReason,
    SceneWorkSpec,
    active_candidate_ids,
    determine_scene_resume_plan,
    recover_stale_scene_work,
    claim_scene_work,
    start_scene_work_retry,
    work_result_is_valid,
)


class _Marker(str, Enum):
    VALUE = "VALUE"


class CanonicalFingerprintTests(TestCase):
    def test_mapping_set_uuid_enum_decimal_are_stable(self) -> None:
        identity = UUID("00000000-0000-0000-0000-000000000001")
        left = {"b": {"z", "a"}, "a": [identity, _Marker.VALUE, Decimal("1.200")]}
        right = {"a": [identity, "VALUE", Decimal("1.2")], "b": {"a", "z"}}
        self.assertEqual(canonical_fingerprint(left), canonical_fingerprint(right))

    def test_semantic_change_changes_fingerprint(self) -> None:
        self.assertNotEqual(canonical_fingerprint({"count": 0}), canonical_fingerprint({"count": 1}))


class SceneProcessingStateTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_zero_candidate_completion_is_valid_and_reused(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            work = _work(project.id, source.id, AUTONOMOUS_PROMOTION, "input", "config")
            work.result_reference = "autonomous:candidates:0"
            work.result_fingerprint = canonical_fingerprint({"candidate_ids": []})
            session.add(work)
            session.commit()
            spec = SceneWorkSpec(project.id, AUTONOMOUS_PROMOTION, "input", "config", "test", "v1", source.id)
            plan = determine_scene_resume_plan(session, (spec,))
            self.assertTrue(work_result_is_valid(session, work))
            self.assertEqual(plan.reusable_work_items, (work.id,))
            self.assertEqual(plan.execution_specs, ())

    def test_audio_config_change_invalidates_audio_and_promotion_only(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            work = _work(project.id, source.id, AUDIO_EVIDENCE, "source", "old")
            work.result_reference = '{"schema":"autonomous-modality-result-v0.1","evidences":[]}'
            work.result_fingerprint = canonical_fingerprint({"evidences": []})
            session.add(work)
            session.commit()
            spec = SceneWorkSpec(project.id, AUDIO_EVIDENCE, "source", "new", "test", "v1", source.id)
            plan = determine_scene_resume_plan(session, (spec,))
            self.assertEqual(plan.execution_specs, (spec,))
            self.assertIn((AUDIO_EVIDENCE, SceneResumeReason.CONFIG_CHANGED), plan.reasons)
            self.assertIn(AUTONOMOUS_PROMOTION, plan.downstream_invalidations)

    def test_latest_zero_result_excludes_old_candidate_from_active_snapshot(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            old = _work(project.id, source.id, AUTONOMOUS_PROMOTION, "old", "config")
            old.created_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            candidate = SceneCandidate(
                source_video_id=source.id,
                analysis_work_item=old,
                start_seconds=1,
                end_seconds=2,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
                input_fingerprint="old",
                result_fingerprint="candidate",
            )
            session.add(candidate)
            session.flush()
            session.add_all([
                SceneEvidence(
                    scene_candidate_id=candidate.id,
                    modality=SceneEvidenceModality.AUDIO,
                    evidence_type="AUDIO_ACTIVITY",
                    payload={},
                    producer="test",
                    producer_version="v1",
                ),
                SceneAnalysisWorkResultCandidate(work_item_id=old.id, scene_candidate_id=candidate.id),
            ])
            old.result_reference = "autonomous:candidates:1"
            old.result_fingerprint = "old-result"
            session.commit()
            self.assertEqual(active_candidate_ids(session, project.id), (candidate.id,))

            latest = _work(project.id, source.id, AUTONOMOUS_PROMOTION, "new", "config")
            latest.created_at = datetime.now(timezone.utc)
            latest.result_reference = "autonomous:candidates:0"
            latest.result_fingerprint = "new-result"
            session.add(latest)
            session.commit()
            self.assertEqual(active_candidate_ids(session, project.id), ())

    def test_stale_recovery_then_retry_allocates_new_attempt(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            work = _work(project.id, source.id, AUDIO_EVIDENCE, "source", "config", status=SceneAnalysisWorkStatus.RUNNING)
            attempt = SceneAnalysisAttempt(
                work_item=work,
                attempt_number=1,
                status=SceneAnalysisAttemptStatus.RUNNING,
                started_at=datetime.now(timezone.utc) - timedelta(hours=2),
            )
            session.add_all([work, attempt])
            session.commit()
            recover_stale_scene_work(
                session, work.id, stale_before=datetime.now(timezone.utc) - timedelta(hours=1)
            )
            retry = start_scene_work_retry(session, work.id)
            self.assertEqual(retry.attempt_number, 2)
            self.assertEqual(session.get(SceneAnalysisWorkItem, work.id).status, SceneAnalysisWorkStatus.RUNNING)

    def test_second_exact_claim_is_blocked_while_first_is_running(self) -> None:
        with Session(self.engine, expire_on_commit=False) as first, Session(self.engine, expire_on_commit=False) as second:
            project, source = _source(first)
            spec = SceneWorkSpec(project.id, AUDIO_EVIDENCE, "source", "config", "test", "v1", source.id)
            work, attempt, created = claim_scene_work(first, spec)
            self.assertTrue(created)
            self.assertEqual(attempt.attempt_number, 1)
            with self.assertRaisesRegex(Exception, "CONCURRENT_EXECUTION"):
                claim_scene_work(second, spec)
            self.assertEqual(second.scalar(select(SceneAnalysisWorkItem).where(SceneAnalysisWorkItem.id == work.id)).status, SceneAnalysisWorkStatus.RUNNING)


def _source(session):
    project = Project(name="Scene state", split_policy=EpisodeSplitPolicy.SINGLE)
    source = SourceVideo(
        project=project,
        original_filename="source.mov",
        storage_reference="projects/test/source.mov",
        fingerprint="source-fingerprint",
        fingerprint_algorithm="sha256",
    )
    session.add(project)
    session.commit()
    return project, source


def _work(project_id, source_id, work_type, input_fingerprint, config_fingerprint, *, status=SceneAnalysisWorkStatus.COMPLETED):
    return SceneAnalysisWorkItem(
        project_id=project_id,
        source_video_id=source_id,
        work_type=work_type,
        status=status,
        input_fingerprint=input_fingerprint,
        producer="test",
        producer_version="v1",
        config_fingerprint=config_fingerprint,
    )
