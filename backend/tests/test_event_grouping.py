from __future__ import annotations

from datetime import datetime, timezone
from unittest import TestCase
from uuid import UUID, uuid4

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    EpisodeSplitPolicy,
    EventGroup,
    EventGroupMember,
    Project,
    SceneCandidate,
    SceneDiscoveryMethod,
    SceneEvidence,
    SceneEvidenceModality,
    SceneRelation,
    SceneRelationType,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.event_grouping import (
    EVIDENCE_TYPE_OVERLAP,
    EXACT_SOURCE_INTERVAL,
    SOURCE_NEIGHBOR_HINT,
    TRANSCRIPT_OVERLAP,
    CandidateComparisonProjection,
    EventGroupingError,
    PairFilterConfig,
    build_conservative_group_sets,
    build_pair_manifest,
    canonical_candidate_pair,
    persist_relation,
    process_event_grouping,
)


PROJECT_ID = UUID("00000000-0000-0000-0000-000000000701")


class EventPairFilterTests(TestCase):
    def test_canonical_pair_rejects_self_and_orders_uuid(self) -> None:
        high = UUID("ffffffff-ffff-ffff-ffff-ffffffffffff")
        low = UUID("00000000-0000-0000-0000-000000000001")
        self.assertEqual(canonical_candidate_pair(high, low), (low, high))
        with self.assertRaises(EventGroupingError):
            canonical_candidate_pair(low, low)

    def test_manifest_is_deterministic_and_reasons_do_not_create_relations(self) -> None:
        first = _projection(1, source_order=0, text=("공항", "도착"), evidence=("TRANSCRIPT:STRUCTURE",))
        second = _projection(2, source_order=1, text=("공항", "렌터카"), evidence=("TRANSCRIPT:STRUCTURE",))
        manifest = build_pair_manifest((second, first))
        repeated = build_pair_manifest((first, second))
        self.assertEqual(manifest.result_fingerprint, repeated.result_fingerprint)
        self.assertEqual(manifest.possible_pair_count, 1)
        self.assertEqual(manifest.retained_pair_count, 1)
        self.assertEqual(
            set(manifest.retained_pairs[0].blocking_reasons),
            {TRANSCRIPT_OVERLAP, EVIDENCE_TYPE_OVERLAP, SOURCE_NEIGHBOR_HINT},
        )
        self.assertEqual(manifest.retained_pairs[0].left_candidate_id, first.candidate_id)

    def test_exact_duplicate_signal_is_explicit(self) -> None:
        first = _projection(1, source_order=0, source_fingerprint="same")
        second = _projection(2, source_order=4, source_fingerprint="same")
        manifest = build_pair_manifest((first, second))
        self.assertEqual(manifest.retained_pairs[0].blocking_reasons, (EXACT_SOURCE_INTERVAL,))

    def test_cross_project_snapshot_is_rejected(self) -> None:
        first = _projection(1, source_order=0)
        second = CandidateComparisonProjection(
            **{**first.__dict__, "project_id": uuid4(), "candidate_id": uuid4()}
        )
        with self.assertRaises(EventGroupingError):
            build_pair_manifest((first, second))

    def test_incremental_manifest_counts_only_focus_pairs(self) -> None:
        projections = tuple(_projection(index, source_order=index) for index in range(1, 6))
        focus = projections[-1].candidate_id
        manifest = build_pair_manifest(projections, focus_candidate_ids=(focus,))
        self.assertEqual(manifest.possible_pair_count, 4)
        self.assertTrue(all(focus in (pair.left_candidate_id, pair.right_candidate_id) for pair in manifest.retained_pairs))

    def test_scale_filter_avoids_all_pairs(self) -> None:
        projections = tuple(
            _projection(index, source_order=index, text=(f"token{index}",))
            for index in range(1, 601)
        )
        manifest = build_pair_manifest(projections)
        self.assertEqual(manifest.candidate_count, 600)
        self.assertEqual(manifest.possible_pair_count, 179_700)
        self.assertEqual(manifest.retained_pair_count, 599)
        self.assertGreater(manifest.reduction_rate, 0.99)


