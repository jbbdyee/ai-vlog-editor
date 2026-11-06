"""P1 SRT download: status fields and the integrity-checked SRT download contract."""

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from backend.app.main import app
from backend.app.models import EpisodeSplitPolicy, Project
from backend.tests import test_project_render_api as fixtures

SRT = "1\n00:00:00,000 --> 00:00:01,000\n안녕하세요, Cutory!\n\n".encode("utf-8")


class TestSrtDownloadApi(TestCase):
    setUp = fixtures.ProjectRenderApiTests.setUp
    _candidate = fixtures.ProjectRenderApiTests._candidate
    _result = fixtures.ProjectRenderApiTests._result
    _url = fixtures.ProjectRenderApiTests._url

    def _complete(self, result):
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            assert self.client.post(self._url() + "/render").status_code == 202
            self.executor.run_next()

    def _with_srt(self, **fields):
        result = self._result()
        srt = result.output_path.with_name("final.srt")
        srt.write_bytes(SRT)
        return replace(result, subtitle_path=srt, **fields)

    def _srt_url(self, render_id):
        return self._url() + f"/renders/{render_id}/subtitles/download"

    def test_download_success_headers_and_etag(self):
        self._candidate()
        result = self._with_srt()
        self._complete(result)
        status = self.client.get(self._url() + "/rendering").json()
        assert status["subtitle_integrity_status"] == "VERIFIED"
        assert status["subtitle_download_available"] is True
        assert status["subtitle_download_url"] == self._srt_url(result.render_id.hex)
        response = self.client.get(status["subtitle_download_url"])
        assert response.status_code == 200
        assert response.content == SRT
        assert response.headers["content-type"] == "application/x-subrip; charset=utf-8"
        disposition = response.headers["content-disposition"]
        assert disposition.startswith("attachment") and f"{result.render_id.hex}.srt" in disposition
        assert response.headers["etag"] == f'"sha256-{sha256(SRT).hexdigest()}"'
        # Existing MP4 download is unchanged by the new route.
        basic = self.client.get(status["output"]["download_url"])
        assert basic.status_code == 200 and basic.headers["content-type"] == "video/mp4"
        assert basic.content == b"synthetic MP4 bytes"

    def test_range_request(self):
        self._candidate()
        result = self._with_srt()
        self._complete(result)
        partial = self.client.get(self._srt_url(result.render_id.hex), headers={"Range": "bytes=0-1"})
        assert partial.status_code == 206 and partial.content == SRT[:2]

    def test_unavailable_srt_cases(self):
        self._candidate()
        cases = (
            ("none", lambda: self._result()),
            ("generation failed", lambda: replace(self._result(), subtitle_error_code="SUBTITLE_GENERATION_FAILED")),
            ("file never written", lambda: replace(self._result(), subtitle_path=self._result().output_path.with_name("final.srt"))),
        )
        for name, make in cases:
            with self.subTest(case=name):
                result = make()
                self._complete(result)
                status = self.client.get(self._url() + "/rendering").json()
                assert status["subtitle_download_available"] is False
                assert status["subtitle_download_url"] is None
                response = self.client.get(self._srt_url(result.render_id.hex))
                assert response.status_code in (404, 409)
                assert response.json()["detail"]["code"] in ("SUBTITLE_FILE_NOT_FOUND", "SUBTITLE_FILE_UNVERIFIED")
                assert self.client.get(status["output"]["download_url"]).status_code == 200

    def test_missing_after_completion_is_404(self):
        self._candidate()
        result = self._with_srt()
        self._complete(result)
        result.subtitle_path.unlink()
        status = self.client.get(self._url() + "/rendering").json()
        assert status["subtitle_integrity_status"] == "MISSING"
        assert status["subtitle_download_available"] is False
        response = self.client.get(self._srt_url(result.render_id.hex))
        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "SUBTITLE_FILE_NOT_FOUND"

    def test_corrupt_srt_is_blocked_but_mp4_still_served(self):
        self._candidate()
        result = self._with_srt()
        self._complete(result)
        result.subtitle_path.write_bytes(SRT.replace("Cutory".encode(), "Cutorz".encode()))  # same size, other digest
        status = self.client.get(self._url() + "/rendering").json()
        assert status["subtitle_integrity_status"] == "CORRUPT"
        assert status["subtitle_download_available"] is False and status["subtitle_download_url"] is None
        response = self.client.get(self._srt_url(result.render_id.hex))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "SUBTITLE_FILE_CORRUPT"
        assert self.client.get(status["output"]["download_url"]).status_code == 200

    def test_unverified_srt_is_not_served(self):
        self._candidate()
        result = self._with_srt()
        self._complete(result)
        registry = app.state.project_render_run_registry
        stored = registry.completed_result(self.project_id, result.render_id)
        with patch.object(registry, "completed_result", return_value=replace(stored, subtitle_sha256=None)):
            response = self.client.get(self._srt_url(result.render_id.hex))
        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "SUBTITLE_FILE_UNVERIFIED"

    def test_incomplete_unknown_foreign_and_invalid_ids(self):
        self._candidate()
        result = self._with_srt()
        url = self._srt_url(result.render_id.hex)
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            assert self.client.post(self._url() + "/render").status_code == 202
            queued = self.client.get(self._url() + "/rendering").json()
            assert queued["subtitle_download_available"] is False and queued["subtitle_download_url"] is None
            pending = self.client.get(url)
            assert pending.status_code == 409 and pending.json()["detail"]["code"] == "RENDER_NOT_COMPLETED"
            self.executor.run_next()
        assert self.client.get(url).status_code == 200
        assert self.client.get(self._srt_url(uuid4().hex)).json()["detail"]["code"] == "RENDER_NOT_FOUND"
        assert self.client.get(f"/projects/{uuid4()}/renders/{result.render_id.hex}/subtitles/download").status_code == 404
        with self.factory() as session:
            other = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(other)
            session.commit()
            other_id = other.id
        assert self.client.get(f"/projects/{other_id}/renders/{result.render_id.hex}/subtitles/download").status_code == 404
        for fragment in ("..%2F.env", "bad.srt", f"{result.render_id.hex}%2F..", result.render_id.hex.upper()):
            assert self.client.get(self._url() + f"/renders/{fragment}/subtitles/download").status_code == 422

    def test_recorded_path_outside_render_directory_is_not_served(self):
        self._candidate()
        result = self._result()
        elsewhere = Path(self.root) / "elsewhere.srt"
        elsewhere.write_bytes(SRT)
        self._complete(replace(result, subtitle_path=elsewhere))
        status = self.client.get(self._url() + "/rendering").json()
        assert status["subtitle_download_available"] is False
        assert self.client.get(self._srt_url(result.render_id.hex)).status_code == 404


