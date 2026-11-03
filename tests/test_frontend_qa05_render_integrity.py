"""QA-05: Streamlit handling of QA-03 render integrity states.

The contract tests drive the real FastAPI app (isolated SQLite + temporary output root, reusing the
QA-03 fixture) through the Streamlit API client, so the client is checked against actual server
payloads and 409 bodies rather than hand-written copies. Media-free: synthetic bytes only.
"""

from unittest import TestCase
from unittest.mock import patch

import httpx

from backend.app.models import ProjectRenderRun
from backend.tests import test_qa03_render_integrity as qa03
from frontend.api_client import BackendApiError, VideoEditorApiClient
from frontend.app import (_render_hard_subtitle_status, _render_project_render_section,
                          _render_project_render_status)
from tests.test_frontend_project_render import CANDIDATE, PROJECT, plan
from tests.test_frontend_project_subtitles import hard_status


class StreamlitIntegrityContractTests(TestCase):
    # Reuse the QA-03 backend fixture by composition (inheriting would re-run its tests here).
    setUp = qa03.RenderIntegrityApiTests.setUp
    url = qa03.RenderIntegrityApiTests.url
    directory = qa03.RenderIntegrityApiTests.directory
    fake_render = qa03.RenderIntegrityApiTests.fake_render
    render = qa03.RenderIntegrityApiTests.render

    def streamlit_client(self):
        def forward(request: httpx.Request) -> httpx.Response:
            response = self.client.request(request.method, request.url.path, headers=dict(request.headers))
            return httpx.Response(response.status_code, headers=response.headers, content=response.content)
        http = httpx.Client(transport=httpx.MockTransport(forward))
        self.addCleanup(http.close)
        return VideoEditorApiClient(backend_url="http://backend.test", http_client=http)

    def clear_digests(self, render_id, *columns):
        with self.factory.begin() as session:
            row = session.get(ProjectRenderRun, render_id)
            for column in columns:
                setattr(row, column, None)

    def tamper(self, render_id, name):
        path = self.directory(render_id) / name
        data = bytearray(path.read_bytes()); data[len(data) // 2] ^= 0x01
        path.write_bytes(bytes(data))  # same size, different bytes

    def assert_download_blocked(self, call, code, message_fragment):
        with self.assertRaises(BackendApiError) as raised:
            call()
        self.assertEqual((raised.exception.status_code, raised.exception.code), (409, code))
        self.assertIn(message_fragment, str(raised.exception))
        self.assertNotIn("아직 다운로드 가능한", str(raised.exception))

    def test_verified_render_still_downloads_both_files(self):
        render_id = self.render()
        client = self.streamlit_client()
        state = client.get_project_rendering_status(str(self.project_id))
        self.assertEqual((state["integrity_status"], state["subtitle_integrity_status"],
                          state["hard_subtitle_integrity_status"]), ("VERIFIED",) * 3)
        self.assertEqual(state["hard_subtitle_status"], "AVAILABLE")
        self.assertEqual(client.download_project_render(str(self.project_id), str(render_id)), qa03.BASE)
        self.assertEqual(client.download_project_subtitled_render(str(self.project_id), str(render_id)), qa03.HARD)

    def test_corrupt_base_is_reported_and_never_downloaded(self):
        render_id = self.render()
        self.tamper(render_id, "final.mp4")
        client = self.streamlit_client()
        state = client.get_project_rendering_status(str(self.project_id))  # must not be rejected as malformed
        self.assertEqual((state["status"], state["download_available"], state["integrity_status"],
                          state["safe_error_code"], state["hard_subtitle_status"],
                          state["hard_subtitle_download_available"]),
                         ("COMPLETED", False, "CORRUPT", "RENDER_FILE_CORRUPT", "BASE_UNAVAILABLE", False))
        self.assertIsNone(state["output"]["download_url"])
        self.assert_download_blocked(lambda: client.download_project_render(str(self.project_id), str(render_id)),
                                     "RENDER_FILE_CORRUPT", "일치하지 않아")
        with patch("frontend.app.st.warning") as warning:
            _render_project_render_status(state)
            _render_hard_subtitle_status(state)
        self.assertIn("일치하지 않아", warning.call_args_list[0].args[0])
        self.assertIn("기본 영상을 제공할 수 없어", warning.call_args_list[1].args[0])

    def test_hash_less_base_is_unverified_not_not_ready(self):
        render_id = self.render()
        self.clear_digests(render_id, "base_sha256", "srt_sha256", "hard_sha256")
        client = self.streamlit_client()
        state = client.get_project_rendering_status(str(self.project_id))
        self.assertEqual((state["integrity_status"], state["safe_error_code"], state["hard_subtitle_status"]),
                         ("UNVERIFIED", "RENDER_FILE_UNVERIFIED", "BASE_UNAVAILABLE"))
        self.assert_download_blocked(lambda: client.download_project_render(str(self.project_id), str(render_id)),
                                     "RENDER_FILE_UNVERIFIED", "무결성 기록이 없는")
        with patch("frontend.app.st.warning") as warning:
            _render_project_render_status(state)
        self.assertIn("무결성 기록이 없는", warning.call_args.args[0])

    def test_hard_subtitle_corrupt_or_unverified_keeps_base_download(self):
        for label, change, code, fragment in (
                ("CORRUPT", lambda rid: self.tamper(rid, "final-subtitled.mp4"),
                 "SUBTITLED_RENDER_CORRUPT", "일치하지 않아"),
                ("UNVERIFIED", lambda rid: self.clear_digests(rid, "hard_sha256"),
                 "SUBTITLED_RENDER_UNVERIFIED", "무결성 기록이 없는")):
            with self.subTest(label):
                render_id = self.render()
                change(render_id)
                client = self.streamlit_client()
                state = client.get_project_rendering_status(str(self.project_id))
                self.assertEqual((state["download_available"], state["hard_subtitle_status"],
                                  state["hard_subtitle_download_available"], state["hard_subtitle_download_url"]),
                                 (True, label, False, None))
                self.assertEqual(client.download_project_render(str(self.project_id), str(render_id)), qa03.BASE)
                self.assert_download_blocked(
                    lambda: client.download_project_subtitled_render(str(self.project_id), str(render_id)),
                    code, fragment)
                with patch("frontend.app.st.warning") as warning:
                    _render_hard_subtitle_status(state)
                self.assertIn(fragment, warning.call_args.args[0])

    def test_missing_base_keeps_404_contract(self):
        render_id = self.render()
        (self.directory(render_id) / "final.mp4").unlink()
        client = self.streamlit_client()
        state = client.get_project_rendering_status(str(self.project_id))
        self.assertEqual((state["integrity_status"], state["safe_error_code"]), ("MISSING", "RENDER_FILE_MISSING"))
        with self.assertRaises(BackendApiError) as raised:
            client.download_project_render(str(self.project_id), str(render_id))
        self.assertEqual((raised.exception.status_code, raised.exception.code), (404, "RENDER_NOT_FOUND"))
        with patch("frontend.app.st.warning") as warning:
            _render_project_render_status(state)
        self.assertIn("찾을 수 없습니다", warning.call_args.args[0])


def integrity_status(base="CORRUPT", hard_kind="BASE_UNAVAILABLE"):
    value = hard_status(hard_kind)
    value.update({"download_available": base == "VERIFIED",
                  "safe_error_code": None if base == "VERIFIED" else f"RENDER_FILE_{base}",
                  "integrity_status": base, "subtitle_integrity_status": None,
                  "hard_subtitle_integrity_status": None if hard_kind == "BASE_UNAVAILABLE" else hard_kind})
    if base != "VERIFIED":
        value["output"] = {**value["output"], "download_url": None}
    return value


class StreamlitIntegrityValidationTests(TestCase):
    def client_for(self, payload):
        http = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
        self.addCleanup(http.close)
        return VideoEditorApiClient(backend_url="http://test", http_client=http)

    def test_inconsistent_integrity_payloads_are_rejected(self):
        broken = [
            {**integrity_status(), "integrity_status": "VERIFIED"},              # VERIFIED but not downloadable
            {**integrity_status(), "integrity_status": "TAMPERED"},              # unknown status
            {**integrity_status("VERIFIED", "AVAILABLE"), "hard_subtitle_integrity_status": "CORRUPT"},
            {**integrity_status("VERIFIED", "AVAILABLE"), "hard_subtitle_status": "BASE_UNAVAILABLE",
             "hard_subtitle_download_available": False, "hard_subtitle_download_url": None,
             "hard_subtitle_integrity_status": None},                            # base is available
        ]
        for payload in broken:
            with self.subTest(payload=payload), self.assertRaises(BackendApiError):
                self.client_for(payload).get_project_rendering_status(PROJECT)

    def test_older_server_without_integrity_fields_is_still_accepted(self):
        state = self.client_for(hard_status("AVAILABLE")).get_project_rendering_status(PROJECT)
        self.assertTrue(state["download_available"])
        self.assertIsNone(state["integrity_status"])

    def test_blocked_states_disable_all_download_controls(self):
        for payload in (integrity_status("CORRUPT"), integrity_status("UNVERIFIED")):
            state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                     f"project_render_status_{PROJECT}": payload,
                     f"project_render_bytes_{PROJECT}": (payload["render_id"], b"stale")}
            with (patch("frontend.app.st.session_state", state),
                  patch("frontend.app.st.button", return_value=False) as button,
                  patch("frontend.app.st.download_button") as download,
                  patch("frontend.app.st.subheader"), patch("frontend.app.st.warning") as warning):
                _render_project_render_section(object(), plan(), True)
            labels = [c.args[0] for c in button.call_args_list]
            self.assertNotIn("자막 없는 영상 다운로드 준비", labels)
            self.assertNotIn("자막 적용 영상 다운로드 준비", labels)
            download.assert_not_called()
            self.assertEqual(len(warning.call_args_list), 2)
        for kind in ("CORRUPT", "UNVERIFIED"):
            state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                     f"project_render_status_{PROJECT}": integrity_status("VERIFIED", kind)}
            with (patch("frontend.app.st.session_state", state),
                  patch("frontend.app.st.button", return_value=False) as button,
                  patch("frontend.app.st.download_button") as download,
                  patch("frontend.app.st.subheader"), patch("frontend.app.st.success"),
                  patch("frontend.app.st.warning")):
                _render_project_render_section(object(), plan(), True)
            hard_prepare = [c for c in button.call_args_list if c.args[0] == "자막 적용 영상 다운로드 준비"]
            hard_download = [c for c in download.call_args_list if c.args[0] == "자막 적용 영상 다운로드"]
            self.assertTrue(hard_prepare[0].kwargs["disabled"])
            self.assertTrue(hard_download[0].kwargs["disabled"])
            self.assertEqual(hard_download[0].kwargs["data"], b"")