class ConservativeGroupingTests(TestCase):
    def test_accepted_same_event_fixture_forms_group_and_expands_as_clique(self) -> None:
        a, b, c = uuid4(), uuid4(), uuid4()
        groups, prevented, unassigned = build_conservative_group_sets(
            (a, b, c), ((a, b), (a, c), (b, c))
        )
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {a, b, c})
        self.assertEqual(prevented, 0)
        self.assertEqual(unassigned, ())

    def test_singleton_and_directional_only_candidates_stay_unassigned(self) -> None:
        candidate = uuid4()
        groups, _, unassigned = build_conservative_group_sets((candidate,), ())
        self.assertEqual(groups, ())
        self.assertEqual(unassigned, (candidate,))

    def test_single_bridge_does_not_merge_existing_groups(self) -> None:
        a, b, c, d = (UUID(int=index) for index in range(1, 5))
        groups, prevented, _ = build_conservative_group_sets(
            (a, b, c, d), ((a, b), (c, d), (b, c))
        )
        self.assertEqual({frozenset(group) for group in groups}, {frozenset((a, b)), frozenset((c, d))})
        self.assertEqual(prevented, 1)

    def test_candidate_with_only_one_edge_cannot_expand_group(self) -> None:
        a, b, c = (UUID(int=index) for index in range(1, 4))
        groups, _, unassigned = build_conservative_group_sets((a, b, c), ((a, b), (b, c)))
        self.assertEqual(groups, ((a, b),))
        self.assertEqual(unassigned, (c,))

    def test_candidate_compatible_with_two_groups_is_unassigned(self) -> None:
        a, b, c, d, x = (UUID(int=index) for index in range(1, 6))
        groups, _, unassigned = build_conservative_group_sets(
            (a, b, c, d, x),
            (
                (a, b), (c, d),
                (x, a), (x, b),
                (x, c), (x, d),
            ),
        )
        self.assertEqual({frozenset(group) for group in groups}, {frozenset((a, b)), frozenset((c, d))})
        self.assertEqual(unassigned, (x,))


class EventGroupingPersistenceTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_duplicate_relation_is_canonical_durable_and_idempotent(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=True)
            result = process_event_grouping(session, project.id)
            repeated = process_event_grouping(session, project.id)
            relation = session.scalar(select(SceneRelation))
            self.assertEqual(result.duplicate_relations_added, 1)
            self.assertTrue(repeated.reused)
            self.assertEqual(session.scalar(select(func.count(SceneRelation.id))), 1)
            self.assertEqual(relation.relation_type, SceneRelationType.DUPLICATE)
            self.assertEqual(
                (relation.source_scene_candidate_id, relation.target_scene_candidate_id),
                canonical_candidate_pair(candidates[0].id, candidates[1].id),
            )
            self.assertEqual(result.event_group_ids, ())
            self.assertEqual(len(result.unassigned_candidate_ids), 2)

    def test_reverse_duplicate_persistence_is_suppressed(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=True)
            first, created = persist_relation(
                session, project.id, candidates[0].id, candidates[1].id,
                SceneRelationType.DUPLICATE, producer="test", producer_version="v1",
            )
            reverse, reverse_created = persist_relation(
                session, project.id, candidates[1].id, candidates[0].id,
                SceneRelationType.DUPLICATE, producer="test", producer_version="v1",
            )
            self.assertTrue(created)
            self.assertFalse(reverse_created)
            self.assertEqual(first.id, reverse.id)

    def test_cross_project_relation_is_rejected(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            first_project, first_candidates = _database_graph(session, duplicate=False)
            _, second_candidates = _database_graph(session, duplicate=False)
            with self.assertRaises(EventGroupingError):
                persist_relation(
                    session, first_project.id, first_candidates[0].id, second_candidates[0].id,
                    SceneRelationType.SAME_EVENT, producer="test", producer_version="v1",
                )

    def test_synthetic_accepted_same_event_persists_group_without_label(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=False, count=3)
            for left, right in ((0, 1), (0, 2), (1, 2)):
                persist_relation(
                    session, project.id, candidates[left].id, candidates[right].id,
                    SceneRelationType.SAME_EVENT, producer="synthetic-fixture", producer_version="v1",
                )
            session.commit()
            result = process_event_grouping(session, project.id)
            group = session.get(EventGroup, result.event_group_ids[0])
            self.assertEqual(result.grouped_candidate_count, 3)
            self.assertIsNone(group.label)
            self.assertIsNone(group.summary)
            self.assertEqual(session.scalar(select(func.count(EventGroupMember.id))), 3)

    def test_single_bridge_preserves_two_groups_and_one_current_membership(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=False, count=4)
            for left, right in ((0, 1), (2, 3), (1, 2)):
                persist_relation(
                    session, project.id, candidates[left].id, candidates[right].id,
                    SceneRelationType.SAME_EVENT, producer="synthetic-fixture", producer_version="v1",
                )
            session.commit()
            result = process_event_grouping(session, project.id)
            memberships = session.scalars(select(EventGroupMember)).all()
            self.assertEqual(len(result.event_group_ids), 2)
            self.assertEqual(result.prevented_bridge_merge_count, 1)
            self.assertEqual(len({item.scene_candidate_id for item in memberships}), 4)

    def test_directional_relations_do_not_create_event_groups(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=False, count=3)
            persist_relation(
                session, project.id, candidates[0].id, candidates[1].id,
                SceneRelationType.CONTINUATION, producer="synthetic-fixture", producer_version="v1",
            )
            persist_relation(
                session, project.id, candidates[2].id, candidates[1].id,
                SceneRelationType.REACTION_TO, producer="synthetic-fixture", producer_version="v1",
            )
            session.commit()
            result = process_event_grouping(session, project.id)
            self.assertEqual(result.event_group_ids, ())
            self.assertEqual(len(result.unassigned_candidate_ids), 3)

    def test_changed_candidate_input_creates_new_work_but_not_duplicate_group(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            project, candidates = _database_graph(session, duplicate=False, count=2)
            persist_relation(
                session, project.id, candidates[0].id, candidates[1].id,
                SceneRelationType.SAME_EVENT, producer="synthetic-fixture", producer_version="v1",
            )
            session.commit()
            first = process_event_grouping(session, project.id)
            candidates[0].result_fingerprint = "changed"
            session.commit()
            changed = process_event_grouping(session, project.id)
            self.assertNotEqual(first.grouping_work_item_id, changed.grouping_work_item_id)
            self.assertEqual(session.scalar(select(func.count(EventGroup.id))), 1)


def _projection(
    index: int,
    *,
    source_order: int,
    text: tuple[str, ...] = (),
    evidence: tuple[str, ...] = (),
    source_fingerprint: str | None = None,
) -> CandidateComparisonProjection:
    return CandidateComparisonProjection(
        project_id=PROJECT_ID,
        candidate_id=UUID(int=index),
        source_video_id=UUID(int=10_000 + index),
        start_seconds=10.0,
        end_seconds=15.0,
        discovery_method="AUTONOMOUS",
        candidate_fingerprint=f"candidate-{index}",
        source_fingerprint=source_fingerprint or f"source-{index}",
        bounded_transcript=" ".join(text) or None,
        transcript_tokens=tuple(sorted(text)),
        evidence_keys=tuple(sorted(evidence)),
        available_modalities=tuple(sorted({item.split(":", 1)[0] for item in evidence})),
        source_order=source_order,
    )


def _database_graph(
    session: Session,
    *,
    duplicate: bool,
    count: int = 2,
) -> tuple[Project, list[SceneCandidate]]:
    project = Project(name="Grouping", split_policy=EpisodeSplitPolicy.SINGLE)
    session.add(project)
    session.flush()
    candidates = []
    for index in range(count):
        source = SourceVideo(
            project_id=project.id,
            original_filename=f"source-{index}.mov",
            storage_reference=f"projects/test/source-{index}.mov",
            fingerprint="same-source" if duplicate else f"source-{index}",
            fingerprint_algorithm="sha256",
            duration_seconds=30,
            processing_status=SourceVideoStatus.COMPLETED,
        )
        session.add(source)
        session.flush()
        transcript = Transcript(
            source_video_id=source.id,
            text=f"장면 {index}",
            language="ko",
            segments=[{"start_seconds": 10, "end_seconds": 15, "text": f"장면 {index}"}],
        )
        candidate = SceneCandidate(
            source_video_id=source.id,
            start_seconds=10,
            end_seconds=15,
            discovery_method=SceneDiscoveryMethod.AUTONOMOUS,
            input_fingerprint=f"input-{index}",
            result_fingerprint=f"result-{index}",
        )
        session.add_all([transcript, candidate])
        session.flush()
        session.add(
            SceneEvidence(
                scene_candidate_id=candidate.id,
                modality=SceneEvidenceModality.TRANSCRIPT,
                evidence_type="TRANSCRIPT_STRUCTURE",
                payload={"segment_id": f"segment-{index}"},
                producer="test",
                producer_version="v1",
            )
        )
        candidates.append(candidate)
    session.commit()
    return project, candidates
