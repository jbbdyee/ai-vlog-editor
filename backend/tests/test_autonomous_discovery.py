from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4
import wave

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.app.database import Base
from backend.app.models import (
    EpisodeSplitPolicy,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisWorkItem,
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
    AutonomousConfig,
    ModalityAnalysis,
    SignalEvidence,
    analyze_audio_wav,
    analyze_transcript_structure,
    analyze_visual_video,
    build_promotion_manifest,
    process_autonomous_discovery,
)
from backend.app.services.visual_motion_refiner import _DecodedFrames


class AutonomousPureLogicTests(TestCase):
    def setUp(self) -> None:
        self.source_id = uuid4()

    def test_analysis_interval_rejects_invalid_times(self) -> None:
        with self.assertRaises(ValueError):
            AnalysisInterval(self.source_id, 2, 2, AnalysisUnitType.SILENCE, "test", "v1")

    def test_transcript_structure_and_minimal_korean_reaction_cue(self) -> None:
        result = analyze_transcript_structure(
            source_video_id=self.source_id,
            segments=[_segment(8, 16, "일반 대화"), _segment(16, 20, "우와 대박")],
            duration_seconds=48,
        )
        self.assertEqual(sum(item.evidence_type == "TRANSCRIPT_STRUCTURE" for item in result.evidences), 2)
        reaction = [item for item in result.evidences if item.evidence_type == "TRANSCRIPT_REACTION_CUE"]
        self.assertEqual(len(reaction), 1)
        self.assertEqual(reaction[0].payload["cue_ids"], ["우와", "와", "대박"])
        self.assertNotIn("우와 대박", str(reaction[0].payload))

    def test_audio_pcm_primitive_emits_activity_and_long_silence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "tiny.wav"
            _write_wav(path, [(0, 16_000 * 6), (8_000, 16_000)])
            result = analyze_audio_wav(path, source_video_id=self.source_id, duration_seconds=7)
        types = {item.evidence_type for item in result.evidences}
        self.assertIn("AUDIO_ACTIVITY", types)
        self.assertIn("LONG_SILENCE", types)

    def test_visual_frame_difference_emits_activity_and_static(self) -> None:
        black = bytes([0]) * 16
        white = bytes([255]) * 16
        frames = (black,) * 30 + (white, black, white, black, white)
        with patch(
            "backend.app.services.autonomous_discovery.extract_grayscale_frames",
            return_value=_DecodedFrames(4, 4, frames),
        ):
            result = analyze_visual_video(
                "not-used.mp4",
                source_video_id=self.source_id,
                duration_seconds=7,
                config=AutonomousConfig(static_interval_seconds=3),
            )
        types = {item.evidence_type for item in result.evidences}
        self.assertIn("VISUAL_ACTIVITY", types)
        self.assertIn("STATIC_INTERVAL", types)

    def test_single_signals_abstain_but_cross_modality_overlap_promotes(self) -> None:
        transcript = _fact(self.source_id, 16, 20, SceneEvidenceModality.TRANSCRIPT, "TRANSCRIPT_REACTION_CUE")
        audio = _fact(self.source_id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY")
        visual_only = _fact(self.source_id, 40, 48, SceneEvidenceModality.VISUAL, "VISUAL_ACTIVITY")
        self.assertEqual(build_promotion_manifest([visual_only], duration_seconds=48), ())
        proposals = build_promotion_manifest([transcript, audio, visual_only], duration_seconds=48)
        self.assertEqual([(item.start_seconds, item.end_seconds, item.rule_id) for item in proposals], [(16, 20, "REACTION_CUE_PLUS_AUDIO")])

    def test_same_input_produces_same_manifest(self) -> None:
        facts = [
            _fact(self.source_id, 16, 20, SceneEvidenceModality.TRANSCRIPT, "TRANSCRIPT_REACTION_CUE"),
            _fact(self.source_id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),
        ]
        self.assertEqual(build_promotion_manifest(facts, duration_seconds=48), build_promotion_manifest(facts, duration_seconds=48))


class AutonomousPersistenceTests(TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)

    def tearDown(self) -> None:
        self.engine.dispose()

    def test_synthetic_scenario_promotes_only_supported_interval_and_preserves_quality_facts(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            result = process_autonomous_discovery(
                session,
                source.id,
                audio_analyzer=lambda: ModalityAnalysis((
                    _fact(source.id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),
                    _fact(source.id, 20, 40, SceneEvidenceModality.QUALITY, "LONG_SILENCE"),
                )),
                visual_analyzer=lambda: ModalityAnalysis((
                    _fact(source.id, 20, 40, SceneEvidenceModality.QUALITY, "STATIC_INTERVAL"),
                    _fact(source.id, 40, 48, SceneEvidenceModality.VISUAL, "VISUAL_ACTIVITY"),
                )),
            )
            self.assertEqual(result.candidate_intervals, ((16.0, 20.0),))
            self.assertEqual(result.runtime_quality_count, 2)
            candidate = session.get(SceneCandidate, result.candidate_ids[0])
            evidences = session.scalars(select(SceneEvidence).where(SceneEvidence.scene_candidate_id == candidate.id)).all()
            self.assertEqual(candidate.discovery_method, SceneDiscoveryMethod.AUTONOMOUS)
            self.assertIsNone(candidate.confidence)
            self.assertEqual({item.modality for item in evidences}, {SceneEvidenceModality.TRANSCRIPT, SceneEvidenceModality.AUDIO})
            self.assertNotIn("우와 대박", str([item.payload for item in evidences]))
            self.assertNotIn("C:\\", str([item.payload for item in evidences]))

    def test_partial_failure_completes_promotion_with_warning(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            result = process_autonomous_discovery(
                session,
                source.id,
                audio_analyzer=lambda: (_ for _ in ()).throw(RuntimeError("private path")),
                visual_analyzer=lambda: ModalityAnalysis(()),
            )
            self.assertTrue(result.abstained)
            self.assertIn("AUDIO_EVIDENCE_FAILED", result.warnings)
            self.assertEqual(session.query(SceneCandidate).count(), 0)

    def test_audio_visual_rule_persists_both_modalities(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            result = process_autonomous_discovery(
                session,
                source.id,
                audio_analyzer=lambda: ModalityAnalysis((
                    _fact(source.id, 40, 48, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),
                )),
                visual_analyzer=lambda: ModalityAnalysis((
                    _fact(source.id, 40, 48, SceneEvidenceModality.VISUAL, "VISUAL_ACTIVITY"),
                )),
            )
            evidences = session.scalars(
                select(SceneEvidence).where(
                    SceneEvidence.scene_candidate_id == result.candidate_ids[0]
                )
            ).all()
            self.assertEqual(
                {item.modality for item in evidences},
                {SceneEvidenceModality.AUDIO, SceneEvidenceModality.VISUAL},
            )

    def test_exact_memo_candidate_is_reused_and_high_overlap_is_not_merged(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            exact = SceneCandidate(source_video_id=source.id, start_seconds=16, end_seconds=20, discovery_method=SceneDiscoveryMethod.MEMO_GUIDED, confidence=None, input_fingerprint="memo")
            nearby = SceneCandidate(source_video_id=source.id, start_seconds=16, end_seconds=19, discovery_method=SceneDiscoveryMethod.MEMO_GUIDED, confidence=None, input_fingerprint="memo-near")
            session.add_all([exact, nearby])
            session.commit()
            result = process_autonomous_discovery(session, source.id, audio_analyzer=lambda: ModalityAnalysis((_fact(source.id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),)), visual_analyzer=lambda: ModalityAnalysis(()))
            self.assertEqual(result.candidate_ids, (exact.id,))
            self.assertEqual(result.reused_candidate_count, 1)
            self.assertEqual(session.query(SceneCandidate).count(), 2)
            self.assertEqual(session.get(SceneCandidate, exact.id).discovery_method, SceneDiscoveryMethod.MEMO_GUIDED)
            self.assertGreater(session.query(SceneEvidence).filter_by(scene_candidate_id=exact.id).count(), 0)

    def test_idempotent_rerun_does_not_duplicate_work_candidate_or_evidence(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            audio = lambda: ModalityAnalysis((_fact(source.id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),))
            first = process_autonomous_discovery(session, source.id, audio_analyzer=audio, visual_analyzer=lambda: ModalityAnalysis(()))
            counts = (session.query(SceneAnalysisWorkItem).count(), session.query(SceneAnalysisAttempt).count(), session.query(SceneCandidate).count(), session.query(SceneEvidence).count())
            second = process_autonomous_discovery(session, source.id, audio_analyzer=audio, visual_analyzer=lambda: ModalityAnalysis(()))
            self.assertEqual(first.candidate_ids, second.candidate_ids)
            self.assertEqual(counts, (session.query(SceneAnalysisWorkItem).count(), session.query(SceneAnalysisAttempt).count(), session.query(SceneCandidate).count(), session.query(SceneEvidence).count()))

    def test_audio_config_change_reuses_transcript_and_visual_work(self) -> None:
        with Session(self.engine, expire_on_commit=False) as session:
            source = _graph(session)
            calls = {"audio": 0, "visual": 0}
            def audio():
                calls["audio"] += 1
                return ModalityAnalysis((_fact(source.id, 16, 20, SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),))
            def visual():
                calls["visual"] += 1
                return ModalityAnalysis(())
            process_autonomous_discovery(session, source.id, audio_analyzer=audio, visual_analyzer=visual)
            first_work_count = session.query(SceneAnalysisWorkItem).count()
            process_autonomous_discovery(
                session,
                source.id,
                audio_analyzer=audio,
                visual_analyzer=visual,
                config=AutonomousConfig(long_silence_seconds=7.0),
            )
            self.assertEqual(calls, {"audio": 2, "visual": 1})
            new_works = session.query(SceneAnalysisWorkItem).count() - first_work_count
            self.assertEqual(new_works, 1)  # unchanged Audio result reuses Promotion


def _segment(start, end, text):
    return {"start_seconds": start, "end_seconds": end, "text": text, "words": []}


def _fact(source_id, start, end, modality, evidence_type):
    unit = {
        SceneEvidenceModality.TRANSCRIPT: AnalysisUnitType.TRANSCRIPT_SEGMENT,
        SceneEvidenceModality.AUDIO: AnalysisUnitType.AUDIO_ACTIVITY,
        SceneEvidenceModality.VISUAL: AnalysisUnitType.VISUAL_ACTIVITY,
        SceneEvidenceModality.QUALITY: AnalysisUnitType.STATIC_INTERVAL,
    }[modality]
    return SignalEvidence(AnalysisInterval(source_id, start, end, unit, "test", "v1"), modality, evidence_type, {"measurement": 1})


def _graph(session):
    project = Project(name="Autonomous", split_policy=EpisodeSplitPolicy.SINGLE)
    source = SourceVideo(project=project, original_filename="source.mov", storage_reference="projects/test/source.mov", fingerprint="source-fingerprint", fingerprint_algorithm="sha256", duration_seconds=48, processing_status=SourceVideoStatus.COMPLETED)
    source.transcript = Transcript(text="일반 대화 우와 대박", language="ko", language_probability=1, segments=[_segment(8, 16, "일반 대화"), _segment(16, 20, "우와 대박")])
    session.add(project)
    session.commit()
    return source


def _write_wav(path, sections):
    samples = bytearray()
    for value, count in sections:
        encoded = int(value).to_bytes(2, byteorder="little", signed=True)
        samples.extend(encoded * count)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(bytes(samples))
