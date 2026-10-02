from dataclasses import replace
from unittest import TestCase
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    EditMemo,
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisAttemptStatus,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.memo_guided_discovery import (
    DEFAULT_CONFIG,
    DeterministicSemanticSelector,
    IntentParseStatus,
    MemoAction,
    MemoGuidedDiscoveryError,
    MemoGuidedSearchConfig,
    ProposalType,
    SceneProposal,
    SemanticSelection,
    SelectionStatus,
    SelectionValidationError,
    TemporalReference,
    build_search_region,
    generate_scene_proposals,
    parse_memo_intent,
    process_memo_guided_discovery,
    validate_selection,
)


class MemoGuidedPureLogicTests(TestCase):
    def setUp(self) -> None:
        self.source_id = uuid4()
        self.memo = _memo(matched_reference="방금")

    def test_intent_supports_keep_just_now_and_earlier(self) -> None:
        just_now = parse_memo_intent(self.memo)
        earlier = parse_memo_intent(_memo(matched_reference="아까"))
        self.assertEqual((just_now.action, just_now.temporal_reference), (MemoAction.KEEP, TemporalReference.JUST_NOW))
        self.assertEqual(earlier.temporal_reference, TemporalReference.EARLIER)
        self.assertEqual(just_now.parse_status, IntentParseStatus.SUPPORTED)

    def test_unsupported_action_and_unknown_reference_abstain_at_parse(self) -> None:
        unsupported = parse_memo_intent(_memo(matched_action="지워줘"))
        unknown = parse_memo_intent(_memo(matched_reference="언젠가"))
        self.assertEqual(unsupported.action, MemoAction.UNKNOWN)
        self.assertEqual(unknown.temporal_reference, TemporalReference.UNKNOWN)
        self.assertEqual(unsupported.parse_status, IntentParseStatus.UNSUPPORTED)

    def test_search_regions_use_config_and_clamp_at_source_start(self) -> None:
        just_now = build_search_region(source_video_id=self.source_id, memo_start_seconds=16, duration_seconds=30, reference=TemporalReference.JUST_NOW)
        earlier = build_search_region(source_video_id=self.source_id, memo_start_seconds=150, duration_seconds=200, reference=TemporalReference.EARLIER)
        self.assertEqual((just_now.start_seconds, just_now.end_seconds), (0.0, 16.0))
        self.assertEqual((earlier.start_seconds, earlier.end_seconds), (30.0, 150.0))

    def test_proposals_are_bounded_deduplicated_ordered_and_reproducible(self) -> None:
        region = build_search_region(source_video_id=self.source_id, memo_start_seconds=16, duration_seconds=21, reference=TemporalReference.JUST_NOW)
        segments = [_segment(10, 12, "여행 장면"), _segment(12.5, 15.5, "바다 장면")]
        first = generate_scene_proposals(source_video_id=self.source_id, transcript_segments=segments, search_region=region, duration_seconds=21)
        second = generate_scene_proposals(source_video_id=self.source_id, transcript_segments=segments, search_region=region, duration_seconds=21)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), DEFAULT_CONFIG.proposal_budget)
        self.assertEqual(len({(p.start_seconds, p.end_seconds) for p in first}), len(first))
        self.assertIn(ProposalType.TRANSCRIPT_BLOCK, {p.proposal_type for p in first})
        self.assertIn(ProposalType.FIXED_WINDOW, {p.proposal_type for p in first})
        self.assertIn(ProposalType.CONTEXT_EXPANDED, {p.proposal_type for p in first})

    def test_malformed_segments_fail_instead_of_becoming_arbitrary_intervals(self) -> None:
        region = build_search_region(source_video_id=self.source_id, memo_start_seconds=16, duration_seconds=21, reference=TemporalReference.JUST_NOW)
        with self.assertRaises(MemoGuidedDiscoveryError):
            generate_scene_proposals(source_video_id=self.source_id, transcript_segments=[_segment(12, 10, "bad")], search_region=region, duration_seconds=21)

    def test_selector_selects_unique_nearby_block_and_abstains_on_tie(self) -> None:
        region, proposals = _manifest(self.source_id)
        intent = parse_memo_intent(self.memo)
        selector = DeterministicSemanticSelector()
        selected = selector.select(intent, region, proposals[:1], {"segment-0001": "장면"})
        tied = selector.select(intent, region, proposals, {})
        self.assertEqual(selected.status, SelectionStatus.SELECTED)
        self.assertEqual(tied.status, SelectionStatus.AMBIGUOUS)
        self.assertIsNone(tied.selected_proposal_id)

    def test_selector_reports_no_match_and_earlier_insufficient_evidence(self) -> None:
        region, proposals = _manifest(self.source_id)
        far = tuple(replace(item, end_seconds=10.0, start_seconds=8.0) for item in proposals[:1])
        selector = DeterministicSemanticSelector()
        no_match = selector.select(parse_memo_intent(self.memo), region, far, {})
        earlier_intent = parse_memo_intent(_memo(matched_reference="아까"))
        insufficient = selector.select(earlier_intent, replace(region, reference_type=TemporalReference.EARLIER), proposals, {})
        self.assertEqual(no_match.status, SelectionStatus.NO_MATCH)
        self.assertEqual(insufficient.status, SelectionStatus.INSUFFICIENT_EVIDENCE)

    def test_validator_accepts_manifest_id_and_rejects_unknown_source_range_or_config(self) -> None:
        region, proposals = _manifest(self.source_id)
        proposal = proposals[0]
        selection = DeterministicSemanticSelector().select(parse_memo_intent(self.memo), region, proposals[:1], {})
        self.assertEqual(validate_selection(selection=selection, proposals=proposals[:1], source_video_id=self.source_id, search_region=region, duration_seconds=21, config_fingerprint=proposal.config_fingerprint), proposal)
        for invalid in (
            replace(selection, selected_proposal_id="unknown"),
            selection,
        ):
            with self.assertRaises(SelectionValidationError):
                validate_selection(selection=invalid, proposals=proposals[:1], source_video_id=(uuid4() if invalid is selection else self.source_id), search_region=region, duration_seconds=21, config_fingerprint=proposal.config_fingerprint)
        with self.assertRaises(SelectionValidationError):
            validate_selection(selection=selection, proposals=proposals[:1], source_video_id=self.source_id, search_region=region, duration_seconds=21, config_fingerprint="stale")


class MemoGuidedPersistenceTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_selected_result_persists_candidate_four_evidences_attempt_and_lineage(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            memo = _graph(session, reference="방금")
            result = process_memo_guided_discovery(session, memo.id)
            self.assertEqual(result.selection_status, SelectionStatus.SELECTED)
            candidate = session.get(SceneCandidate, result.candidate_id)
            evidences = session.scalars(select(SceneEvidence).where(SceneEvidence.scene_candidate_id == candidate.id)).all()
            work = session.get(SceneAnalysisWorkItem, result.work_item_id)
            attempt = session.get(SceneAnalysisAttempt, result.attempt_id)
            self.assertEqual(float(candidate.start_seconds), 12.0)
            self.assertEqual(float(candidate.end_seconds), 15.0)
            self.assertIsNone(candidate.confidence)
            self.assertEqual({item.evidence_type for item in evidences}, {"USER_MEMO", "TEMPORAL_REFERENCE", "TRANSCRIPT_MATCH", "SEMANTIC_SELECTION"})
            self.assertEqual((work.target_type, work.target_id, work.status), ("EDIT_MEMO", memo.id, SceneAnalysisWorkStatus.COMPLETED))
            self.assertEqual(attempt.status, SceneAnalysisAttemptStatus.COMPLETED)
            payload_text = str([item.payload for item in evidences])
            self.assertNotIn(memo.transcript_text, payload_text)
            self.assertNotIn("C:\\", payload_text)

    def test_unsupported_input_completes_with_no_candidate(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            memo = _graph(session, action="지워줘")
            result = process_memo_guided_discovery(session, memo.id)
            self.assertEqual(result.selection_status, SelectionStatus.INSUFFICIENT_EVIDENCE)
            self.assertIsNone(result.candidate_id)
            self.assertEqual(session.get(SceneAnalysisWorkItem, result.work_item_id).status, SceneAnalysisWorkStatus.COMPLETED)

    def test_same_memo_is_idempotent_and_does_not_duplicate_candidate_or_evidence(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            memo = _graph(session)
            first = process_memo_guided_discovery(session, memo.id)
            second = process_memo_guided_discovery(session, memo.id)
            self.assertEqual(first.candidate_id, second.candidate_id)
            self.assertEqual(session.query(SceneCandidate).count(), 1)
            self.assertEqual(session.query(SceneEvidence).count(), 4)
            self.assertEqual(session.query(SceneAnalysisWorkItem).count(), 1)

    def test_multiple_memos_create_independent_work_items(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            first = _graph(session)
            second = EditMemo(source_video_id=first.source_video_id, transcript_id=first.transcript_id, start_seconds=18, end_seconds=19, transcript_text="AI야 방금 살려줘", matched_trigger="AI야", matched_reference="방금", matched_action="살려줘", trigger_match_type="exact", trigger_similarity=1)
            session.add(second)
            session.commit()
            process_memo_guided_discovery(session, first.id)
            process_memo_guided_discovery(session, second.id)
            self.assertEqual(session.query(SceneAnalysisWorkItem).count(), 2)

    def test_validator_contract_failure_is_durably_failed_without_candidate(self) -> None:
        class InvalidSelector:
            def select(self, intent, search_region, proposals, transcript_context):
                return SemanticSelection(
                    SelectionStatus.SELECTED,
                    "not-in-manifest",
                    None,
                    "INVALID_TEST_OUTPUT",
                    None,
                )

        with Session(self.engine, expire_on_commit=False) as session:
            memo = _graph(session)
            with self.assertRaises(SelectionValidationError):
                process_memo_guided_discovery(session, memo.id, selector=InvalidSelector())
            work = session.scalar(select(SceneAnalysisWorkItem))
            attempt = session.scalar(select(SceneAnalysisAttempt))
            self.assertEqual(work.status, SceneAnalysisWorkStatus.FAILED)
            self.assertEqual(attempt.status, SceneAnalysisAttemptStatus.FAILED)
            self.assertEqual(attempt.safe_error_code, "MEMO_DISCOVERY_FAILED")
            self.assertEqual(session.query(SceneCandidate).count(), 0)


def _memo(*, matched_action: str = "살려줘", matched_reference: str = "방금") -> EditMemo:
    return EditMemo(id=uuid4(), source_video_id=uuid4(), transcript_id=uuid4(), start_seconds=16, end_seconds=18, transcript_text="AI야 방금 장면 꼭 살려줘", matched_trigger="AI야", matched_reference=matched_reference, matched_action=matched_action, trigger_match_type="exact", trigger_similarity=1)


def _segment(start: float, end: float, text: str) -> dict[str, object]:
    return {"start_seconds": start, "end_seconds": end, "text": text, "words": []}


def _manifest(source_id):
    region = build_search_region(source_video_id=source_id, memo_start_seconds=16, duration_seconds=21, reference=TemporalReference.JUST_NOW)
    config_fp = generate_scene_proposals(source_video_id=source_id, transcript_segments=[_segment(12, 15, "장면")], search_region=region, duration_seconds=21)[0].config_fingerprint
    proposals = tuple(SceneProposal(f"p-{i}", source_id, start, end, ProposalType.TRANSCRIPT_BLOCK, "test", "v1", (f"segment-{i:04d}",), {}, config_fp) for i, (start, end) in enumerate(((12, 15), (13, 15.5)), start=1))
    return region, proposals


def _graph(session: Session, *, action: str = "살려줘", reference: str = "방금") -> EditMemo:
    project = Project(name="Memo discovery", split_policy=EpisodeSplitPolicy.SINGLE)
    source = SourceVideo(project=project, original_filename="source.mov", storage_reference="projects/test/source.mov", fingerprint="abc", fingerprint_algorithm="sha256", duration_seconds=21, processing_status=SourceVideoStatus.COMPLETED)
    transcript = Transcript(source_video=source, text="여행 장면 AI야", language="ko", language_probability=1, segments=[_segment(12, 15, "여행 장면"), _segment(16, 18, "AI야 방금 장면 꼭 살려줘")])
    memo = EditMemo(source_video=source, transcript=transcript, start_seconds=16, end_seconds=18, transcript_text="AI야 방금 장면 꼭 살려줘", matched_trigger="AI야", matched_reference=reference, matched_action=action, trigger_match_type="exact", trigger_similarity=1)
    session.add(project)
    session.commit()
    return memo
