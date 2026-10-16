from unittest import TestCase
from unittest.mock import patch

import httpx

from frontend.api_client import BackendApiError, BackendConnectionError, VideoEditorApiClient
from frontend.app import _load_project_edit_plan, _reconcile_selection_order, _render_project_edit_plan_section


PROJECT = "11111111-1111-1111-1111-111111111111"
FIRST = "22222222-2222-2222-2222-222222222222"
SECOND = "33333333-3333-3333-3333-333333333333"
FOREIGN = "44444444-4444-4444-4444-444444444444"


def candidates():
    return {"project_id": PROJECT, "candidates": [
        {"candidate_id": FIRST, "source_video_id": FOREIGN, "start_seconds": 1.0, "end_seconds": 2.0},
        {"candidate_id": SECOND, "source_video_id": PROJECT, "start_seconds": 3.0, "end_seconds": 4.0},
    ]}


class SceneEditPlanClientTests(TestCase):
    def client(self, handler):
        calls = []
        def capture(request):
            calls.append(request)
            return handler(request)
        http_client = httpx.Client(transport=httpx.MockTransport(capture))
        self.addCleanup(http_client.close)
        return VideoEditorApiClient(http_client=http_client), calls

    def test_get_put_order_and_safe_response(self):
        payload = {"project_id": PROJECT, "candidate_ids": [SECOND, FIRST],
                   "invalid_candidate_ids": [], "private_path": "/Users/private"}
        client, calls = self.client(lambda _: httpx.Response(200, json=payload))
        saved = client.save_project_scene_edit_plan(PROJECT, [SECOND, FIRST])
        self.assertEqual(saved["candidate_ids"], [SECOND, FIRST])
        self.assertNotIn("private_path", saved)
        self.assertEqual(calls[0].method, "PUT")
        self.assertEqual(calls[0].read(), b'{"candidate_ids":["33333333-3333-3333-3333-333333333333","22222222-2222-2222-2222-222222222222"]}')
        self.assertEqual(client.get_project_scene_edit_plan(PROJECT)["candidate_ids"], [SECOND, FIRST])
        self.assertEqual(calls[1].method, "GET")

    def test_conflict_and_invalid_id_do_not_retry(self):
        client, calls = self.client(lambda _: httpx.Response(409))
        with self.assertRaises(BackendApiError) as raised:
            client.save_project_scene_edit_plan(PROJECT, [FIRST])
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(len(calls), 1)
        with self.assertRaises(BackendApiError):
            client.save_project_scene_edit_plan(PROJECT, ["../bad"])
        self.assertEqual(len(calls), 1)

    def test_not_found_and_malformed_response(self):
        missing, _ = self.client(lambda _: httpx.Response(404))
        with self.assertRaises(BackendApiError) as raised:
            missing.get_project_scene_edit_plan(PROJECT)
        self.assertEqual(raised.exception.status_code, 404)
        malformed, _ = self.client(lambda _: httpx.Response(200, json={"project_id": PROJECT, "candidate_ids": [FIRST], "invalid_candidate_ids": [SECOND]}))
        with self.assertRaises(BackendApiError):
            malformed.get_project_scene_edit_plan(PROJECT)

    def test_connection_error_is_safe_and_not_retried(self):
        calls = []
        def fail(request):
            calls.append(request)
            raise httpx.ConnectError("private host", request=request)
        client, _ = self.client(fail)
        with self.assertRaises(BackendConnectionError) as raised:
            client.get_project_scene_edit_plan(PROJECT)
        self.assertNotIn("private", str(raised.exception))
        self.assertEqual(len(calls), 1)


class SceneEditPlanPresentationTests(TestCase):
    def test_selection_and_exclusion_preserve_order(self):
        self.assertEqual(_reconcile_selection_order([SECOND, FIRST], [FIRST]), [FIRST])
        self.assertEqual(_reconcile_selection_order([SECOND], [FIRST, SECOND]), [SECOND, FIRST])

    def test_reload_restores_saved_plan_and_exposes_conflict(self):
        class Client:
            def get_project_scene_edit_plan(self, _):
                return {"project_id": PROJECT, "candidate_ids": [SECOND, FOREIGN, FIRST],
                        "invalid_candidate_ids": [FOREIGN]}
        state = {}
        with patch("frontend.app.st.session_state", state):
            _load_project_edit_plan(Client(), candidates())
        self.assertEqual(state[f"scene_selected_{PROJECT}"], [SECOND, FIRST])
        self.assertEqual(state["scene_edit_plan"]["invalid_candidate_ids"], [FOREIGN])

    def test_save_explicit_order_after_selecting_candidates(self):
        saved = []
        class Client:
            def save_project_scene_edit_plan(self, _, ids):
                saved.append(ids)
                return {"project_id": PROJECT, "candidate_ids": ids, "invalid_candidate_ids": []}
        state = {"scene_edit_plan": {"project_id": PROJECT, "candidate_ids": [], "invalid_candidate_ids": []},
                 f"scene_selected_{PROJECT}": [FIRST, SECOND],
                 f"scene_order_{PROJECT}": [SECOND, FIRST]}
        with (patch("frontend.app.st.session_state", state), patch("frontend.app.st.subheader"),
              patch("frontend.app.st.caption"), patch("frontend.app.st.multiselect", return_value=[FIRST, SECOND]),
              patch("frontend.app.st.selectbox", return_value=SECOND),
              patch("frontend.app.st.button", side_effect=[False, False, True]),
              patch("frontend.app.st.write"), patch("frontend.app.st.success")):
            _render_project_edit_plan_section(Client(), candidates(), True)
        self.assertEqual(saved, [[SECOND, FIRST]])

    def test_zero_candidates_and_api_error_are_distinct(self):
        class Client:
            def save_project_scene_edit_plan(self, _, ids):
                raise BackendApiError("저장 실패")
        state = {"scene_edit_plan": {"project_id": PROJECT, "candidate_ids": [], "invalid_candidate_ids": []}}
        with (patch("frontend.app.st.session_state", state), patch("frontend.app.st.subheader"),
              patch("frontend.app.st.caption"), patch("frontend.app.st.multiselect", return_value=[]),
              patch("frontend.app.st.button", return_value=True), patch("frontend.app.st.info") as info,
              patch("frontend.app.st.error") as error):
            _render_project_edit_plan_section(Client(), {"project_id": PROJECT, "candidates": []}, True)
        info.assert_called()
        error.assert_called_once_with("저장 실패")

    def test_invalid_saved_candidate_requires_explicit_confirmation(self):
        class Client:
            pass
        state = {"scene_edit_plan": {"project_id": PROJECT, "candidate_ids": [FOREIGN],
                                      "invalid_candidate_ids": [FOREIGN]},
                 f"scene_selected_{PROJECT}": [], f"scene_order_{PROJECT}": []}
        with (patch("frontend.app.st.session_state", state), patch("frontend.app.st.subheader"),
              patch("frontend.app.st.caption"), patch("frontend.app.st.warning") as warning,
              patch("frontend.app.st.checkbox", return_value=False),
              patch("frontend.app.st.multiselect", return_value=[]),
              patch("frontend.app.st.info"), patch("frontend.app.st.button", return_value=False) as button):
            _render_project_edit_plan_section(Client(), candidates(), True)
        self.assertIn(FOREIGN, warning.call_args.args[0])
        self.assertTrue(button.call_args.kwargs["disabled"])
