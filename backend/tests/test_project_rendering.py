"""MVP-05A render engine tests with fake FFmpeg and optional synthetic media."""

from pathlib import Path
import shutil
import subprocess
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from uuid import UUID, uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectSceneEditPlan, ProjectSceneEditPlanItem,
    SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus,
    SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.services.clip_renderer import RenderedClip
from backend.app.services.media_probe import MediaInfo, probe_media
from backend.app.services.project_rendering import ProjectRenderError, render_project_edit_plan
from backend.app.storage.source_storage import LocalSourceStorage


class ProjectRenderingTests(TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.engine = create_engine(f"sqlite+pysqlite:///{self.root / 'render.db'}")
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.storage_root = self.root / "originals"
        self.storage = LocalSourceStorage(self.storage_root)
        self.project_id = self.project()
        self.rendered_clips = []
        self.source_paths = []

    def project(self):
        with self.factory() as session:
            project = Project(name="render", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project)
            session.commit()
            return project.id

    def candidate(self, project_id=None, *, start=1, end=2, source_duration=10, source_file=None):
        project_id = project_id or self.project_id
        reference = f"projects/{project_id.hex}/sources/{uuid4().hex}.mp4"
        path = self.storage_root / reference
        path.parent.mkdir(parents=True, exist_ok=True)
        if source_file is None:
            path.write_bytes(b"synthetic source, not decoded")
        else:
            shutil.copyfile(source_file, path)
        self.source_paths.append(path)
        with self.factory() as session:
            source = SourceVideo(project_id=project_id, original_filename="synthetic.mp4",
                                 storage_reference=reference, duration_seconds=source_duration)
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
                start_seconds=start, end_seconds=end,
                discovery_method=SceneDiscoveryMethod.AUTONOMOUS, input_fingerprint="test",
            )
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

    def plan(self, ids):
        with self.factory() as session:
            plan = ProjectSceneEditPlan(project_id=self.project_id)
            plan.items = [ProjectSceneEditPlanItem(position=i, candidate_id=value)
                          for i, value in enumerate(ids)]
            session.add(plan)
            session.commit()

    def fake_render_one(self, source, candidate, output, *, ffmpeg_executable):
        clip_path = Path(output) / f"{uuid4().hex}.mp4"
        clip_path.write_bytes(b"fake clip")
        self.rendered_clips.append(clip_path)
        return RenderedClip(Path(source), clip_path, candidate.start_seconds,
                            candidate.end_seconds, candidate.end_seconds - candidate.start_seconds,
                            "h264", "aac")

    @staticmethod
    def fake_probe(path):
        return MediaInfo(10, True, True, "h264", "aac", "mov,mp4")

    @staticmethod
    def fake_ffmpeg(command, **_):
        Path(command[-1]).write_bytes(b"final mp4")
        return subprocess.CompletedProcess(command, 0)

    def render(self, **kwargs):
        return render_project_edit_plan(
            session_factory=self.factory, source_storage=self.storage,
            project_id=self.project_id, output_root=self.root / "output",
            render_one=self.fake_render_one, inspect_media=self.fake_probe,
            run_ffmpeg=self.fake_ffmpeg, **kwargs,
        )

    def test_single_scene_and_source_preservation_and_temp_cleanup(self):
        selected = self.candidate()
        self.plan([selected])
        result = self.render()
        self.assertEqual(result.candidate_ids, (selected,))
        self.assertTrue(result.output_path.is_file())
        self.assertEqual(result.file_size_bytes, 9)
        self.assertTrue(all(path.is_file() for path in self.source_paths))
        self.assertTrue(all(not path.exists() for path in self.rendered_clips))
        with self.factory() as session:
            self.assertEqual(session.query(ProjectSceneEditPlanItem).count(), 1)

    def test_multi_source_follows_saved_order(self):
        first = self.candidate(start=1, end=2)
        second = self.candidate(start=3, end=4)
        self.plan([second, first])
        result = self.render()
        self.assertEqual(result.candidate_ids, (second, first))

    def test_empty_plan_is_explicit(self):
        with self.assertRaises(ProjectRenderError) as raised:
            self.render()
        self.assertEqual(raised.exception.code, "EMPTY_EDIT_PLAN")
        self.assertFalse((self.root / "output").exists())

    def test_invalid_interval_and_missing_source(self):
        selected = self.candidate(start=2, end=5, source_duration=4)
        self.plan([selected])
        with self.assertRaises(ProjectRenderError) as raised:
            self.render()
        self.assertEqual(raised.exception.code, "INTERVAL_INVALID")

    def test_invalidated_candidate_is_not_substituted(self):
        selected = self.candidate()
        self.plan([selected])
        with self.factory() as session:
            candidate = session.get(SceneCandidate, selected)
            session.get(SceneAnalysisWorkItem, candidate.analysis_work_item_id).status = SceneAnalysisWorkStatus.FAILED
            session.commit()
        with self.assertRaises(ProjectRenderError) as raised:
            self.render()
        self.assertEqual(raised.exception.code, "PLAN_CANDIDATE_CONFLICT")

    def test_other_project_candidate_is_rejected(self):
        other = self.candidate(self.project(), start=1, end=2)
        self.plan([other])
        with self.assertRaises(ProjectRenderError) as raised:
            self.render()
        self.assertEqual(raised.exception.code, "PLAN_CANDIDATE_CONFLICT")

    def test_missing_original_is_explicit_and_no_temp_left(self):
        selected = self.candidate()
        self.plan([selected])
        self.source_paths[0].unlink()
        with self.assertRaises(ProjectRenderError) as raised:
            self.render()
        self.assertEqual(raised.exception.code, "SOURCE_MISSING")
        self.assertEqual(list((self.root / "output").rglob("*.mp4")), [])

    def test_ffmpeg_failure_cleans_partial_output_and_segments(self):
        selected = self.candidate()
        self.plan([selected])
        def fail(command, **_):
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1)
        with self.assertRaises(ProjectRenderError) as raised:
            render_project_edit_plan(
                session_factory=self.factory, source_storage=self.storage,
                project_id=self.project_id, output_root=self.root / "output",
                render_one=self.fake_render_one, inspect_media=self.fake_probe,
                run_ffmpeg=fail,
            )
        self.assertEqual(raised.exception.code, "CONCAT_FAILED")
        self.assertTrue(all(not path.exists() for path in self.rendered_clips))
        self.assertEqual(list((self.root / "output").rglob("*.mp4")), [])
        self.assertTrue(self.source_paths[0].is_file())

    def test_output_not_created_is_error(self):
        selected = self.candidate()
        self.plan([selected])
        with self.assertRaises(ProjectRenderError) as raised:
            render_project_edit_plan(
                session_factory=self.factory, source_storage=self.storage,
                project_id=self.project_id, output_root=self.root / "output",
                render_one=self.fake_render_one, inspect_media=self.fake_probe,
                run_ffmpeg=lambda command, **_: subprocess.CompletedProcess(command, 0),
            )
        self.assertEqual(raised.exception.code, "OUTPUT_MISSING")


@skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg tools are unavailable")
class SyntheticProjectRenderTests(ProjectRenderingTests):
    def test_heterogeneous_video_audio_concat(self):
        first = self.root / "first.mp4"
        second = self.root / "second.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=24:d=1.5",
                        "-f", "lavfi", "-i", "sine=frequency=440:duration=1.5",
                        "-c:v", "libx264", "-c:a", "aac", "-shortest", str(first)], check=True)
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=640x360:r=15:d=1.5",
                        "-an", "-c:v", "libx264", str(second)], check=True)
        first_id = self.candidate(start=0.1, end=0.8, source_duration=1.5, source_file=first)
        second_id = self.candidate(start=0.2, end=0.9, source_duration=1.5, source_file=second)
        self.plan([second_id, first_id])
        result = render_project_edit_plan(
            session_factory=self.factory, source_storage=self.storage,
            project_id=self.project_id, output_root=self.root / "output",
        )
        info = probe_media(result.output_path)
        self.assertEqual(result.candidate_ids, (second_id, first_id))
        self.assertTrue(info.has_video_stream and info.has_audio_stream)
        self.assertEqual((info.video_codec, info.audio_codec), ("h264", "aac"))
        self.assertAlmostEqual(info.duration_seconds, 1.4, delta=0.2)
        self.assertTrue(all(path.is_file() for path in self.source_paths))
        self.assertEqual(len(list(result.output_path.parent.glob("segments-*"))), 0)
