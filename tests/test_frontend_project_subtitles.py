"""MVP-06D frontend contract and button states."""

from unittest import TestCase
from unittest.mock import patch

import httpx

from frontend.api_client import BackendApiError, VideoEditorApiClient
from frontend.app import _render_project_render_section
from tests.test_frontend_project_render import CANDIDATE, PROJECT, RENDER, plan, status


def hard_status(kind="AVAILABLE"):
    value = status()
    available = kind == "AVAILABLE"
    value.update({
        "hard_subtitle_status": kind,
        "hard_subtitle_error_code": "SUBTITLE_RENDER_FAILED" if kind == "FAILED" else None,
        "hard_subtitle_download_available": available,
        "hard_subtitle_download_url": (
            f"/projects/{PROJECT}/renders/{RENDER.replace('-', '')}/subtitled/download"
            if available else None),
    })
    return value


class FrontendSubtitleTests(TestCase):
    def test_client_validates_status_and_download(self):
        calls = []
        def handle(request):
            calls.append(request.url.path)
            if request.url.path.endswith("/rendering"):
                return httpx.Response(200, json=hard_status())
            return httpx.Response(200, content=b"hard mp4", headers={"content-type": "video/mp4"})
        with httpx.Client(transport=httpx.MockTransport(handle)) as http:
            client = VideoEditorApiClient(backend_url="http://test", http_client=http)
            self.assertTrue(client.get_project_rendering_status(PROJECT)["hard_subtitle_download_available"])
            self.assertEqual(client.download_project_subtitled_render(PROJECT, RENDER), b"hard mp4")
        self.assertTrue(calls[-1].endswith("/subtitled/download"))
        broken = hard_status()
        broken["hard_subtitle_download_url"] = "/private.mp4"
        with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=broken))) as http:
            with self.assertRaises(BackendApiError):
                VideoEditorApiClient(backend_url="http://test", http_client=http).get_project_rendering_status(PROJECT)

    def test_subtitled_button_disabled_when_unavailable(self):
        for kind in ("NO_SUBTITLES", "NOT_CONFIGURED", "FAILED", "MISSING"):
            with self.subTest(kind=kind):
                state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                         f"project_render_status_{PROJECT}": hard_status(kind)}
                with (patch("frontend.app.st.session_state", state),
                      patch("frontend.app.st.button", return_value=False) as button,
                      patch("frontend.app.st.download_button") as download,
                      patch("frontend.app.st.subheader"), patch("frontend.app.st.success"),
                      patch("frontend.app.st.info"), patch("frontend.app.st.warning")):
                    _render_project_render_section(object(), plan(), True)
                hard_prepare = [c for c in button.call_args_list if c.args[0] == "자막 적용 영상 다운로드 준비"]
                hard_download = [c for c in download.call_args_list if c.args[0] == "자막 적용 영상 다운로드"]
                self.assertTrue(hard_prepare[0].kwargs["disabled"])
                self.assertTrue(hard_download[0].kwargs["disabled"])

    def test_both_downloads_can_be_prepared_independently(self):
        class Client:
            def get_project_rendering_status(self, _):
                return hard_status()
            def download_project_render(self, *_):
                return b"plain"
            def download_project_subtitled_render(self, *_):
                return b"hard"
        state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                 f"project_render_status_{PROJECT}": hard_status()}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[False, False, True, True]),
              patch("frontend.app.st.download_button") as download,
              patch("frontend.app.st.subheader"), patch("frontend.app.st.success")):
            _render_project_render_section(Client(), plan(), True)
        self.assertEqual(state[f"project_render_bytes_{PROJECT}"], (RENDER, b"plain"))
        self.assertEqual(state[f"project_subtitled_bytes_{PROJECT}"], (RENDER, b"hard"))
        self.assertEqual([c.kwargs["data"] for c in download.call_args_list], [b"plain", b"hard"])
        self.assertFalse(download.call_args_list[-1].kwargs["disabled"])