from backend.tests import test_persistent_render_api as persistent  # noqa: E402
from backend.app.services.persistent_render_execution import PersistentProjectRenderRunRegistry  # noqa: E402
from backend.app.services.project_rendering import ProjectRenderResult  # noqa: E402


class TestPersistentSrtDownload(TestCase):
    """DB-backed registry (the mode the 8000 server runs): SRT digest survives a registry restart."""

    setUp = persistent.PersistentRenderApiTests.setUp
    url = persistent.PersistentRenderApiTests.url
    fake_result = persistent.PersistentRenderApiTests.fake_result

    def _render_with_srt(self):
        def with_srt(**kwargs):
            result = self.fake_result(**kwargs)
            srt = result.output_path.parent / "final.srt"
            srt.write_bytes(SRT)
            return ProjectRenderResult(**{**result.__dict__, "subtitle_path": srt})

        with patch("backend.app.routers.projects.render_project_edit_plan", side_effect=with_srt):
            response = self.client.post(self.url("/render"))
            self.assertEqual(response.status_code, 202, response.text)
            self.executor.run_next()
        return response.json()["render_id"].replace("-", "")

    def test_srt_download_after_registry_restart(self):
        compact = self._render_with_srt()
        app.state.project_render_run_registry = PersistentProjectRenderRunRegistry(
            persistent.ManualExecutor(), self.factory, self.output)
        state = self.client.get(self.url("/rendering")).json()
        self.assertEqual(state["subtitle_integrity_status"], "VERIFIED")
        self.assertEqual(state["subtitle_download_url"], self.url(f"/renders/{compact}/subtitles/download"))
        response = self.client.get(state["subtitle_download_url"])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, SRT)
        self.assertEqual(response.headers["etag"], f'"sha256-{sha256(SRT).hexdigest()}"')
        history = self.client.get(self.url("/renders")).json()["items"]
        self.assertEqual(history[0]["subtitle_download_url"], state["subtitle_download_url"])
        (self.output / "projects" / self.project_id.hex / "renders" / compact / "final.srt").write_bytes(SRT[:-1] + b"!")
        blocked = self.client.get(state["subtitle_download_url"])
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "SUBTITLE_FILE_CORRUPT")
        self.assertEqual(self.client.get(self.url(f"/renders/{compact}/download")).status_code, 200)
