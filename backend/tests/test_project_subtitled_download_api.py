"""MVP-06D status and safe download contract for the optional hard subtitle file."""

from dataclasses import replace
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from uuid import uuid4

from backend.app.models import EpisodeSplitPolicy, Project
from backend.app.routers.projects import _completed_hard_subtitle_file
from backend.tests import test_project_render_api as fixtures


class TestSubtitledDownloadApi(TestCase):
    setUp = fixtures.ProjectRenderApiTests.setUp
    _candidate = fixtures.ProjectRenderApiTests._candidate
    _result = fixtures.ProjectRenderApiTests._result
    _url = fixtures.ProjectRenderApiTests._url

    def _complete(self, result):
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            assert self.client.post(self._url() + "/render").status_code == 202
            self.executor.run_next()

    def test_both_downloads_and_status(self):
        self._candidate()
        result = self._result()
        hard = result.output_path.with_name("final-subtitled.mp4")
        hard.write_bytes(b"subtitled synthetic MP4")
        result = replace(result, hard_subtitle_path=hard)
        self._complete(result)
        status = self.client.get(self._url() + "/rendering").json()
        assert status["hard_subtitle_status"] == "AVAILABLE"
        assert status["hard_subtitle_download_available"] is True
        basic = self.client.get(status["output"]["download_url"])
        subtitled = self.client.get(status["hard_subtitle_download_url"])
        assert basic.status_code == subtitled.status_code == 200
        assert basic.content == b"synthetic MP4 bytes"
        assert subtitled.content == b"subtitled synthetic MP4"
        assert basic.headers["content-type"] == subtitled.headers["content-type"] == "video/mp4"
        assert f'{result.render_id.hex}-subtitled.mp4' in subtitled.headers["content-disposition"]

    def test_no_subtitles_unconfigured_failure_and_missing_file(self):
        self._candidate()
        cases = (
            ({}, "NO_SUBTITLES"),
            ({"subtitle_path": Path("final.srt")}, "NOT_CONFIGURED"),
            ({"hard_subtitle_error_code": "SUBTITLE_RENDER_FAILED"}, "FAILED"),
            ({"subtitle_error_code": "SUBTITLE_GENERATION_FAILED"}, "SUBTITLE_FAILED"),
            ({"hard_subtitle_path": Path("missing.mp4")}, "MISSING"),
        )
        for fields, expected in cases:
            with self.subTest(expected=expected):
                result = replace(self._result(), **fields)
                self._complete(result)
                status = self.client.get(self._url() + "/rendering").json()
                assert status["hard_subtitle_status"] == expected
                assert status["hard_subtitle_download_available"] is False
                assert status["hard_subtitle_download_url"] is None
                assert self.client.get(self._url() + f"/renders/{result.render_id.hex}/subtitled/download").status_code == 404
                assert self.client.get(status["output"]["download_url"]).status_code == 200

    def test_incomplete_unknown_foreign_project_and_unsafe_path(self):
        self._candidate()
        result = self._result()
        url = self._url() + f"/renders/{result.render_id.hex}/subtitled/download"
        with patch("backend.app.routers.projects.render_project_edit_plan", return_value=result):
            assert self.client.post(self._url() + "/render").status_code == 202
            assert self.client.get(url).status_code == 409
            self.executor.run_next()
        assert self.client.get(self._url() + f"/renders/{uuid4().hex}/subtitled/download").status_code == 404
        assert self.client.get(f"/projects/{uuid4()}/renders/{result.render_id.hex}/subtitled/download").status_code == 404
        with self.factory() as session:
            other = Project(name="other", split_policy=EpisodeSplitPolicy.SINGLE)
            session.add(other)
            session.commit()
            other_id = other.id
        assert self.client.get(f"/projects/{other_id}/renders/{result.render_id.hex}/subtitled/download").status_code == 404
        for fragment in ("..%2F.env", "bad.mp4", f"{result.render_id.hex}%2F.."):
            assert self.client.get(self._url() + f"/renders/{fragment}/subtitled/download").status_code == 422
        wrong = result.output_path.with_name("wrong.mp4")
        wrong.write_bytes(b"private")
        from backend.app.main import app
        assert _completed_hard_subtitle_file(app_test_request(app), self.project_id,
                                             replace(result, hard_subtitle_path=wrong)) is None


def app_test_request(app):
    from starlette.requests import Request
    return Request({"type": "http", "app": app})
