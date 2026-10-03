from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    SceneAnalysisAttempt,
    EpisodeSplitPolicy,
    Project,
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
from backend.app.services.scene_fingerprints import canonical_fingerprint
from backend.app.services.scene_processing_state import (
    AUTONOMOUS_PROMOTION,
    AUDIO_EVIDENCE,
    SHOT_EVIDENCE,
    TRANSCRIPT_EVIDENCE,
    VISUAL_EVIDENCE,
    SceneWorkSpec,
    determine_scene_resume_plan,
    work_result_is_valid,
)
from backend.app.services.shot_structure import (
    SHOT_DETECTOR_VERSION,
    ShotDetectionConfig,
    ShotStructureError,
    build_shot_structure_result,
    detect_shot_structure,
    process_shot_evidence,
    shot_config_fingerprint,
    shot_input_fingerprint,
)


class ShotStructurePureTests(TestCase):
    def setUp(self) -> None:
        self.source_id = uuid4()

    def test_zero_boundary_is_one_continuous_interval(self) -> None:
        result = build_shot_structure_result(self.source_id, 4, ())
        self.assertEqual(result.boundaries, ())
        self.assertEqual(
            [(item.start_seconds, item.end_seconds) for item in result.intervals],
            [(0.0, 4.0)],
        )

    def test_boundaries_are_normalized_deduplicated_and_ordered(self) -> None:
        result = build_shot_structure_result(
            self.source_id,
            5,
            ((3.0004, 12), (1.0004, 10), (1.0003, 11)),
        )
        self.assertEqual(
            [item.timestamp_seconds for item in result.boundaries], [1.0, 3.0]
        )
        self.assertEqual(
            [(item.start_seconds, item.end_seconds) for item in result.intervals],
            [(0.0, 1.0), (1.0, 3.0), (3.0, 5.0)],
        )

    def test_duration_endpoint_is_clamped_then_not_a_boundary(self) -> None:
        result = build_shot_structure_result(self.source_id, 5, ((5.0004, 12),))
        self.assertEqual(result.boundaries, ())

    def test_invalid_boundary_is_rejected(self) -> None:
        with self.assertRaisesRegex(ShotStructureError, "must not be negative"):
            build_shot_structure_result(self.source_id, 5, ((-0.1, 12),))

    def test_minimum_duration_suppresses_too_close_cuts(self) -> None:
        result = build_shot_structure_result(
            self.source_id,
            3,
            ((0.2, 10), (1.0, 11), (2.8, 12)),
            config=ShotDetectionConfig(minimum_shot_duration_seconds=0.5),
        )
        self.assertEqual([item.timestamp_seconds for item in result.boundaries], [1.0])

    def test_config_fingerprint_is_stable_and_changes_with_threshold(self) -> None:
        self.assertEqual(
            shot_config_fingerprint(ShotDetectionConfig()),
            shot_config_fingerprint(ShotDetectionConfig()),
        )
        self.assertNotEqual(
            shot_config_fingerprint(ShotDetectionConfig()),
            shot_config_fingerprint(ShotDetectionConfig(threshold_percent=12)),
        )

    def test_ffmpeg_scdet_output_is_parsed_without_persisting_log(self) -> None:
        with TemporaryDirectory() as directory:
            source = Path(directory) / "fixture.mp4"
            source.touch()
            process = type(
                "Result",
                (),
                {
                    "returncode": 0,
                    "stderr": (
                        "[scdet @ x] lavfi.scd.score: 42.000, lavfi.scd.time: 2.000\n"
                    ),
                },
            )()
            with patch("backend.app.services.shot_structure.subprocess.run", return_value=process) as runner:
                result = detect_shot_structure(
                    source,
                    source_video_id=self.source_id,
                    duration_seconds=4,
                )
        self.assertEqual(result.boundaries[0].timestamp_seconds, 2.0)
        command = runner.call_args.args[0]
        self.assertIn("scdet=threshold=10.000000", command)


class ShotEvidencePersistenceTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_result_is_reused_and_supports_active_candidate_only(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source, candidate = _active_candidate(session)
            calls = 0

            def analyzer(source_id, duration):
                nonlocal calls
                calls += 1
                return build_shot_structure_result(source_id, duration, ((2.0, 50),))

            first = process_shot_evidence(session, source.id, analyzer=analyzer)
            second = process_shot_evidence(session, source.id, analyzer=analyzer)
            self.assertFalse(first.reused)
            self.assertTrue(second.reused)
            self.assertEqual(calls, 1)
            evidence = session.scalar(
                select(SceneEvidence).where(
                    SceneEvidence.scene_candidate_id == candidate.id,
                    SceneEvidence.modality == SceneEvidenceModality.SHOT,
                )
            )
            self.assertIsNotNone(evidence)
            self.assertEqual(evidence.evidence_type, "SHOT_CHANGE")
            self.assertIsNone(evidence.confidence)
            self.assertNotIn("path", evidence.payload)
            work = session.get(SceneAnalysisWorkItem, first.work_item_id)
            self.assertTrue(work_result_is_valid(session, work))

    def test_zero_boundary_and_zero_candidate_are_valid(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            result = process_shot_evidence(
                session,
                source.id,
                analyzer=lambda source_id, duration: build_shot_structure_result(
                    source_id, duration, ()
                ),
            )
            self.assertEqual(result.boundary_count, 0)
            self.assertEqual(result.interval_count, 1)
            self.assertEqual(result.evidence_count, 0)
            self.assertTrue(
                work_result_is_valid(session, session.get(SceneAnalysisWorkItem, result.work_item_id))
            )

    def test_shot_config_change_only_invalidates_shot_work(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            first = process_shot_evidence(
                session,
                source.id,
                analyzer=lambda source_id, duration: build_shot_structure_result(
                    source_id, duration, ()
                ),
            )
            changed = ShotDetectionConfig(threshold_percent=12)
            spec = SceneWorkSpec(
                project.id,
                SHOT_EVIDENCE,
                shot_input_fingerprint(source),
                shot_config_fingerprint(changed),
                "shot-structure",
                SHOT_DETECTOR_VERSION,
                source.id,
            )
            plan = determine_scene_resume_plan(session, (spec,))
            self.assertEqual(plan.execution_specs, (spec,))
            self.assertEqual(plan.downstream_invalidations, ())
            self.assertIn(first.work_item_id, plan.invalid_work_items)

    def test_shot_change_reuses_transcript_audio_and_visual_work(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            for work_type in (TRANSCRIPT_EVIDENCE, AUDIO_EVIDENCE, VISUAL_EVIDENCE):
                session.add(
                    SceneAnalysisWorkItem(
                        project_id=project.id,
                        source_video_id=source.id,
                        work_type=work_type,
                        status=SceneAnalysisWorkStatus.COMPLETED,
                        input_fingerprint=f"{work_type}-input",
                        config_fingerprint=f"{work_type}-config",
                        producer="test",
                        producer_version="v1",
                        result_reference=(
                            '{"schema":"autonomous-modality-result-v0.1","evidences":[]}'
                        ),
                        result_fingerprint=canonical_fingerprint({"evidences": []}),
                    )
                )
            session.commit()
            process_shot_evidence(
                session,
                source.id,
                analyzer=lambda source_id, duration: build_shot_structure_result(
                    source_id, duration, ()
                ),
            )
            specs = tuple(
                SceneWorkSpec(
                    project.id,
                    work_type,
                    f"{work_type}-input",
                    f"{work_type}-config",
                    "test",
                    "v1",
                    source.id,
                )
                for work_type in (TRANSCRIPT_EVIDENCE, AUDIO_EVIDENCE, VISUAL_EVIDENCE)
            ) + (
                SceneWorkSpec(
                    project.id,
                    SHOT_EVIDENCE,
                    shot_input_fingerprint(source),
                    shot_config_fingerprint(ShotDetectionConfig(threshold_percent=12)),
                    "shot-structure",
                    SHOT_DETECTOR_VERSION,
                    source.id,
                ),
            )
            plan = determine_scene_resume_plan(session, specs)
            self.assertEqual(len(plan.reusable_work_items), 3)
            self.assertEqual(plan.execution_specs, (specs[-1],))

    def test_source_fingerprint_change_invalidates_shot_work(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, source = _source(session)
            process_shot_evidence(
                session,
                source.id,
                analyzer=lambda source_id, duration: build_shot_structure_result(
                    source_id, duration, ()
                ),
            )
            source.fingerprint = "changed"
            session.commit()
            spec = SceneWorkSpec(
                project.id,
                SHOT_EVIDENCE,
                shot_input_fingerprint(source),
                shot_config_fingerprint(ShotDetectionConfig()),
                "shot-structure",
                SHOT_DETECTOR_VERSION,
                source.id,
            )
            plan = determine_scene_resume_plan(session, (spec,))
            self.assertEqual(plan.execution_specs, (spec,))

    def test_failure_is_isolated_and_existing_candidate_is_preserved(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            _, source, candidate = _active_candidate(session)

            def failure(source_id, duration):
                raise ShotStructureError("detector failed")

            with self.assertRaises(ShotStructureError):
                process_shot_evidence(session, source.id, analyzer=failure)
            self.assertIsNotNone(session.get(SceneCandidate, candidate.id))
            work = session.scalar(
                select(SceneAnalysisWorkItem).where(
                    SceneAnalysisWorkItem.source_video_id == source.id,
                    SceneAnalysisWorkItem.work_type == SHOT_EVIDENCE,
                )
            )
            self.assertEqual(work.status, SceneAnalysisWorkStatus.FAILED)

    def test_snapshot_change_rejects_stale_result(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            _, source = _source(session)

            def changes_source(source_id, duration):
                session.get(SourceVideo, source_id).fingerprint = "changed-during-analysis"
                session.flush()
                return build_shot_structure_result(source_id, duration, ())

            with self.assertRaises(ShotStructureError):
                process_shot_evidence(session, source.id, analyzer=changes_source)
            work = session.scalar(
                select(SceneAnalysisWorkItem).where(
                    SceneAnalysisWorkItem.source_video_id == source.id,
                    SceneAnalysisWorkItem.work_type == SHOT_EVIDENCE,
                )
            )
            attempt = session.scalar(
                select(SceneAnalysisAttempt).where(
                    SceneAnalysisAttempt.work_item_id == work.id
                )
            )
            self.assertEqual(attempt.safe_error_code, "INPUT_CHANGED_DURING_EXECUTION")


def _source(session: Session):
    project = Project(name="Shot structure", split_policy=EpisodeSplitPolicy.SINGLE)
    source = SourceVideo(
        project=project,
        original_filename="source.mov",
        storage_reference="projects/test/source.mov",
        fingerprint="shot-source",
        fingerprint_algorithm="sha256",
        duration_seconds=Decimal("4.000"),
        processing_status=SourceVideoStatus.COMPLETED,
    )
    session.add(project)
    session.commit()
    return project, source


def _active_candidate(session: Session):
    project, source = _source(session)
    work = SceneAnalysisWorkItem(
        project_id=project.id,
        source_video_id=source.id,
        work_type=AUTONOMOUS_PROMOTION,
        status=SceneAnalysisWorkStatus.COMPLETED,
        input_fingerprint="promotion-input",
        config_fingerprint="promotion-config",
        producer="autonomous-discovery",
        producer_version="v0.1",
        result_reference="autonomous:candidates:1",
        result_fingerprint=canonical_fingerprint({"candidate_ids": ["candidate"]}),
    )
    candidate = SceneCandidate(
        source_video_id=source.id,
        analysis_work_item=work,
        start_seconds=1,
        end_seconds=3,
        discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
        confidence=None,
        input_fingerprint="candidate-input",
        result_fingerprint="candidate-result",
    )
    session.add_all([work, candidate])
    session.flush()
    session.add_all(
        [
            SceneAnalysisWorkResultCandidate(
                work_item_id=work.id, scene_candidate_id=candidate.id
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
    return project, source, candidate
