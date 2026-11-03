"""QA-03 render output SHA-256 integrity: completion, status, preview, download and Range.

Media-free: synthetic bytes, isolated SQLite and temporary output roots only.
"""

from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase, skipUnless
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from starlette.applications import Starlette
from starlette.routing import Route

from backend.app.database import Base
from backend.app.main import app
from backend.app.models import (
    EpisodeSplitPolicy, Project, ProjectRenderRun, ProjectSceneEditPlan, ProjectSceneEditPlanItem,
    SceneAnalysisWorkItem, SceneAnalysisWorkResultCandidate, SceneAnalysisWorkStatus,
    SceneCandidate, SceneDiscoveryMethod, SceneEvidence, SceneEvidenceModality, SourceVideo,
)
from backend.app.routers.verified_file_response import VerifiedFileResponse
from backend.app.services import render_integrity
from backend.app.services.persistent_render_execution import PersistentProjectRenderRunRegistry, utcnow
from backend.app.services.project_render_execution import ProjectRenderRunRegistry
from backend.app.services.project_rendering import ProjectRenderResult
from backend.app.services.render_integrity import (
    IntegrityStatus, OutputIntegrityError, VerifiedFile, is_sha256_hex, verify_file,
)

BASE = bytes(range(256)) * 40          # 10,240 bytes, position-dependent so Range slices are checkable
HARD = b"hard-subtitled synthetic " * 300
SRT = "1\n00:00:00,000 --> 00:00:01,000\n안녕하세요\n".encode("utf-8")


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


class ManualExecutor:
    def __init__(self): self.operations = []
    def submit(self, operation): self.operations.append(operation); return object()
    def run_next(self): self.operations.pop(0)()


class RenderIntegrityApiTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.engine = create_engine(f"sqlite+pysqlite:///{self.root / 'qa03.db'}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        self.addCleanup(self.engine.dispose)
        self.factory = sessionmaker(bind=self.engine, expire_on_commit=False)
        loader = patch("backend.app.main.load_model", return_value=object())
        loader.start(); self.addCleanup(loader.stop)
        context = TestClient(app)
        self.client = context.__enter__(); self.addCleanup(context.__exit__, None, None, None)
        app.state.project_session_factory = self.factory
        self.output = self.root / "outputs"
        app.state.project_render_output_root = self.output
        self.executor = ManualExecutor()
        self.registry = PersistentProjectRenderRunRegistry(self.executor, self.factory, self.output)
        app.state.project_render_run_registry = self.registry
        with self.factory.begin() as session:
            project = Project(name="QA-03", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project); session.flush()
            source = SourceVideo(project_id=project.id, original_filename="mock.mp4",
                                 storage_reference="qa03/mock.mp4", duration_seconds=5)
            session.add(source); session.flush()
            work = SceneAnalysisWorkItem(
                project_id=project.id, source_video_id=source.id, work_type="AUTONOMOUS_PROMOTION",
                status=SceneAnalysisWorkStatus.COMPLETED, input_fingerprint="source", producer="qa03",
                producer_version="1", result_reference="autonomous:candidates:1", result_fingerprint="result")
            session.add(work); session.flush()
            candidate = SceneCandidate(source_video_id=source.id, analysis_work_item_id=work.id,
                                       start_seconds=1, end_seconds=2,
                                       discovery_method=SceneDiscoveryMethod.AUTONOMOUS, input_fingerprint="source")
            session.add(candidate); session.flush()
            session.add_all([
                SceneAnalysisWorkResultCandidate(work_item_id=work.id, scene_candidate_id=candidate.id),
                SceneEvidence(scene_candidate_id=candidate.id, modality=SceneEvidenceModality.AUDIO,
                              evidence_type="AUDIO_ACTIVITY", payload={}, producer="qa03",
                              producer_version="1", source_reference="qa03"),
            ])
            plan = ProjectSceneEditPlan(project_id=project.id)
            plan.items = [ProjectSceneEditPlanItem(position=0, candidate_id=candidate.id)]
            session.add(plan)
            self.project_id, self.candidate_id = project.id, candidate.id

    # -- helpers ---------------------------------------------------------------------------
    def url(self, suffix=""):
        return f"/projects/{self.project_id}{suffix}"

    def directory(self, render_id: UUID) -> Path:
        return self.output / "projects" / self.project_id.hex / "renders" / render_id.hex

    def fake_render(self, **kwargs):
        render_id = kwargs["render_id"]
        directory = self.directory(render_id)
        directory.mkdir(parents=True)
        (directory / "final.mp4").write_bytes(BASE)
        (directory / "final.srt").write_bytes(SRT)
        (directory / "final-subtitled.mp4").write_bytes(HARD)
        return ProjectRenderResult(self.project_id, render_id, directory / "final.mp4", (self.candidate_id,), 1.0,
                                   "h264", "aac", len(BASE), subtitle_path=directory / "final.srt",
                                   hard_subtitle_path=directory / "final-subtitled.mp4")

    def render(self, side_effect=None) -> UUID:
        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=side_effect or self.fake_render):
            response = self.client.post(self.url("/render"))
            self.assertEqual(response.status_code, 202, response.text)
            self.executor.run_next()
        return UUID(response.json()["render_id"])

    def row(self, render_id: UUID) -> ProjectRenderRun:
        with self.factory() as session:
            return session.get(ProjectRenderRun, render_id)

    def base_url(self, render_id): return self.url(f"/renders/{render_id.hex}/download")
    def hard_url(self, render_id): return self.url(f"/renders/{render_id.hex}/subtitled/download")

    def assert_blocked(self, response, status_code, code, *leaked: bytes):
        self.assertEqual(response.status_code, status_code, response.text)
        self.assertEqual(response.json()["detail"]["code"], code)
        self.assertNotEqual(response.headers.get("content-type"), "video/mp4")
        for data in leaked:
            self.assertNotIn(data[:64], response.content)

    # -- completion ------------------------------------------------------------------------
    def test_completion_records_sha256_of_each_actual_output(self):
        render_id = self.render()
        row = self.row(render_id)
        self.assertEqual(row.status, "COMPLETED")
        self.assertEqual((row.base_sha256, row.srt_sha256, row.hard_sha256),
                         (digest(BASE), digest(SRT), digest(HARD)))
        self.assertTrue(all(is_sha256_hex(value) for value in (row.base_sha256, row.srt_sha256, row.hard_sha256)))
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual((state["integrity_status"], state["subtitle_integrity_status"],
                          state["hard_subtitle_integrity_status"]), ("VERIFIED", "VERIFIED", "VERIFIED"))
        self.assertTrue(state["download_available"]); self.assertTrue(state["hard_subtitle_download_available"])
        base = self.client.get(self.base_url(render_id))
        hard = self.client.get(self.hard_url(render_id))
        self.assertEqual((base.status_code, hard.status_code), (200, 200))
        self.assertEqual((base.content, hard.content), (BASE, HARD))
        self.assertEqual(base.headers["etag"], f'"sha256-{digest(BASE)}"')
        self.assertEqual(base.headers["content-type"], "video/mp4")
        self.assertIn("inline", base.headers["content-disposition"])
        self.assertIn("attachment", hard.headers["content-disposition"])

    def test_base_digest_failure_never_publishes_completed(self):
        with patch("backend.app.services.persistent_render_execution.record_output_digest",
                   side_effect=OutputIntegrityError("synthetic")):
            render_id = self.render()
        row = self.row(render_id)
        self.assertNotEqual(row.status, "COMPLETED")
        self.assertEqual(row.status, "RECONCILIATION_REQUIRED")  # existing policy: file left, no auto publish
        self.assertIsNone(row.base_sha256)
        self.assertEqual(self.client.get(self.base_url(render_id)).status_code, 409)

    def test_change_between_hash_and_commit_is_not_completed(self):
        with patch("backend.app.services.persistent_render_execution.same_file", return_value=False):
            render_id = self.render()
        self.assertNotEqual(self.row(render_id).status, "COMPLETED")

    def test_subtitle_digest_failure_drops_only_that_output(self):
        real = render_integrity.record_output_digest

        def flaky(path, size):
            if Path(path).name == "final.srt":
                raise OutputIntegrityError("synthetic")
            return real(path, size)

        with patch("backend.app.services.persistent_render_execution.record_output_digest", side_effect=flaky):
            render_id = self.render()
        row = self.row(render_id)
        self.assertEqual(row.status, "COMPLETED")
        self.assertIsNone(row.srt_relpath); self.assertIsNone(row.srt_sha256)
        self.assertEqual(row.subtitle_error_code, "SUBTITLE_OUTPUT_INVALID")
        self.assertEqual(row.base_sha256, digest(BASE)); self.assertEqual(row.hard_sha256, digest(HARD))
        self.assertEqual(self.client.get(self.base_url(render_id)).content, BASE)

    def test_missing_hard_output_at_completion_keeps_base(self):
        def without_hard(**kwargs):
            result = self.fake_render(**kwargs)
            result.hard_subtitle_path.unlink()
            return result

        render_id = self.render(without_hard)
        row = self.row(render_id)
        self.assertEqual(row.status, "COMPLETED")
        self.assertIsNone(row.hard_sha256)
        self.assertEqual(row.hard_subtitle_error_code, "SUBTITLE_OUTPUT_INVALID")
        self.assertEqual(self.client.get(self.base_url(render_id)).status_code, 200)

    # -- serving policy --------------------------------------------------------------------
    def test_same_size_different_bytes_is_blocked_everywhere(self):
        render_id = self.render()
        tampered = bytes(reversed(BASE))
        self.assertEqual(len(tampered), len(BASE))
        (self.directory(render_id) / "final.mp4").write_bytes(tampered)
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertFalse(state["download_available"])
        self.assertIsNone(state["output"]["download_url"])
        self.assertEqual(state["safe_error_code"], "RENDER_FILE_CORRUPT")
        self.assertEqual(state["integrity_status"], "CORRUPT")
        # Hard MP4 is intact but depends on a verified base (current contract).
        self.assertEqual(state["hard_subtitle_status"], "BASE_UNAVAILABLE")
        self.assertFalse(state["hard_subtitle_download_available"])
        self.assert_blocked(self.client.get(self.base_url(render_id)), 409, "RENDER_FILE_CORRUPT", tampered)
        self.assert_blocked(self.client.get(self.base_url(render_id), headers={"Range": "bytes=0-99"}),
                            409, "RENDER_FILE_CORRUPT", tampered)
        self.assert_blocked(self.client.get(self.hard_url(render_id)), 409, "RENDER_FILE_CORRUPT", HARD)
        history = self.client.get(self.url("/renders")).json()["items"]
        self.assertEqual(history[0]["safe_error_code"], "RENDER_FILE_CORRUPT")
        row = self.row(render_id)
        self.assertEqual(row.status, "COMPLETED")           # record preserved, not FAILED
        self.assertEqual(row.base_sha256, digest(BASE))     # baseline never re-registered
        # Restoring the original bytes restores availability (QA-02 recovery policy).
        (self.directory(render_id) / "final.mp4").write_bytes(BASE)
        self.assertEqual(self.client.get(self.base_url(render_id)).content, BASE)

    def test_different_size_is_corrupt_not_missing(self):
        render_id = self.render()
        (self.directory(render_id) / "final.mp4").write_bytes(BASE + b"x")
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual((state["integrity_status"], state["safe_error_code"]), ("CORRUPT", "RENDER_FILE_CORRUPT"))
        self.assert_blocked(self.client.get(self.base_url(render_id)), 409, "RENDER_FILE_CORRUPT", BASE)

    def test_missing_file_keeps_existing_404_contract(self):
        render_id = self.render()
        (self.directory(render_id) / "final.mp4").unlink()
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual((state["integrity_status"], state["safe_error_code"]), ("MISSING", "RENDER_FILE_MISSING"))
        self.assert_blocked(self.client.get(self.base_url(render_id)), 404, "RENDER_NOT_FOUND")
        self.assert_blocked(self.client.get(self.base_url(render_id), headers={"Range": "bytes=0-9"}),
                            404, "RENDER_NOT_FOUND")
        self.assertEqual(self.row(render_id).status, "COMPLETED")

    def test_hard_subtitle_only_corruption_keeps_base(self):
        render_id = self.render()
        (self.directory(render_id) / "final-subtitled.mp4").write_bytes(HARD.upper())
        state = self.client.get(self.url("/rendering")).json()
        self.assertTrue(state["download_available"])
        self.assertEqual((state["hard_subtitle_status"], state["hard_subtitle_integrity_status"]), ("CORRUPT", "CORRUPT"))
        self.assertIsNone(state["hard_subtitle_download_url"])
        self.assertEqual(self.client.get(self.base_url(render_id)).content, BASE)
        self.assert_blocked(self.client.get(self.hard_url(render_id)), 409, "SUBTITLED_RENDER_CORRUPT", HARD.upper())
        self.assert_blocked(self.client.get(self.hard_url(render_id), headers={"Range": "bytes=0-9"}),
                            409, "SUBTITLED_RENDER_CORRUPT")

    def test_srt_only_corruption_keeps_both_mp4(self):
        render_id = self.render()
        (self.directory(render_id) / "final.srt").write_bytes(SRT.replace(b"1", b"2", 1))
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["subtitle_integrity_status"], "CORRUPT")
        self.assertTrue(state["download_available"]); self.assertTrue(state["hard_subtitle_download_available"])
        self.assertEqual(self.client.get(self.hard_url(render_id)).content, HARD)

    def test_hash_less_historical_row_is_preserved_and_blocked(self):
        render_id = self.render()
        with self.factory.begin() as session:   # simulate a row completed before revision e3a1c9d27b45
            row = session.get(ProjectRenderRun, render_id)
            row.base_sha256 = row.srt_sha256 = row.hard_sha256 = None
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["status"], "COMPLETED")
        self.assertFalse(state["download_available"])
        self.assertEqual((state["integrity_status"], state["safe_error_code"]), ("UNVERIFIED", "RENDER_FILE_UNVERIFIED"))
        self.assertEqual(state["hard_subtitle_status"], "BASE_UNAVAILABLE")
        self.assert_blocked(self.client.get(self.base_url(render_id)), 409, "RENDER_FILE_UNVERIFIED", BASE)
        self.assert_blocked(self.client.get(self.base_url(render_id), headers={"Range": "bytes=0-9"}),
                            409, "RENDER_FILE_UNVERIFIED")
        self.assert_blocked(self.client.get(self.hard_url(render_id)), 409, "RENDER_FILE_UNVERIFIED", HARD)
        row = self.row(render_id)   # no automatic backfill, no status overwrite, files untouched
        self.assertEqual((row.status, row.base_sha256, row.hard_sha256), ("COMPLETED", None, None))
        self.assertEqual((self.directory(render_id) / "final.mp4").read_bytes(), BASE)

    def test_hash_less_hard_subtitle_is_unverified(self):
        render_id = self.render()
        with self.factory.begin() as session:
            session.get(ProjectRenderRun, render_id).hard_sha256 = None
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["hard_subtitle_status"], "UNVERIFIED")
        self.assertEqual(self.client.get(self.base_url(render_id)).status_code, 200)
        self.assert_blocked(self.client.get(self.hard_url(render_id)), 409, "SUBTITLED_RENDER_UNVERIFIED", HARD)

    def test_restart_keeps_digests_and_detects_later_tampering(self):
        render_id = self.render()
        app.state.project_render_run_registry = PersistentProjectRenderRunRegistry(
            ManualExecutor(), self.factory, self.output)
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual((state["render_id"], state["integrity_status"]), (str(render_id), "VERIFIED"))
        self.assertEqual(self.client.get(self.base_url(render_id)).content, BASE)
        (self.directory(render_id) / "final.mp4").write_bytes(b"\0" * len(BASE))
        self.assert_blocked(self.client.get(self.base_url(render_id)), 409, "RENDER_FILE_CORRUPT")

    def test_previous_success_and_latest_failure_display(self):
        first = self.render()
        from backend.app.services.project_rendering import ProjectRenderError
        self.render(ProjectRenderError("CONCAT_FAILED", "synthetic"))
        items = self.client.get(self.url("/renders")).json()["items"]
        self.assertEqual([item["status"] for item in items], ["FAILED", "COMPLETED"])
        self.assertIsNone(items[0]["integrity_status"])
        self.assertEqual(items[1]["integrity_status"], "VERIFIED")
        self.assertEqual(self.client.get(self.base_url(first)).content, BASE)

    # -- HTTP Range ------------------------------------------------------------------------
    def test_range_variants_served_from_verified_handle(self):
        render_id = self.render()
        url = self.base_url(render_id)
        single = self.client.get(url, headers={"Range": "bytes=10-29"})
        self.assertEqual(single.status_code, 206)
        self.assertEqual(single.content, BASE[10:30])
        self.assertEqual(single.headers["content-range"], f"bytes 10-29/{len(BASE)}")
        self.assertEqual(single.headers["accept-ranges"], "bytes")
        suffix = self.client.get(url, headers={"Range": "bytes=-16"})
        self.assertEqual((suffix.status_code, suffix.content), (206, BASE[-16:]))
        multi = self.client.get(url, headers={"Range": "bytes=0-3,100-103"})
        self.assertEqual(multi.status_code, 206)
        self.assertIn("multipart/byteranges", multi.headers["content-type"])
        self.assertIn(BASE[0:4], multi.content); self.assertIn(BASE[100:104], multi.content)
        self.assertEqual(int(multi.headers["content-length"]), len(multi.content))
        self.assertEqual(self.client.get(url, headers={"Range": f"bytes={len(BASE)}-"}).status_code, 416)
        etag = single.headers["etag"]
        matched = self.client.get(url, headers={"Range": "bytes=0-1", "If-Range": etag})
        self.assertEqual(matched.status_code, 206)
        stale = self.client.get(url, headers={"Range": "bytes=0-1", "If-Range": '"sha256-' + "0" * 64 + '"'})
        self.assertEqual((stale.status_code, stale.content), (200, BASE))

    def test_concurrent_range_and_full_requests(self):
        render_id = self.render()
        url = self.base_url(render_id)
        ranges = [(index * 512, index * 512 + 511) for index in range(16)]

        def fetch(span):
            start, end = span
            response = self.client.get(url, headers={"Range": f"bytes={start}-{end}"})
            return response.status_code, response.content == BASE[start:end + 1]

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(fetch, ranges))
            fulls = list(pool.map(lambda _: self.client.get(url).content == BASE, range(4)))
        self.assertEqual(results, [(206, True)] * 16)
        self.assertTrue(all(fulls))


