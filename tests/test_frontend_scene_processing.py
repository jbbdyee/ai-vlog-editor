from unittest import TestCase
from unittest.mock import patch

import httpx

from frontend.api_client import BackendApiError, BackendConnectionError, VideoEditorApiClient
from frontend.app import _render_project_scene_controls, _render_project_scene_status


PROJECT = "11111111-1111-1111-1111-111111111111"
SOURCE = "22222222-2222-2222-2222-222222222222"


def status(run_status="RUNNING", source_status="COMPLETED"):
    return {"project_id": PROJECT, "run_status": run_status, "total_sources": 1,
            "processed_count": 1, "completed_count": 1, "abstained_count": 0,
            "failed_count": 0, "blocked_count": 0, "skipped_count": 0,
            "safe_error_code": None,
            "sources": [{"source_video_id": SOURCE, "status": source_status,
                         "candidate_count": 1, "safe_error_code": None, "warnings": []}]}


class SceneApiClientTests(TestCase):
    def client(self, handler):
        calls = []
        def capture(request):
            calls.append(f"{request.method} {request.url.path}")
            return handler(request)
        http_client = httpx.Client(transport=httpx.MockTransport(capture))
        self.addCleanup(http_client.close)
        return VideoEditorApiClient(http_client=http_client), calls

    def test_acceptance_202_and_status_read_strip_unknown_fields(self):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(202, json={"project_id": PROJECT, "accepted": True,
                    "status_url": f"/projects/{PROJECT}/scene-processing", "path": "/Users/private"})
            return httpx.Response(200, json={**status(), "path": "/Users/private"})
        client, calls = self.client(handler)
        self.assertTrue(client.start_project_scene_processing(PROJECT)["accepted"])
        result = client.get_project_scene_processing_status(PROJECT)
        self.assertEqual(result["run_status"], "RUNNING")
        self.assertNotIn("/Users/", repr(result))
        self.assertEqual(calls, [f"POST /projects/{PROJECT}/scene-process",
                                 f"GET /projects/{PROJECT}/scene-processing"])

    def test_not_started_is_preserved_after_backend_restart(self):
        client, _ = self.client(lambda _: httpx.Response(200, json={**status("NOT_STARTED"),
            "processed_count": 0, "completed_count": 0, "sources": []}))
        self.assertEqual(client.get_project_scene_processing_status(PROJECT)["run_status"], "NOT_STARTED")

    def test_abstained_source_is_normal_zero_candidate_result(self):
        payload = status("COMPLETED", "ABSTAINED")
        payload.update(completed_count=0, abstained_count=1)
        payload["sources"][0]["candidate_count"] = 0
        client, _ = self.client(lambda _: httpx.Response(200, json=payload))
        result = client.get_project_scene_processing_status(PROJECT)
        self.assertEqual(result["abstained_count"], 1)
        self.assertEqual(result["sources"][0]["candidate_count"], 0)

    def test_missing_project_conflict_and_invalid_id(self):
        for code in (404, 409):
            client, calls = self.client(lambda _: httpx.Response(code))
            with self.assertRaises(BackendApiError) as raised:
                client.start_project_scene_processing(PROJECT)
            self.assertEqual(raised.exception.status_code, code)
            self.assertEqual(len(calls), 1)
        client, calls = self.client(lambda _: httpx.Response(200, json=status()))
        with self.assertRaises(BackendApiError):
            client.get_project_scene_processing_status("../bad")
        self.assertEqual(calls, [])

    def test_connection_error_and_no_retry(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ConnectError("private", request=request)
        client, _ = self.client(fail)
        with self.assertRaises(BackendConnectionError):
            client.start_project_scene_processing(PROJECT)
        self.assertEqual(len(calls), 1)

    def test_reject_malformed_status(self):
        client, _ = self.client(lambda _: httpx.Response(200, json={**status(), "run_status": "WIN"}))
        with self.assertRaises(BackendApiError):
            client.get_project_scene_processing_status(PROJECT)


class ScenePresentationTests(TestCase):
    def test_source_outcomes_distinct_from_run_state(self):
        rows = [{"source_video_id": SOURCE, "status": code, "candidate_count": 0,
                 "safe_error_code": None} for code in
                ("COMPLETED", "ABSTAINED", "FAILED", "BLOCKED", "SKIPPED_V1_INCOMPLETE")]
        with (patch("frontend.app.st.info"), patch("frontend.app.st.caption"),
              patch("frontend.app.st.dataframe") as table):
            _render_project_scene_status({**status(), "sources": rows})
        self.assertEqual([r["상태"] for r in table.call_args.args[0]],
                         ["완료", "후보 없음(정상 기권)", "실패", "실행 차단", "건너뜀(v1 미완료)"])

    def test_restart_unknown_not_success_or_failure(self):
        with (patch("frontend.app.st.info") as info, patch("frontend.app.st.success") as success,
              patch("frontend.app.st.error") as error):
            _render_project_scene_status({"run_status": "NOT_STARTED", "sources": []})
        self.assertIn("재시작", info.call_args.args[0])
        success.assert_not_called()
        error.assert_not_called()

    def test_active_run_disables_start(self):
        class Client:
            def start_project_scene_processing(self, _):
                self.fail("duplicate")
        with (patch("frontend.app.st.session_state", {"scene_processing_status": status()}),
              patch("frontend.app.st.button", return_value=False) as button,
              patch("frontend.app._render_project_scene_status")):
            _render_project_scene_controls(Client(), True, PROJECT)
        self.assertTrue(button.call_args_list[0].kwargs["disabled"])

    def test_terminal_refresh_fetches_candidates_once(self):
        calls = []
        class Client:
            def get_project_scene_processing_status(self, _):
                calls.append("status")
                return status("COMPLETED_WITH_WARNINGS", "FAILED")
            def get_project_scene_candidates(self, _):
                calls.append("candidates")
                return {"project_id": PROJECT, "candidates": []}
            def get_project_scene_edit_plan(self, _):
                calls.append("plan")
                return {"project_id": PROJECT, "candidate_ids": [], "invalid_candidate_ids": []}
        state = {}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[False, True]),
              patch("frontend.app._render_project_scene_status")):
            _render_project_scene_controls(Client(), True, PROJECT)
        self.assertEqual(calls, ["status", "candidates", "plan"])
        self.assertEqual(state["scene_candidates_result"]["candidates"], [])

    def test_start_stores_queued_without_duplicate_call(self):
        calls = []
        class Client:
            def start_project_scene_processing(self, _):
                calls.append("start")
        state = {}
        with (patch("frontend.app.st.session_state", state),
              patch("frontend.app.st.button", side_effect=[True, False]),
              patch("frontend.app.st.success"), patch("frontend.app._render_project_scene_status")):
            _render_project_scene_controls(Client(), True, PROJECT)
        self.assertEqual(calls, ["start"])
        self.assertEqual(state["scene_processing_status"]["run_status"], "QUEUED")
