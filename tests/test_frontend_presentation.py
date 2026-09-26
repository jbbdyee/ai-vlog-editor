from unittest import TestCase

from frontend.app import _seconds


class FrontendPresentationTests(TestCase):
    def test_seconds_hides_floating_point_artifact(self) -> None:
        self.assertEqual(_seconds(5.800000000000001), "5.80초")

    def test_seconds_formats_subsecond_artifact_consistently(self) -> None:
        self.assertEqual(_seconds(0.8000000000000007), "0.80초")
