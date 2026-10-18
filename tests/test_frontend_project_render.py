from unittest import TestCase
from unittest.mock import patch

import httpx

from frontend.api_client import BackendApiError, BackendConnectionError, VideoEditorApiClient
from frontend.app import _render_project_render_section, _render_project_render_status, _render_readiness


PROJECT = "11111111-1111-1111-1111-111111111111"
CANDIDATE = "22222222-2222-2222-2222-222222222222"
RENDER = "33333333-3333-3333-3333-333333333333"
DOWNLOAD = f"/projects/{PROJECT}/renders/{RENDER.replace('-', '')}/download"


def plan(ids=None, invalid=None):
    return {"project_id": PROJECT, "candidate_ids": [CANDIDATE] if ids is None else ids,
            "invalid_candidate_ids": [] if invalid is None else invalid}


def status(state="COMPLETED", available=True):
    complete = state == "COMPLETED"
    return {"project_id": PROJECT, "status": state,
            "render_id": RENDER if complete else None,
            "is_active": state in {"QUEUED", "RUNNING"}, "succeeded": complete,
            "failed": state == "FAILED", "safe_error_code": "CONCAT_FAILED" if state == "FAILED" else None,
            "download_available": complete and available,
            "output": {"filename": "final.mp4", "duration_seconds": 5.0,
                       "file_size_bytes": 10, "video_codec": "h264", "audio_codec": "aac",
                       "download_url": DOWNLOAD if available else None} if complete else None}


