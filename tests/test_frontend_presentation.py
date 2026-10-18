from unittest import TestCase
from unittest.mock import patch
from uuid import UUID

from frontend.api_client import BackendApiError
from frontend.app import _render_project_candidate_results, _render_project_candidates_section, _seconds


class FrontendPresentationTests(TestCase):
    def test_project_lookup_displays_successful_result_for_uppercase_id(self) -> None:
        project_id = "11111111-1111-1111-1111-1111111111aa"

        class SuccessfulClient:
            def get_project_scene_candidates(self, _project_id):
                return {"project_id": project_id, "candidates": []}

        with (
            patch("frontend.app.st.session_state", {}),
            patch("frontend.app.st.subheader"),
            patch("frontend.app.st.caption"),
            patch("frontend.app.st.text_input", return_value=project_id.upper()),
            patch("frontend.app.st.button", return_value=True),
            patch("frontend.app.st.spinner"),
            patch("frontend.app._render_project_scene_controls"),
            patch("frontend.app._render_project_scene_diagnostics"),
            patch("frontend.app._load_project_edit_plan"),
            patch("frontend.app._render_project_edit_plan_section"),
            patch("frontend.app._render_project_candidate_results") as render,
        ):
            _render_project_candidates_section(SuccessfulClient(), True)
        render.assert_called_once_with({"project_id": str(UUID(project_id)), "candidates": []})

    def test_project_lookup_shows_api_error_without_stale_result(self) -> None:
        class FailingClient:
            def get_project_scene_candidates(self, _project_id):
                raise BackendApiError("프로젝트를 찾을 수 없습니다.", status_code=404)

        with (
            patch("frontend.app.st.session_state", {"scene_candidates_result": {"project_id": "old", "candidates": []}}),
            patch("frontend.app.st.subheader"),
            patch("frontend.app.st.caption"),
            patch("frontend.app.st.text_input", return_value="new") as text_input,
            patch("frontend.app.st.button", return_value=True),
            patch("frontend.app.st.spinner") as spinner,
            patch("frontend.app._render_project_scene_controls"),
            patch("frontend.app._render_project_scene_diagnostics"),
            patch("frontend.app._load_project_edit_plan"),
            patch("frontend.app._render_project_edit_plan_section"),
            patch("frontend.app.st.error") as error,
            patch("frontend.app.st.info") as info,
        ):
            spinner.return_value.__enter__.return_value = None
            _render_project_candidates_section(FailingClient(), True)
        text_input.assert_called_once()
        error.assert_called_once_with("프로젝트를 찾을 수 없습니다.")
        info.assert_not_called()

    def test_project_candidates_render_in_api_order_with_duration_and_evidence(self) -> None:
        rows = [
            {"candidate_id": "first", "source_video_id": "source-a", "start_seconds": 8.0, "end_seconds": 10.5, "evidence": [{"modality": "SHOT", "evidence_type": "SHOT_CHANGE", "count": 2}]},
            {"candidate_id": "second", "source_video_id": "source-b", "start_seconds": 1.0, "end_seconds": 2.0, "evidence": []},
        ]
        with patch("frontend.app.st.dataframe") as dataframe:
            _render_project_candidate_results({"candidates": rows})
        rendered = dataframe.call_args.args[0]
        self.assertEqual([row["후보 ID"] for row in rendered], ["first", "second"])
        self.assertEqual(rendered[0]["길이"], "2.50초")
        self.assertEqual(rendered[0]["Evidence"], "SHOT/SHOT_CHANGE (2)")
        self.assertEqual(rendered[1]["Evidence"], "없음")

    def test_project_candidates_empty_state_is_not_error(self) -> None:
        with patch("frontend.app.st.info") as info, patch("frontend.app.st.error") as error:
            _render_project_candidate_results({"candidates": []})
        info.assert_called_once()
        error.assert_not_called()

    def test_seconds_hides_floating_point_artifact(self) -> None:
        self.assertEqual(_seconds(5.800000000000001), "5.80초")

    def test_seconds_formats_subsecond_artifact_consistently(self) -> None:
        self.assertEqual(_seconds(0.8000000000000007), "0.80초")
