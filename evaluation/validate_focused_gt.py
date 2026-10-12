"""Validate the v0.1 focused GT documents without reading media or running models.

JSON Schema is the structural layer. This module only adds documented cross-field,
cross-document, and preregistration-reference checks. Missing derived references
are PENDING, never invented by the validator.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


DATASET_DIR = Path(__file__).resolve().parent / "datasets" / "cutory-v2-focused-eval-v0.1"
SCHEMAS = {"memo": "memo.schema.json", "autonomous": "autonomous.schema.json", "vlm": "vlm.schema.json", "event": "event.schema.json"}


@dataclass(frozen=True)
class Issue:
    status: str  # FAIL or PENDING
    code: str
    location: str
    detail: str


@dataclass
class Report:
    checked_files: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def status(self) -> str:
        if any(item.status == "FAIL" for item in self.issues):
            return "FAIL"
        return "PENDING" if self.issues else "PASS"

    def add(self, status: str, code: str, location: str, detail: str) -> None:
        self.issues.append(Issue(status, code, location, detail))


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validators(root: Path) -> dict[str, Draft202012Validator]:
    schemas = {path.name: _read_json(path) for path in (root / "schema").glob("*.json")}
    for schema in schemas.values():
        Draft202012Validator.check_schema(schema)
    registry = Registry().with_resources((name, Resource.from_contents(schema)) for name, schema in schemas.items())
    return {kind: Draft202012Validator(schemas[name], registry=registry) for kind, name in SCHEMAS.items()}


def _interval(report: Report, value: dict[str, Any], duration: float, location: str) -> None:
    start, end = value["start_seconds"], value["end_seconds"]
    if not 0 <= start < end <= duration:
        report.add("FAIL", "INTERVAL_BOUNDS", location, "Require 0 <= start < end <= source duration.")


def _source(report: Report, source: dict[str, Any], scenarios: dict[str, dict[str, Any]], location: str,
            source_by_id: dict[str, tuple[Any, ...]], scenario_source: dict[str, str],
            selected_takes: dict[str, str]) -> None:
    scenario_id = source["scenario_id"]
    scenario = scenarios.get(scenario_id)
    if scenario is None or source["project_id"] != scenario["project_id"]:
        report.add("FAIL", "SCENARIO_REFERENCE", location, "Unknown scenario or wrong project.")
    identity = (source["project_id"], scenario_id, source["media_sha256"], source["duration_seconds"])
    source_id = source["source_id"]
    if source_id in source_by_id and source_by_id[source_id] != identity:
        report.add("FAIL", "SOURCE_ID_CONFLICT", location, "Source ID has conflicting project/scenario/hash/duration.")
    source_by_id[source_id] = identity
    if scenario_id in scenario_source and scenario_source[scenario_id] != source_id:
        report.add("FAIL", "SCENARIO_SOURCE_CONFLICT", location, "One scenario has multiple selected source IDs.")
    scenario_source[scenario_id] = source_id
    chosen = selected_takes.get(scenario_id)
    if chosen and source_id != chosen:
        report.add("FAIL", "SELECTED_TAKE_MISMATCH", location, f"Review notes select {chosen}, not {source_id}.")


def _selected_takes(root: Path) -> dict[str, str]:
    """Only enforce an explicit take selection in the existing P1 review record.

    This is a dataset-v0.1 reference check, not a new general naming rule.
    """
    notes = root / "annotations" / "P1-G5-B4-review-notes.md"
    if not notes.exists():
        return {}
    text = notes.read_text(encoding="utf-8")
    match = re.search(r"P1-S03[^\n]*`(P1-S03-take\d+)` only", text)
    return {"P1-S03": match.group(1)} if match else {}


def _relation_intent(manifest: dict[str, Any], source_scenario: str, target_scenario: str, kind: str) -> bool | None:
    intents = [intent for scenario in manifest["scenarios"] for intent in scenario["relation_intent"]
               if intent["type"] == kind and intent.get("source_scenario_id") == source_scenario
               and intent.get("target_scenario_id") == target_scenario]
    if intents:
        return True
    reversed_intents = [intent for scenario in manifest["scenarios"] for intent in scenario["relation_intent"]
                        if intent["type"] == kind and intent.get("source_scenario_id") == target_scenario
                        and intent.get("target_scenario_id") == source_scenario]
    return False if reversed_intents else None


def _required_covered_tasks(root: Path) -> set[tuple[str, str]]:
    """Use preregistered COVERED rows; CONDITIONAL/OPTIONAL are not requirements."""
    required: set[tuple[str, str]] = set()
    coverage = (root / "manifests" / "COVERAGE.md").read_text(encoding="utf-8")
    for line in coverage.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 5 or cells[2] != "COVERED":
            continue
        case = cells[1].split()[0]
        task = {"A": "memo", "B": "autonomous", "C": "vlm"}.get(case[:1])
        if task:
            for scenario_id in re.findall(r"P[123]-S\d{2}", cells[3]):
                required.add((scenario_id, task))
    return required


def validate_dataset(root: Path = DATASET_DIR, *, mode: str = "draft",
                     proposal_index: dict[str, set[str]] | None = None) -> Report:
    """Validate present GT. In freeze-ready, also report missing planned task GT.

    proposal_index maps an existing manifest fingerprint to its real Proposal IDs.
    It is optional because no proposal generator may be run in this validation.
    """
    if mode not in {"draft", "freeze-ready"}:
        raise ValueError("mode must be draft or freeze-ready")
    report = Report()
    manifest = _read_json(root / "manifests" / "recording-scenarios.json")
    scenarios = {row["scenario_id"]: row for row in manifest["scenarios"]}
    validators = _validators(root)
    source_by_id: dict[str, tuple[Any, ...]] = {}
    duration_by_hash: dict[str, float] = {}
    scenario_source: dict[str, str] = {}
    seen_memos: set[str] = set()
    seen_vlm: set[str] = set()
    present: set[tuple[str, str]] = set()
    selected_takes = _selected_takes(root)
    annotations = sorted((root / "annotations").glob("*.json"))
    for path in annotations:
        location = path.name
        kind = next((name for name in SCHEMAS if f"-{name}." in path.name), None)
        if kind is None:
            report.add("FAIL", "UNKNOWN_DOCUMENT", location, "Cannot infer task schema from filename.")
            continue
        try:
            document = _read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            report.add("FAIL", "JSON_PARSE", location, str(exc))
            continue
        report.checked_files += 1
        errors = sorted(validators[kind].iter_errors(document), key=lambda err: tuple(map(str, err.absolute_path)))
        if errors:
            for error in errors:
                report.add("FAIL", "SCHEMA", location, f"{list(error.absolute_path)}: {error.message}")
            continue
        sources = document["sources"] if kind == "event" else [document["source"]]
        for source in sources:
            _source(report, source, scenarios, location, source_by_id, scenario_source, selected_takes)
            media_hash = source["media_sha256"].lower()
            if media_hash in duration_by_hash and duration_by_hash[media_hash] != source["duration_seconds"]:
                report.add("FAIL", "MEDIA_HASH_DURATION_CONFLICT", location, "Equal media hash has conflicting duration.")
            duration_by_hash[media_hash] = source["duration_seconds"]
            if mode == "freeze-ready" and not source["annotated_before_model_run"]:
                report.add("PENDING", "POST_MODEL_ANNOTATION", location, "Not eligible for preregistered freeze-ready result.")
        project = document["project_id"] if kind == "event" else sources[0]["project_id"]
        if kind == "event":
            if any(source["project_id"] != project for source in sources):
                report.add("FAIL", "EVENT_PROJECT", location, "Event sources must belong to the document project.")
            key = (project, kind)
            if key in present:
                report.add("FAIL", "DUPLICATE_TASK_DOCUMENT", location, f"Repeated {kind} GT for {project}.")
            present.add(key)
        else:
            key = (sources[0]["scenario_id"], kind)
            if key in present:
                report.add("FAIL", "DUPLICATE_TASK_DOCUMENT", location, f"Repeated {kind} GT for {key[0]}.")
            present.add(key)

        if kind == "memo":
            source = sources[0]
            for row in document["annotations"]:
                memo_id = row["memo_id"]
                if memo_id in seen_memos:
                    report.add("FAIL", "DUPLICATE_MEMO_ID", location, memo_id)
                seen_memos.add(memo_id)
                _interval(report, row["memo_interval"], source["duration_seconds"], location)
                for target in row["target_intervals"]:
                    _interval(report, target, source["duration_seconds"], location)
                outcome = row["expected_outcome"]
                targets = row["target_intervals"]
                if outcome == "NO_MATCH" and targets:
                    report.add("FAIL", "NO_MATCH_TARGET", location, "NO_MATCH requires no target intervals.")
                if outcome == "AMBIGUOUS" and (len(targets) < 2 or not row["rationale_code"]):
                    report.add("FAIL", "AMBIGUOUS_TARGETS", location, "Require at least two alternatives and a rationale.")
                if outcome == "SELECTED" and not targets:
                    report.add("FAIL", "SELECTED_TARGET", location, "SELECTED requires a target interval.")
                if "preferred_proposal_id" in row and row["preferred_proposal_id"] not in row["acceptable_proposal_ids"]:
                    report.add("FAIL", "PREFERRED_PROPOSAL", location, "Preferred ID must be acceptable.")
                _proposal_refs(report, row, location, proposal_index)

        elif kind == "autonomous":
            duration = sources[0]["duration_seconds"]
            for row in document["target_intervals"]:
                _interval(report, row, duration, location)
            # The schema already enforces boolean types and disallows consider+exclude.
            # Do not infer semantic value from reaction_present or evidence modality.

        elif kind == "vlm":
            duration = sources[0]["duration_seconds"]
            for row in document["annotations"]:
                if row["annotation_id"] in seen_vlm:
                    report.add("FAIL", "DUPLICATE_VLM_ID", location, row["annotation_id"])
                seen_vlm.add(row["annotation_id"])
                for target in row["target_intervals"]:
                    _interval(report, target, duration, location)
                _proposal_refs(report, row, location, proposal_index)
            # Sufficiency is a human judgment on the bounded Contact Sheet. No media read.

        else:
            _event(report, document, location, manifest, sources)

    if mode == "freeze-ready":
        required_tasks = _required_covered_tasks(root)
        for scenario in scenarios.values():
            scenario_id = scenario["scenario_id"]
            if scenario_id not in scenario_source:
                report.add("PENDING", "MISSING_SOURCE_GT", scenario_id, "No source envelope has been authored for this planned registration.")
        for scenario_id, task in sorted(required_tasks):
            if (scenario_id, task) not in present:
                report.add("PENDING", "MISSING_TASK_GT", scenario_id, f"Preregistered COVERED {task} GT not yet authored.")
        for project in manifest["projects"]:
            project_id = project["project_id"]
            if (project_id, "event") not in present:
                report.add("PENDING", "MISSING_EVENT_GT", project_id, "Project Event GT not yet authored.")
    return report


def _proposal_refs(report: Report, row: dict[str, Any], location: str,
                   proposal_index: dict[str, set[str]] | None) -> None:
    if row["expected_outcome"] != "SELECTED":
        return
    fingerprint = row["proposal_manifest_fingerprint"]
    if proposal_index is None:
        report.add("PENDING", "PROPOSAL_MANIFEST_UNAVAILABLE", location,
                   "Cannot verify selected IDs without the fixed Proposal manifest.")
        return
    if fingerprint not in proposal_index:
        report.add("FAIL", "PROPOSAL_MANIFEST_REFERENCE", location, "Fingerprint absent from supplied Proposal index.")
        return
    unknown = set(row["acceptable_proposal_ids"]) - proposal_index[fingerprint]
    if unknown:
        report.add("FAIL", "PROPOSAL_ID_REFERENCE", location, f"Unknown IDs: {sorted(unknown)}")


def _event(report: Report, doc: dict[str, Any], location: str, manifest: dict[str, Any],
           sources: list[dict[str, Any]]) -> None:
    source_map = {item["source_id"]: item for item in sources}
    if len(source_map) != len(sources):
        report.add("FAIL", "DUPLICATE_SOURCE_ID", location, "Duplicate source envelopes in Event document.")
    candidates: dict[str, dict[str, Any]] = {}
    for row in doc["candidates"]:
        candidate_id = row["candidate_id"]
        if candidate_id in candidates:
            report.add("FAIL", "DUPLICATE_CANDIDATE_ID", location, candidate_id)
        candidates[candidate_id] = row
        source = source_map.get(row["source_id"])
        if source is None:
            report.add("FAIL", "CANDIDATE_SOURCE_REFERENCE", location, candidate_id)
        else:
            _interval(report, row["interval"], source["duration_seconds"], location)
    groups: dict[str, set[str]] = {}
    membership: dict[str, str] = {}
    for row in doc["event_groups"]:
        event_id = row["gt_event_id"]
        if event_id in groups:
            report.add("FAIL", "DUPLICATE_EVENT_ID", location, event_id)
        groups[event_id] = set(row["candidate_ids"])
        for candidate_id in row["candidate_ids"]:
            if candidate_id not in candidates:
                report.add("FAIL", "GROUP_CANDIDATE_REFERENCE", location, candidate_id)
            if candidate_id in membership and membership[candidate_id] != event_id:
                report.add("FAIL", "MULTIPLE_EVENT_MEMBERSHIP", location, candidate_id)
            membership[candidate_id] = event_id
    for pair in doc["must_not_merge"]:
        if pair[0] == pair[1] or any(event not in groups for event in pair):
            report.add("FAIL", "MUST_NOT_MERGE_REFERENCE", location, str(pair))
    for candidate_id in doc["acceptable_unassigned"]:
        if candidate_id not in candidates or candidate_id in membership:
            report.add("FAIL", "UNASSIGNED_REFERENCE", location, candidate_id)
    for row in doc["ambiguous_memberships"]:
        if row["candidate_id"] not in candidates or any(event != "UNASSIGNED" and event not in groups for event in row["acceptable"]):
            report.add("FAIL", "AMBIGUOUS_MEMBERSHIP_REFERENCE", location, row["candidate_id"])
    seen_pairs: set[tuple[str, str, str]] = set()
    for row in doc["relations"]:
        left, right, kind = row["source_candidate_id"], row["target_candidate_id"], row["relation_type"]
        if left == right or left not in candidates or right not in candidates:
            report.add("FAIL", "RELATION_CANDIDATE_REFERENCE", location, f"{left} {kind} {right}")
            continue
        symmetric = kind not in {"CONTINUATION", "REACTION_TO"}
        if symmetric and left >= right:
            report.add("FAIL", "SYMMETRIC_PAIR_ORDER", location, f"{left} {kind} {right}")
        key = (left, right, kind) if not symmetric else (min(left, right), max(left, right), kind)
        if key in seen_pairs:
            report.add("FAIL", "DUPLICATE_RELATION", location, str(key))
        seen_pairs.add(key)
        if kind in {"CONTINUATION", "REACTION_TO"}:
            left_scenario = source_map[candidates[left]["source_id"]]["scenario_id"] if candidates[left]["source_id"] in source_map else None
            right_scenario = source_map[candidates[right]["source_id"]]["scenario_id"] if candidates[right]["source_id"] in source_map else None
            if left_scenario and right_scenario and _relation_intent(manifest, left_scenario, right_scenario, kind) is False:
                report.add("FAIL", "RELATION_DIRECTION", location, f"{kind}: {left_scenario} → {right_scenario} reverses preregistration.")
        if kind == "DUPLICATE":
            left_source = source_map.get(candidates[left]["source_id"])
            right_source = source_map.get(candidates[right]["source_id"])
            left_interval = candidates[left]["interval"]
            right_interval = candidates[right]["interval"]
            same_interval = all(round(left_interval[key], 3) == round(right_interval[key], 3)
                                for key in ("start_seconds", "end_seconds"))
            if not left_source or not right_source or left_source["media_sha256"].lower() != right_source["media_sha256"].lower() or not same_interval:
                report.add("FAIL", "DUPLICATE_NOT_EXACT", location,
                           "DUPLICATE requires identical source hash and 0.001-second normalized interval.")
        if kind == "SAME_EVENT" and membership.get(left) and membership.get(right):
            pair = {membership[left], membership[right]}
            if len(pair) == 2 and any(set(blocked) == pair for blocked in doc["must_not_merge"]):
                report.add("FAIL", "MUST_NOT_MERGE_CONFLICT", location, f"{left} and {right} link excluded Events.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("draft", "freeze-ready"), default="draft")
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    parser.add_argument("--proposal-index", type=Path,
                        help="Optional evaluator-only JSON map: manifest fingerprint -> existing Proposal ID list")
    args = parser.parse_args()
    index = _read_json(args.proposal_index) if args.proposal_index else None
    report = validate_dataset(args.dataset, mode=args.mode,
                              proposal_index={key: set(value) for key, value in index.items()} if index else None)
    print(f"{report.status}: checked {report.checked_files} GT JSON document(s); {len(report.issues)} issue(s)")
    for item in report.issues:
        print(f"{item.status} {item.code} {item.location}: {item.detail}")
    return {"PASS": 0, "FAIL": 1, "PENDING": 2}[report.status]


if __name__ == "__main__":
    raise SystemExit(main())