class InMemoryRegistryIntegrityTests(TestCase):
    """The process-local registry (persistence disabled) also refuses unhashed/changed files."""

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def test_completion_attaches_digests_and_missing_file_stays_unservable(self):
        executor = ManualExecutor()
        registry = ProjectRenderRunRegistry(executor)
        project_id, render_id = uuid4(), uuid4()
        base = self.root / "final.mp4"; base.write_bytes(BASE)
        hard = self.root / "final-subtitled.mp4"; hard.write_bytes(HARD)
        missing_srt = self.root / "final.srt"
        result = ProjectRenderResult(project_id, render_id, base, (), 1.0, "h264", "aac", len(BASE),
                                     subtitle_path=missing_srt, hard_subtitle_path=hard)
        self.assertTrue(registry.start(project_id, lambda: result))
        executor.run_next()
        stored = registry.completed_result(project_id, render_id)
        self.assertEqual(stored.file_sha256, digest(BASE))
        self.assertEqual((stored.hard_subtitle_sha256, stored.hard_subtitle_size_bytes), (digest(HARD), len(HARD)))
        self.assertIsNone(stored.subtitle_sha256)


class IntegrityPrimitiveTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "final.mp4"
        self.path.write_bytes(BASE)

    def test_verify_statuses(self):
        self.assertEqual(verify_file(self.path, len(BASE), digest(BASE)).status, IntegrityStatus.VERIFIED)
        self.assertEqual(verify_file(self.path, len(BASE), None).status, IntegrityStatus.UNVERIFIED)
        self.assertEqual(verify_file(self.path, len(BASE), digest(b"other")).status, IntegrityStatus.CORRUPT)
        self.assertEqual(verify_file(self.path, len(BASE) + 1, digest(BASE)).status, IntegrityStatus.CORRUPT)
        self.assertEqual(verify_file(self.path, len(BASE), "Z" * 64).status, IntegrityStatus.CORRUPT)
        self.assertEqual(verify_file(self.path.with_name("none.mp4"), 1, digest(BASE)).status, IntegrityStatus.MISSING)
        self.assertEqual(verify_file(None, 1, digest(BASE)).status, IntegrityStatus.MISSING)

    def test_db_check_constraint_rejects_malformed_digest(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        for bad in ("A" * 64, "a" * 63, "g" * 64, "a" * 65):
            with self.subTest(bad=bad), self.assertRaises(IntegrityError), factory.begin() as session:
                project = Project(name="ck", split_policy=EpisodeSplitPolicy.SINGLE)
                session.add(project); session.flush()
                session.add(ProjectRenderRun(render_id=uuid4(), project_id=project.id, status="COMPLETED",
                                             plan_snapshot=[], plan_fingerprint="x", created_at=utcnow(),
                                             base_sha256=bad))
        with factory.begin() as session:
            project = Project(name="ok", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(project); session.flush()
            session.add(ProjectRenderRun(render_id=uuid4(), project_id=project.id, status="COMPLETED",
                                         plan_snapshot=[], plan_fingerprint="x", created_at=utcnow(),
                                         base_sha256=digest(BASE), srt_sha256=None, hard_sha256=None))
        with factory() as session:
            self.assertEqual(session.scalars(select(ProjectRenderRun.base_sha256)).all(), [digest(BASE)])
        engine.dispose()

    def _serve(self, verified: VerifiedFile) -> TestClient:
        async def endpoint(_request):
            return VerifiedFileResponse(verified, media_type="video/mp4", filename="x.mp4",
                                        content_disposition_type="inline")
        return TestClient(Starlette(routes=[Route("/f", endpoint)]))

    def test_path_replaced_after_verification_serves_verified_bytes_only(self):
        verified = verify_file(self.path, len(BASE), digest(BASE), keep_open=True)
        replacement = self.path.with_name("evil.mp4"); replacement.write_bytes(bytes(len(BASE)))
        try:
            os.replace(replacement, self.path)
            replaced = True
        except PermissionError:
            replaced = False   # Windows: the verified handle denies rename/replace while open
        response = self._serve(verified).get("/f")
        self.assertEqual(response.content, BASE)
        if os.name == "nt":
            self.assertFalse(replaced)
        self.assertIsNone(verified.handle)    # closed after the response

    @skipUnless(os.name == "nt", "Share-mode write denial is Windows-specific")
    def test_windows_handle_denies_writers_while_verified(self):
        verified = verify_file(self.path, len(BASE), digest(BASE), keep_open=True)
        try:
            with self.assertRaises(PermissionError):
                with open(self.path, "r+b") as writer:
                    writer.write(b"X")
        finally:
            verified.close()
        with open(self.path, "r+b") as writer:   # released afterwards
            writer.write(BASE[:1])

    def test_full_body_mismatch_while_streaming_is_aborted_before_last_chunk(self):
        verified = verify_file(self.path, len(BASE), digest(BASE), keep_open=True)
        verified.sha256 = digest(b"something else")  # simulate bytes that changed after the pre-check
        with self.assertRaises(OutputIntegrityError):
            self._serve(verified).get("/f")

    def test_only_verified_handles_can_be_served(self):
        with self.assertRaises(ValueError):
            VerifiedFileResponse(verify_file(self.path, len(BASE), None), media_type="video/mp4",
                                 filename="x.mp4", content_disposition_type="inline")