class RenderClientTests(TestCase):
    def client(self, handler):
        calls = []
        def capture(request):
            calls.append(f"{request.method} {request.url.path}")
            return handler(request)
        http_client = httpx.Client(transport=httpx.MockTransport(capture))
        self.addCleanup(http_client.close)
        return VideoEditorApiClient(backend_url="http://backend.test", http_client=http_client), calls

    def test_accept_status_and_download_without_paths(self):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(202, json={"project_id": PROJECT, "accepted": True,
                    "status_url": f"/projects/{PROJECT}/rendering", "local_path": "/Users/private"})
            if request.url.path.endswith("/rendering"):
                return httpx.Response(200, json={**status(), "local_path": "/Users/private"})
            return httpx.Response(200, content=b"fake-mp4", headers={"content-type": "video/mp4"})
        client, calls = self.client(handler)
        self.assertTrue(client.start_project_render(PROJECT)["accepted"])
        rendered = client.get_project_rendering_status(PROJECT)
        self.assertEqual(rendered["render_id"], RENDER)
        self.assertTrue(rendered["download_available"])
        self.assertNotIn("/Users/", repr(rendered))
        self.assertEqual(client.download_project_render(PROJECT, RENDER), b"fake-mp4")
        self.assertEqual(calls, [f"POST /projects/{PROJECT}/render",
                                 f"GET /projects/{PROJECT}/rendering", f"GET {DOWNLOAD}"])

    def test_not_started_after_restart_is_not_success(self):
        client, _ = self.client(lambda _: httpx.Response(200, json=status("NOT_STARTED")))
        result = client.get_project_rendering_status(PROJECT)
        self.assertFalse(result["download_available"])
        self.assertIsNone(result["render_id"])

    def test_invalid_response_or_download_target_is_rejected(self):
        client, calls = self.client(lambda _: httpx.Response(200, json={**status(),
            "output": {**status()["output"], "download_url": "/Users/private"}}))
        with self.assertRaises(BackendApiError):
            client.get_project_rendering_status(PROJECT)
        with self.assertRaises(BackendApiError):
            client.download_project_render(PROJECT, "../private")
        self.assertEqual(len(calls), 1)
        malformed, _ = self.client(lambda _: httpx.Response(200, json={**status(), "status": ["COMPLETED"]}))
        with self.assertRaises(BackendApiError):
            malformed.get_project_rendering_status(PROJECT)

    def test_missing_project_conflict_and_download_error_are_safe(self):
        for code in (404, 409):
            client, calls = self.client(lambda _: httpx.Response(code, json={"detail": {"message": "private"}}))
            with self.assertRaises(BackendApiError) as raised:
                client.start_project_render(PROJECT)
            self.assertEqual(raised.exception.status_code, code)
            self.assertNotIn("private", str(raised.exception))
            self.assertEqual(len(calls), 1)
        client, _ = self.client(lambda _: httpx.Response(404))
        with self.assertRaises(BackendApiError) as raised:
            client.download_project_render(PROJECT, RENDER)
        self.assertEqual(raised.exception.status_code, 404)
        empty, _ = self.client(lambda _: httpx.Response(422, json={"detail": {
            "code": "EMPTY_EDIT_PLAN", "message": "The project edit plan is empty."}}))
        with self.assertRaises(BackendApiError) as raised:
            empty.start_project_render(PROJECT)
        self.assertEqual(raised.exception.code, "EMPTY_EDIT_PLAN")
        self.assertEqual(raised.exception.status_code, 422)
        server_error, _ = self.client(lambda _: httpx.Response(500, json={"detail": {
            "code": "RENDER_FAILED", "message": "Download failed."}}))
        with self.assertRaises(BackendApiError) as raised:
            server_error.download_project_render(PROJECT, RENDER)
        self.assertEqual(raised.exception.status_code, 500)

    def test_connection_and_timeout_do_not_retry(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ConnectError("private", request=request)
        client, _ = self.client(fail)
        with self.assertRaises(BackendConnectionError):
            client.start_project_render(PROJECT)
        self.assertEqual(len(calls), 1)


class RenderPresentationTests(TestCase):
    def test_readiness_checks_saved_order_empty_and_invalid(self):
        self.assertIsNone(_render_readiness(plan(), [CANDIDATE]))
        self.assertIn("저장", _render_readiness(plan(), []))
        self.assertIn("비어", _render_readiness(plan([]), []))
        self.assertIn("무효", _render_readiness(plan(invalid=[CANDIDATE]), [CANDIDATE]))

    def test_start_queues_once_and_disables_duplicate(self):
        calls = []
        class Client:
            def start_project_render(self, project_id):
                calls.append(project_id)
        state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE]}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[True, False]) as button,
              patch("frontend.app.st.subheader"), patch("frontend.app.st.success"),
              patch("frontend.app._render_project_render_status")):
            _render_project_render_section(Client(), plan(), True)
        self.assertEqual(calls, [PROJECT])
        self.assertEqual(state[f"project_render_status_{PROJECT}"]["status"], "QUEUED")
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", return_value=False) as button,
              patch("frontend.app.st.subheader"), patch("frontend.app._render_project_render_status")):
            _render_project_render_section(Client(), plan(), True)
        self.assertTrue(button.call_args_list[0].kwargs["disabled"])

    def test_unsaved_empty_and_invalid_never_call_start(self):
        class Client:
            def start_project_render(self, _):
                raise AssertionError("must not start")
        for stored, ordered in ((plan(), []), (plan([]), []),
                                (plan(invalid=[CANDIDATE]), [CANDIDATE])):
            state = {"scene_edit_plan": stored, f"scene_order_{PROJECT}": ordered}
            with (patch("frontend.app.st.session_state", state),
                  patch("frontend.app.st.button", return_value=False) as button,
                  patch("frontend.app.st.subheader"), patch("frontend.app.st.info")):
                _render_project_render_section(Client(), plan(), True)
            self.assertTrue(button.call_args_list[0].kwargs["disabled"])

    def test_refresh_running_failed_and_restart_states(self):
        for state_name in ("RUNNING", "FAILED", "NOT_STARTED"):
            class Client:
                def get_project_rendering_status(self, _):
                    return status(state_name)
            state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE]}
            with (patch("frontend.app.st.session_state", state),
                  patch("frontend.app.st.button", side_effect=[False, True]),
                  patch("frontend.app.st.subheader"), patch("frontend.app.st.info"),
                  patch("frontend.app.st.error"), patch("frontend.app.st.warning")):
                _render_project_render_section(Client(), plan(), True)
            self.assertEqual(state[f"project_render_status_{PROJECT}"]["status"], state_name)
        with (patch("frontend.app.st.info") as info, patch("frontend.app.st.success") as success):
            _render_project_render_status(status("NOT_STARTED"))
        self.assertIn("재시작", info.call_args.args[0])
        success.assert_not_called()

    def test_completed_download_and_error(self):
        class Client:
            def get_project_rendering_status(self, _):
                return status()
            def download_project_render(self, project_id, render_id):
                self.calls.append((project_id, render_id))
                return b"mp4"
            calls = []
        state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                 f"project_render_status_{PROJECT}": status()}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[False, False, True]),
              patch("frontend.app.st.subheader"), patch("frontend.app.st.success"),
              patch("frontend.app.st.download_button") as download):
            _render_project_render_section(Client(), plan(), True)
        self.assertEqual(Client.calls, [(PROJECT, RENDER)])
        self.assertEqual(download.call_args.kwargs["data"], b"mp4")
        self.assertEqual(download.call_args.kwargs["mime"], "video/mp4")
        self.assertEqual(download.call_args.kwargs["file_name"], f"cutory-{RENDER}.mp4")
        class FailedClient(Client):
            def download_project_render(self, *_):
                raise BackendApiError("다운로드 실패")
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[False, False, True]),
              patch("frontend.app.st.subheader"), patch("frontend.app.st.success"),
              patch("frontend.app.st.error") as error,
              patch("frontend.app.st.download_button") as download):
            _render_project_render_section(FailedClient(), plan(), True)
        error.assert_called_once_with("다운로드 실패")
        download.assert_not_called()

    def test_status_lookup_error_clears_stale_completion(self):
        class Client:
            def get_project_rendering_status(self, _):
                raise BackendApiError("상태 확인 실패")
        state = {"scene_edit_plan": plan(), f"scene_order_{PROJECT}": [CANDIDATE],
                 f"project_render_status_{PROJECT}": status()}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[False, True]),
              patch("frontend.app.st.subheader"), patch("frontend.app.st.error"),
              patch("frontend.app.st.warning"), patch("frontend.app.st.download_button") as download):
            _render_project_render_section(Client(), plan(), True)
        self.assertNotIn(f"project_render_status_{PROJECT}", state)
        download.assert_not_called()
