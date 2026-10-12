"""Media-free integration and unit checks for the G5-B5 validator."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from evaluation.validate_focused_gt import DATASET_DIR, validate_dataset


class FocusedGTValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "dataset"
        shutil.copytree(DATASET_DIR / "schema", self.root / "schema")
        shutil.copytree(DATASET_DIR / "manifests", self.root / "manifests")
        (self.root / "annotations").mkdir()
        shutil.copy2(DATASET_DIR / "annotations" / "P1-G5-B4-review-notes.md", self.root / "annotations")

    def draft(self, name: str) -> dict:
        return json.loads((DATASET_DIR / "annotations" / name).read_text(encoding="utf-8"))

    def add(self, name: str, document: dict) -> None:
        (self.root / "annotations" / name).write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    def codes(self, mode: str = "draft", **kwargs: object) -> set[str]:
        return {issue.code for issue in validate_dataset(self.root, mode=mode, **kwargs).issues}

    def test_current_eight_drafts_pass_without_media(self) -> None:
        for path in (DATASET_DIR / "annotations").glob("*.draft.json"):
            self.add(path.name, json.loads(path.read_text(encoding="utf-8")))
        result = validate_dataset(self.root)
        self.assertEqual((result.status, result.checked_files), ("PASS", 8))

    def test_schema_rejects_wrong_type(self) -> None:
        row = self.draft("p1-s01-autonomous.draft.json")
        row["target_intervals"][0]["reaction_present"] = "yes"
        self.add("p1-s01-autonomous.draft.json", row)
        self.assertIn("SCHEMA", self.codes())

    def test_interval_exceeds_duration_and_reversed(self) -> None:
        row = self.draft("p1-s01-autonomous.draft.json")
        row["target_intervals"][0]["end_seconds"] = 999
        self.add("p1-s01-autonomous.draft.json", row)
        self.assertIn("INTERVAL_BOUNDS", self.codes())
        row["target_intervals"][0]["start_seconds"] = 10
        row["target_intervals"][0]["end_seconds"] = 9
        self.add("p1-s01-autonomous.draft.json", row)
        self.assertIn("INTERVAL_BOUNDS", self.codes())

    def test_unknown_scenario_and_source_conflict(self) -> None:
        row = self.draft("p1-s01-autonomous.draft.json")
        row["source"]["scenario_id"] = "P1-S99"
        self.add("p1-s01-autonomous.draft.json", row)
        self.assertIn("SCENARIO_REFERENCE", self.codes())
        row["source"]["scenario_id"] = "P1-S01"
        self.add("p1-s01-autonomous.draft.json", row)
        other = self.draft("p1-s02-autonomous.draft.json")
        other["source"]["source_id"] = row["source"]["source_id"]
        self.add("p1-s02-autonomous.draft.json", other)
        self.assertIn("SOURCE_ID_CONFLICT", self.codes())

    def test_selected_take02_review_reference(self) -> None:
        row = self.draft("p1-s03-memo.draft.json")
        row["source"]["source_id"] = "P1-S03-take01"
        self.add("p1-s03-memo.draft.json", row)
        self.assertIn("SELECTED_TAKE_MISMATCH", self.codes())

    def test_no_match_must_have_empty_target(self) -> None:
        row = self.draft("p1-s04-memo.draft.json")
        row["annotations"][0]["target_intervals"] = [{"start_seconds": 1, "end_seconds": 2}]
        self.add("p1-s04-memo.draft.json", row)
        self.assertIn("NO_MATCH_TARGET", self.codes())

    def test_ambiguous_requires_alternatives(self) -> None:
        row = self.draft("p1-s03-memo.draft.json")
        row["annotations"][0]["target_intervals"] = row["annotations"][0]["target_intervals"][:1]
        self.add("p1-s03-memo.draft.json", row)
        self.assertIn("AMBIGUOUS_TARGETS", self.codes())

    def test_selected_proposal_id_and_fingerprint_reference(self) -> None:
        row = self.draft("p1-s03-memo.draft.json")
        item = row["annotations"][0]
        item["expected_outcome"] = "SELECTED"
        item["acceptable_proposal_ids"] = ["P-01"]
        item["proposal_manifest_fingerprint"] = "a" * 64
        self.add("p1-s03-memo.draft.json", row)
        self.assertIn("PROPOSAL_MANIFEST_UNAVAILABLE", self.codes())
        self.assertIn("PROPOSAL_MANIFEST_REFERENCE", self.codes(proposal_index={"b" * 64: {"P-01"}}))
        self.assertIn("PROPOSAL_ID_REFERENCE", self.codes(proposal_index={"a" * 64: {"P-02"}}))
        self.assertEqual(self.codes(proposal_index={"a" * 64: {"P-01"}}), set())

    def test_duplicate_memo_id(self) -> None:
        first = self.draft("p1-s03-memo.draft.json")
        second = self.draft("p1-s04-memo.draft.json")
        second["annotations"][0]["memo_id"] = first["annotations"][0]["memo_id"]
        self.add("p1-s03-memo.draft.json", first)
        self.add("p1-s04-memo.draft.json", second)
        self.assertIn("DUPLICATE_MEMO_ID", self.codes())

    def test_duplicate_task_document_and_hash_duration_conflict(self) -> None:
        first = self.draft("p1-s03-memo.draft.json")
        second = copy.deepcopy(first)
        second["source"]["duration_seconds"] += 1
        self.add("p1-s03-memo.draft.json", first)
        self.add("p1-s03-memo.extra.json", second)
        codes = self.codes()
        self.assertIn("DUPLICATE_TASK_DOCUMENT", codes)
        self.assertIn("MEDIA_HASH_DURATION_CONFLICT", codes)

    def test_vlm_representation_and_bounded_interval(self) -> None:
        source = self.draft("p1-s06-autonomous.draft.json")["source"]
        row = {"source": source, "representation": "proposal-contact-sheet-v0.2",
               "annotations": [{"annotation_id": "VIS-01", "expected_outcome": "INSUFFICIENT_VISUAL_EVIDENCE",
                                "acceptable_proposal_ids": [], "visual_evidence_sufficiency": "INSUFFICIENT",
                                "target_intervals": [{"start_seconds": 1, "end_seconds": 2}],
                                "required_visual_fact": "Gift opening not visible in bounded frames",
                                "ambiguity": "INSUFFICIENT_CONTEXT", "rationale_code": "TEST"}]}
        self.add("p1-s06-vlm.draft.json", row)
        self.assertEqual(self.codes(), set())
        row["representation"] = "unknown"
        self.add("p1-s06-vlm.draft.json", row)
        self.assertIn("SCHEMA", self.codes())
        row["representation"] = "proposal-contact-sheet-v0.2"
        row["annotations"][0]["target_intervals"][0]["end_seconds"] = 100
        self.add("p1-s06-vlm.draft.json", row)
        self.assertIn("INTERVAL_BOUNDS", self.codes())

    def event_document(self) -> dict:
        sources = [self.draft(f"p1-s0{i}-autonomous.draft.json")["source"] for i in (1, 2, 3, 4)]
        candidates = [{"candidate_id": f"C{i}", "source_id": source["source_id"],
                       "interval": {"start_seconds": 1, "end_seconds": 2}}
                      for i, source in enumerate(sources, 1)]
        return {"dataset_version": "cutory-v2-focused-eval-v0.1", "annotation_revision": 1,
                "project_id": "P1", "scenario_id": "P1-S01", "annotated_before_model_run": True,
                "annotator": "test", "annotation_time": "2026-10-12T00:00:00Z", "privacy_class": "PRIVATE_LOCAL",
                "sources": sources, "candidates": candidates, "relations": [],
                "event_groups": [{"gt_event_id": "E1", "candidate_ids": ["C1", "C2"]},
                                 {"gt_event_id": "E2", "candidate_ids": ["C3", "C4"]}],
                "acceptable_unassigned": [], "must_not_merge": [["E1", "E2"]], "ambiguous_memberships": []}

    def test_event_candidate_source_and_duplicate_ids(self) -> None:
        row = self.event_document()
        row["candidates"][0]["source_id"] = "UNKNOWN"
        self.add("p1-event.draft.json", row)
        self.assertIn("CANDIDATE_SOURCE_REFERENCE", self.codes())
        row = self.event_document()
        row["candidates"][1]["candidate_id"] = "C1"
        self.add("p1-event.draft.json", row)
        self.assertIn("DUPLICATE_CANDIDATE_ID", self.codes())

    def test_event_direction_symmetric_order_and_group(self) -> None:
        row = self.event_document()
        row["event_groups"][0]["candidate_ids"][1] = "UNKNOWN"
        self.add("p1-event.draft.json", row)
        self.assertIn("GROUP_CANDIDATE_REFERENCE", self.codes())
        row = self.event_document()
        row["relations"] = [{"source_candidate_id": "C2", "target_candidate_id": "C1",
                             "relation_type": "SAME_EVENT", "directional": False,
                             "rationale_code": "TEST", "ambiguity": "NONE"}]
        self.add("p1-event.draft.json", row)
        self.assertIn("SYMMETRIC_PAIR_ORDER", self.codes())
        row = self.event_document()
        row["relations"] = [{"source_candidate_id": "C3", "target_candidate_id": "C1",
                             "relation_type": "SAME_EVENT", "directional": False,
                             "rationale_code": "TEST", "ambiguity": "NONE"}]
        self.add("p1-event.draft.json", row)
        self.assertIn("MUST_NOT_MERGE_CONFLICT", self.codes())

    def test_event_reaction_direction_against_preregistration(self) -> None:
        row = self.event_document()
        # Replace first two source envelopes with P2-S02 trigger and P2-S04 reaction.
        trigger = copy.deepcopy(row["sources"][0])
        reaction = copy.deepcopy(row["sources"][1])
        trigger.update(project_id="P2", scenario_id="P2-S02", source_id="P2-S02-take01")
        reaction.update(project_id="P2", scenario_id="P2-S04", source_id="P2-S04-take01")
        row["project_id"] = "P2"
        row["sources"] = [trigger, reaction]
        row["candidates"] = [{"candidate_id": "TRIGGER", "source_id": trigger["source_id"],
                              "interval": {"start_seconds": 1, "end_seconds": 2}},
                             {"candidate_id": "REACTION", "source_id": reaction["source_id"],
                              "interval": {"start_seconds": 1, "end_seconds": 2}}]
        row["event_groups"] = [{"gt_event_id": "E1", "candidate_ids": ["TRIGGER", "REACTION"]}]
        row["must_not_merge"] = []
        edge = {"source_candidate_id": "TRIGGER", "target_candidate_id": "REACTION",
                "relation_type": "REACTION_TO", "directional": True,
                "rationale_code": "TEST", "ambiguity": "NONE"}
        row["relations"] = [edge]
        self.add("p2-event.draft.json", row)
        self.assertIn("RELATION_DIRECTION", self.codes())
        edge["source_candidate_id"], edge["target_candidate_id"] = edge["target_candidate_id"], edge["source_candidate_id"]
        self.add("p2-event.draft.json", row)
        self.assertNotIn("RELATION_DIRECTION", self.codes())

    def test_event_unassigned_and_membership_references(self) -> None:
        row = self.event_document()
        row["acceptable_unassigned"] = ["UNKNOWN"]
        self.add("p1-event.draft.json", row)
        self.assertIn("UNASSIGNED_REFERENCE", self.codes())
        row = self.event_document()
        row["event_groups"][1]["candidate_ids"][1] = "C1"
        self.add("p1-event.draft.json", row)
        self.assertIn("MULTIPLE_EVENT_MEMBERSHIP", self.codes())

    def test_duplicate_relation_requires_hash_and_normalized_interval(self) -> None:
        row = self.event_document()
        row["relations"] = [{"source_candidate_id": "C1", "target_candidate_id": "C2",
                             "relation_type": "DUPLICATE", "directional": False,
                             "rationale_code": "TEST", "ambiguity": "NONE"}]
        self.add("p1-event.draft.json", row)
        self.assertIn("DUPLICATE_NOT_EXACT", self.codes())
        row["sources"][1]["media_sha256"] = row["sources"][0]["media_sha256"]
        row["sources"][1]["duration_seconds"] = row["sources"][0]["duration_seconds"]
        self.add("p1-event.draft.json", row)
        self.assertNotIn("DUPLICATE_NOT_EXACT", self.codes())

    def test_draft_allows_missing_tasks_freeze_reports_them(self) -> None:
        self.add("p1-s04-memo.draft.json", self.draft("p1-s04-memo.draft.json"))
        self.assertEqual(validate_dataset(self.root).status, "PASS")
        result = validate_dataset(self.root, mode="freeze-ready")
        self.assertEqual(result.status, "PENDING")
        self.assertIn("MISSING_TASK_GT", {x.code for x in result.issues})
        self.assertIn("MISSING_EVENT_GT", {x.code for x in result.issues})


if __name__ == "__main__":
    unittest.main()
