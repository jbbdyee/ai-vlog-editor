"""Media-free checks for the preregistered manifest, not GT correctness."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from evaluation.validate_focused_manifest import DATASET_DIR, validate_manifest


class ManifestValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        manifest_dir = self.root / "manifests"
        manifest_dir.mkdir()
        self.manifest = json.loads((DATASET_DIR / "manifests" / "recording-scenarios.json").read_text(encoding="utf-8"))
        for name in ("COVERAGE.md", "README.md"):
            (manifest_dir / name).write_text((DATASET_DIR / "manifests" / name).read_text(encoding="utf-8"), encoding="utf-8")
        self.save()

    def save(self) -> None:
        (self.root / "manifests" / "recording-scenarios.json").write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding="utf-8"
        )

    def codes(self) -> set[str]:
        self.save()
        return {issue.code for issue in validate_manifest(self.root).issues}

    def scenario(self, scenario_id: str) -> dict:
        return next(row for row in self.manifest["scenarios"] if row["scenario_id"] == scenario_id)

    def test_current_contract_passes_without_gt_or_media(self) -> None:
        self.assertEqual(self.codes(), set())
        report = validate_manifest(self.root)
        self.assertEqual((report.project_count, report.scenario_count, report.coverage_count), (3, 18, 46))

    def test_duplicate_and_missing_project_ids(self) -> None:
        self.manifest["projects"][1]["project_id"] = "P1"
        self.assertIn("DUPLICATE_PROJECT_ID", self.codes())
        self.manifest["projects"][1].pop("project_id")
        self.assertIn("MISSING_PROJECT_ID", self.codes())

    def test_duplicate_and_missing_scenario_ids(self) -> None:
        self.manifest["scenarios"][1]["scenario_id"] = "P1-S01"
        self.assertIn("DUPLICATE_SCENARIO_ID", self.codes())
        self.manifest["scenarios"][1].pop("scenario_id")
        self.assertIn("MISSING_SCENARIO_ID", self.codes())

    def test_unknown_project_and_task_coverage(self) -> None:
        self.scenario("P1-S01")["project_id"] = "UNKNOWN"
        self.scenario("P1-S01")["task_coverage"].append("Z99")
        self.assertTrue({"UNKNOWN_PROJECT", "UNKNOWN_COVERAGE_ID"} <= self.codes())

    def test_duplicate_coverage_id(self) -> None:
        path = self.root / "manifests" / "COVERAGE.md"
        path.write_text(path.read_text(encoding="utf-8") + "\n| A1 repeated | COVERED | P1-S01 | duplicate |\n", encoding="utf-8")
        self.assertIn("DUPLICATE_COVERAGE_ID", self.codes())

    def test_invalid_coverage_status(self) -> None:
        path = self.root / "manifests" / "COVERAGE.md"
        path.write_text(path.read_text(encoding="utf-8").replace("| A1 unique JUST_NOW | COVERED |", "| A1 unique JUST_NOW | DONE |"), encoding="utf-8")
        self.assertIn("INVALID_COVERAGE_STATUS", self.codes())

    def test_unknown_coverage_scenario_and_missing_back_reference(self) -> None:
        path = self.root / "manifests" / "COVERAGE.md"
        content = path.read_text(encoding="utf-8").replace("| P1-S01 | 쉬운 control |", "| P9-S99 | 쉬운 control |")
        path.write_text(content, encoding="utf-8")
        self.assertIn("UNKNOWN_COVERAGE_SCENARIO", self.codes())
        self.assertIn("COVERAGE_BACK_REFERENCE", self.codes())

    def test_conditional_case_is_not_required_to_have_manifest_back_reference(self) -> None:
        self.assertNotIn("A5", self.scenario("P1-S06")["task_coverage"])
        self.assertEqual(self.codes(), set())

    def test_unknown_and_cross_project_relation(self) -> None:
        self.scenario("P2-S02")["relation_intent"][0]["with"] = "UNKNOWN"
        self.assertIn("RELATION_REFERENCE", self.codes())
        self.scenario("P2-S02")["relation_intent"][0]["with"] = "P1-S01"
        self.assertIn("CROSS_PROJECT_RELATION", self.codes())

    def test_continuation_and_reaction_direction(self) -> None:
        continuation = self.scenario("P2-S03")["relation_intent"][0]
        continuation["source_scenario_id"], continuation["target_scenario_id"] = (
            continuation["target_scenario_id"], continuation["source_scenario_id"]
        )
        reaction = self.scenario("P2-S04")["relation_intent"][0]
        reaction["source_scenario_id"], reaction["target_scenario_id"] = (
            reaction["target_scenario_id"], reaction["source_scenario_id"]
        )
        self.assertIn("RELATION_DIRECTION", self.codes())

    def test_symmetric_relation_rejects_directional_endpoints(self) -> None:
        self.scenario("P2-S02")["relation_intent"][0]["source_scenario_id"] = "P2-S02"
        self.assertIn("SYMMETRIC_RELATION_DIRECTION", self.codes())

    def test_manifest_version_requires_complete_history(self) -> None:
        self.manifest["manifest_version"] = 4
        self.assertIn("MANIFEST_HISTORY", self.codes())
        self.manifest["manifest_version"] = 0
        self.assertIn("INVALID_MANIFEST_VERSION", self.codes())

    def test_project_must_have_a_scenario(self) -> None:
        self.manifest["projects"].append({"project_id": "P4"})
        self.assertIn("PROJECT_WITHOUT_SCENARIO", self.codes())


if __name__ == "__main__":
    unittest.main()
