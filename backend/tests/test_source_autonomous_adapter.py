from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy,
    ProcessingStage,
    ProcessingStageKind,
    ProcessingStageStatus,
    Project,
    SceneAnalysisAttempt,
    SceneAnalysisWorkItem,
    SceneAnalysisWorkStatus,
    SceneCandidate,
    SceneEvidence,
    SceneEvidenceModality,
    SourceVideo,
    SourceVideoStatus,
    Transcript,
)
from backend.app.services.audio_extractor import ExtractedAudio
from backend.app.services.autonomous_discovery import (
    AnalysisInterval,
    AnalysisUnitType,
    ModalityAnalysis,
    SignalEvidence,
)
from backend.app.services.source_autonomous_adapter import (
    SourceAutonomousServices,
    SourceAutonomousStatus,
    process_source_autonomous,
)
from backend.app.storage.processing_workspace import LocalProcessingWorkspace


class _Storage:
    def __init__(self, source_path: Path) -> None:
        self.source_path = source_path
        self.references: list[str] = []

    def resolve(self, reference: str) -> Path:
        self.references.append(reference)
        return self.source_path


class SourceAutonomousAdapterTests(TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite+pysqlite:///{self.root / 'scene.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.source_path = self.root / "original.mov"
        self.source_path.write_bytes(b"fake source, never decoded")
        self.storage = _Storage(self.source_path)
        self.workspace = LocalProcessingWorkspace(self.root / "scene-temporary")
        with self.factory() as session:
            self.project_id, self.source_id = self._new_source(session)
        self.extract_calls = 0
        self.audio_calls = 0
        self.visual_calls = 0

    def _new_source(self, session, *, completed=True, transcript=True):
        project = Project(name="Scene adapter", split_policy=EpisodeSplitPolicy.SINGLE)
        source = SourceVideo(
            project=project,
            original_filename="original.mov",
            storage_reference="projects/internal/source.mov",
            fingerprint="source-sha",
            fingerprint_algorithm="sha256",
            duration_seconds=48,
            processing_status=SourceVideoStatus.COMPLETED if completed else SourceVideoStatus.READY,
        )
        if transcript:
            source.transcript = Transcript(
                text="우와",
                language="ko",
                segments=[{"start_seconds": 16, "end_seconds": 20, "text": "우와", "words": []}],
            )
        for kind in ProcessingStageKind:
            source.processing_stages.append(ProcessingStage(
                stage=kind,
                status=ProcessingStageStatus.COMPLETED if completed else ProcessingStageStatus.PENDING,
            ))
        session.add(project)
        session.commit()
        return project.id, source.id

    def _fact(self, modality, evidence_type):
        unit = AnalysisUnitType.AUDIO_ACTIVITY if modality is SceneEvidenceModality.AUDIO else AnalysisUnitType.VISUAL_ACTIVITY
        return SignalEvidence(
            AnalysisInterval(self.source_id, 16, 20, unit, "fake", "1"),
            modality,
            evidence_type,
            {"measurement": 1},
        )

    def _services(self, *, audio=None, visual=None):
        def extract(source_path, directory):
            self.extract_calls += 1
            self.assertEqual(source_path, self.source_path)
            wav = directory / "fake.wav"
            wav.write_bytes(b"fake wav")
            return ExtractedAudio(source_path, wav, 48, 16_000, 1, "pcm_s16le")

        def analyze_audio(path, **kwargs):
            self.audio_calls += 1
            self.assertTrue(path.is_file())
            return audio() if audio else ModalityAnalysis((self._fact(SceneEvidenceModality.AUDIO, "AUDIO_ACTIVITY"),))

        def analyze_visual(path, **kwargs):
            self.visual_calls += 1
            self.assertEqual(path, self.source_path)
            return visual() if visual else ModalityAnalysis(())

        return SourceAutonomousServices(extract=extract, analyze_audio=analyze_audio, analyze_visual=analyze_visual)

    def _run(self, services, source_id=None):
        with self.factory() as session:
            return process_source_autonomous(
                session=session,
                storage=self.storage,
                scene_workspace=self.workspace,
                source_video_id=source_id or self.source_id,
                services=services,
            )

    def test_candidate_evidence_and_mvp01_api(self):
        result = self._run(self._services())
        self.assertEqual(result.status, SourceAutonomousStatus.COMPLETED)
        self.assertEqual(result.discovery.candidate_intervals, ((16.0, 20.0),))
        with self.factory() as session:
            self.assertEqual(session.query(SceneCandidate).count(), 1)
            self.assertGreater(session.query(SceneEvidence).count(), 0)
            self.assertEqual(session.get(SourceVideo, self.source_id).processing_status, SourceVideoStatus.COMPLETED)
        with patch("backend.app.main.load_model", return_value=object()):
            with TestClient(app) as client:
                app.state.project_session_factory = self.factory
                response = client.get(f"/projects/{self.project_id}/scene-candidates")
                self.assertEqual(response.status_code, 200)
                candidates = response.json()["candidates"]
                self.assertEqual(len(candidates), 1)
                self.assertEqual(candidates[0]["candidate_id"], str(result.discovery.candidate_ids[0]))
                self.assertEqual(candidates[0]["source_video_id"], str(self.source_id))
                self.assertIn({"modality": "AUDIO", "evidence_type": "AUDIO_ACTIVITY", "count": 1}, candidates[0]["evidence"])
                self.assertNotIn("projects/internal", response.text)

    def test_same_input_reuses_work_and_skips_analyzers_and_wav(self):
        services = self._services()
        first = self._run(services)
        with self.factory() as session:
            counts = (session.query(SceneAnalysisWorkItem).count(), session.query(SceneAnalysisAttempt).count(), session.query(SceneCandidate).count())
        second = self._run(services)
        self.assertEqual(first.discovery.candidate_ids, second.discovery.candidate_ids)
        self.assertEqual((self.extract_calls, self.audio_calls, self.visual_calls), (1, 1, 1))
        with self.factory() as session:
            self.assertEqual(counts, (session.query(SceneAnalysisWorkItem).count(), session.query(SceneAnalysisAttempt).count(), session.query(SceneCandidate).count()))

    def test_no_candidate_is_normal_abstain(self):
        result = self._run(self._services(audio=lambda: ModalityAnalysis(())))
        self.assertEqual(result.status, SourceAutonomousStatus.ABSTAINED)
        self.assertEqual(result.discovery.candidate_ids, ())
        with self.factory() as session:
            self.assertEqual(session.query(SceneCandidate).count(), 0)
            self.assertEqual(session.get(SourceVideo, self.source_id).processing_status, SourceVideoStatus.COMPLETED)

    def test_modality_partial_failure_is_durable_and_no_automatic_retry(self):
        def fail():
            raise RuntimeError("private path")
        result = self._run(self._services(audio=fail))
        self.assertEqual(result.status, SourceAutonomousStatus.ABSTAINED)
        self.assertIn("AUDIO_EVIDENCE_FAILED", result.warnings)
        blocked = self._run(self._services())
        self.assertEqual((blocked.status, blocked.safe_error_code), (SourceAutonomousStatus.BLOCKED, "SCENE_RETRY_REQUIRED"))
        self.assertEqual(self.extract_calls, 1)
        with self.factory() as session:
            self.assertTrue(any(work.status is SceneAnalysisWorkStatus.FAILED for work in session.scalars(select(SceneAnalysisWorkItem))))

    def test_all_modalities_unavailable_fails_without_v1_status_change(self):
        with self.factory() as session:
            _, source_id = self._new_source(session, transcript=False)
        result = self._run(self._services(), source_id)
        self.assertEqual((result.status, result.safe_error_code), (SourceAutonomousStatus.BLOCKED, "V1_ANALYSIS_INCOMPLETE"))
        self.assertEqual(self.storage.references, [])

    def test_visual_and_audio_failures_keep_safe_error_and_v1_completion(self):
        def fail():
            raise RuntimeError("private detail")
        with self.factory() as session:
            session.get(SourceVideo, self.source_id).transcript.segments = "invalid"
            session.commit()
        result = self._run(self._services(audio=fail, visual=fail))
        self.assertEqual((result.status, result.safe_error_code), (SourceAutonomousStatus.FAILED, "SCENE_DISCOVERY_FAILED"))
        self.assertNotIn("private", str(result))
        with self.factory() as session:
            self.assertEqual(session.get(SourceVideo, self.source_id).processing_status, SourceVideoStatus.COMPLETED)
            self.assertEqual(session.query(SceneAnalysisAttempt).filter_by(status="FAILED").count(), 3)
        self.assertEqual(self._run(self._services()).status, SourceAutonomousStatus.BLOCKED)

    def test_temporary_wav_cleanup_even_after_failure(self):
        self._run(self._services(audio=lambda: (_ for _ in ()).throw(RuntimeError("fail"))))
        source_directory = self.root / "scene-temporary" / "projects" / self.project_id.hex / "sources" / self.source_id.hex
        self.assertFalse(source_directory.exists())
        self.assertTrue(self.source_path.exists())

    def test_other_project_isolation(self):
        with self.factory() as session:
            other_project_id, other_source_id = self._new_source(session)
        result = self._run(self._services())
        with patch("backend.app.main.load_model", return_value=object()):
            with TestClient(app) as client:
                app.state.project_session_factory = self.factory
                other = client.get(f"/projects/{other_project_id}/scene-candidates")
        self.assertEqual(other.status_code, 200)
        self.assertEqual(other.json()["candidates"], [])
        self.assertNotEqual(other_source_id, self.source_id)
        self.assertEqual(result.status, SourceAutonomousStatus.COMPLETED)

    def test_incomplete_source_does_not_run_analyzers(self):
        with self.factory() as session:
            _, source_id = self._new_source(session, completed=False)
        result = self._run(self._services(), source_id)
        self.assertEqual(result.status, SourceAutonomousStatus.BLOCKED)
        self.assertEqual(self.storage.references, [])

    def test_running_scene_work_blocks_without_auto_retry(self):
        with self.factory() as session:
            session.add(SceneAnalysisWorkItem(project_id=self.project_id, source_video_id=self.source_id, work_type="AUDIO_EVIDENCE", status=SceneAnalysisWorkStatus.RUNNING, input_fingerprint="x", producer="test", producer_version="1"))
            session.commit()
        result = self._run(self._services())
        self.assertEqual((result.status, result.safe_error_code), (SourceAutonomousStatus.BLOCKED, "SCENE_WORK_RUNNING"))
        self.assertEqual(self.storage.references, [])

    def test_missing_analyzer_is_explicitly_blocked(self):
        services = SourceAutonomousServices(analyze_audio=None)  # type: ignore[arg-type]
        result = self._run(services)
        self.assertEqual((result.status, result.safe_error_code), (SourceAutonomousStatus.BLOCKED, "SCENE_ANALYZER_UNAVAILABLE"))
        self.assertEqual(self.storage.references, [])
