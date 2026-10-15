"""Check the preregistered scenario/Coverage contract without GT or media.

This is separate from validate_focused_gt: it checks planned references, not
whether an event, reaction, or conditional case actually occurred on video.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path


DATASET_DIR = Path(__file__).resolve().parent / "datasets" / "cutory-v2-focused-eval-v0.1"
CASE_RE = re.compile(r"\b([ABCD]\d+)\b")
SCENARIO_RE = re.compile(r"(?:(P\d+)-)?(S\d{2})\b")
HISTORY_RE = re.compile(r"manifest v(\d+)\s*→\s*v(\d+)")
RELATION_TYPES = frozenset({"SAME_EVENT", "CONTINUATION", "REACTION_TO", "DUPLICATE", "MUST_NOT_MERGE", "UNRELATED"})
DIRECTIONAL_TYPES = frozenset({"CONTINUATION", "REACTION_TO"})


@dataclass(frozen=True)
class Issue:
    code: str
    location: str
    detail: str


@dataclass
class Report:
    project_count: int = 0
    scenario_count: int = 0
    coverage_count: int = 0
    issues: list[Issue] = field(default_factory=list)

    @property
    def status(self) -> str:
        return "FAIL" if self.issues else "PASS"

    def add(self, code: str, location: str, detail: str) -> None:
        self.issues.append(Issue(code, location, detail))


def _scenario_references(cell: str) -> tuple[str, ...]:
    """Expand existing table shorthand such as P2-S01↔S02 and P3-S01/S02."""
    project = None
    result = []
    for match in SCENARIO_RE.finditer(cell):
        project = match.group(1) or project
        if project is not None:
            result.append(f"{project}-{match.group(2)}")
    return tuple(result)


def _coverage_rows(report: Report, text: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    rows: dict[str, tuple[str, tuple[str, ...]]] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        cells = [cell.strip() for cell in line.split("|")]
        if len(cells) < 5:
            continue
        match = CASE_RE.match(cells[1])
        if not match and not re.match(r"^[ABCD]\d", cells[1]):
            continue
        location = f"COVERAGE.md:{line_number}"
        if not match:
            report.add("INVALID_COVERAGE_ROW", location, "Coverage case ID is missing or invalid.")
            continue
        if cells[2] not in {"COVERED", "CONDITIONAL", "OPTIONAL"}:
            report.add("INVALID_COVERAGE_STATUS", location, cells[2])
            continue
        case_id = match.group(1)
        if case_id in rows:
            report.add("DUPLICATE_COVERAGE_ID", location, case_id)
        rows[case_id] = (cells[2], _scenario_references(cells[3]))
        if cells[2] != "OPTIONAL" and not rows[case_id][1]:
            report.add("MISSING_COVERAGE_SCENARIO", location, case_id)
    return rows


def _history(report: Report, version: object, text: str) -> None:
    if type(version) is not int or version < 1:
        report.add("INVALID_MANIFEST_VERSION", "recording-scenarios.json", "manifest_version must be a positive integer.")
        return
    transitions = [(int(left), int(right)) for left, right in HISTORY_RE.findall(text)]
    counts = Counter(transitions)
    expected = {(number, number + 1) for number in range(1, version)}
    if set(transitions) != expected or any(count != 1 for count in counts.values()):
        report.add("MANIFEST_HISTORY", "manifests/README.md", "Version history must contain each vN → vN+1 transition exactly once.")


def validate_manifest(root: Path = DATASET_DIR) -> Report:
    report = Report()
    manifest_path = root / "manifests" / "recording-scenarios.json"
    coverage_path = root / "manifests" / "COVERAGE.md"
    readme_path = root / "manifests" / "README.md"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        coverage_text = coverage_path.read_text(encoding="utf-8")
        history_text = readme_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError) as exc:
        report.add("INPUT_INVALID", str(root), str(exc))
        return report
    if not isinstance(manifest, dict):
        report.add("INVALID_MANIFEST", str(manifest_path), "Manifest must be an object.")
        return report
    _history(report, manifest.get("manifest_version"), history_text)
    projects = manifest.get("projects")
    scenarios = manifest.get("scenarios")
    if not isinstance(projects, list) or not isinstance(scenarios, list):
        report.add("INVALID_MANIFEST", str(manifest_path), "projects and scenarios must be arrays.")
        return report
    report.project_count, report.scenario_count = len(projects), len(scenarios)
    coverage = _coverage_rows(report, coverage_text)
    report.coverage_count = len(coverage)
    project_ids: set[str] = set()
    for index, project in enumerate(projects):
        project_id = project.get("project_id") if isinstance(project, dict) else None
        if not isinstance(project_id, str) or not project_id:
            report.add("MISSING_PROJECT_ID", f"projects[{index}]", "project_id is required.")
        elif project_id in project_ids:
            report.add("DUPLICATE_PROJECT_ID", f"projects[{index}]", project_id)
        else:
            project_ids.add(project_id)
    scenario_by_id: dict[str, dict] = {}
    for index, scenario in enumerate(scenarios):
        location = f"scenarios[{index}]"
        if not isinstance(scenario, dict):
            report.add("INVALID_SCENARIO", location, "Scenario must be an object.")
            continue
        scenario_id = scenario.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id:
            report.add("MISSING_SCENARIO_ID", location, "scenario_id is required.")
            continue
        if scenario_id in scenario_by_id:
            report.add("DUPLICATE_SCENARIO_ID", location, scenario_id)
        scenario_by_id[scenario_id] = scenario
        project_id = scenario.get("project_id")
        if not isinstance(project_id, str) or project_id not in project_ids:
            report.add("UNKNOWN_PROJECT", location, str(project_id))
        elif not scenario_id.startswith(f"{project_id}-"):
            report.add("SCENARIO_PROJECT_MISMATCH", location, scenario_id)
        task_coverage = scenario.get("task_coverage")
        if not isinstance(task_coverage, list):
            report.add("INVALID_TASK_COVERAGE", location, "task_coverage must be an array.")
        else:
            if len(task_coverage) != len(set(map(str, task_coverage))):
                report.add("DUPLICATE_TASK_COVERAGE", location, scenario_id)
            for case_id in task_coverage:
                if not isinstance(case_id, str) or case_id not in coverage:
                    report.add("UNKNOWN_COVERAGE_ID", location, str(case_id))
        if not isinstance(scenario.get("relation_intent"), list):
            report.add("INVALID_RELATIONS", location, "relation_intent must be an array.")
    for project_id in project_ids:
        if not any(scenario.get("project_id") == project_id for scenario in scenario_by_id.values()):
            report.add("PROJECT_WITHOUT_SCENARIO", project_id, "No Scenario belongs to this Project.")
    for case_id, (status, references) in coverage.items():
        for scenario_id in references:
            if scenario_id not in scenario_by_id:
                report.add("UNKNOWN_COVERAGE_SCENARIO", case_id, scenario_id)
        # The table lists context/pair sources, not a complete inverse index.
        # CONDITIONAL cases may be planned only in the table, while COVERED
        # cases must have at least one owning Scenario in the manifest.
        if status == "COVERED" and not any(
            isinstance(scenario_by_id[scenario_id].get("task_coverage"), list)
            and case_id in scenario_by_id[scenario_id]["task_coverage"]
            for scenario_id in references if scenario_id in scenario_by_id
        ):
            report.add("COVERAGE_BACK_REFERENCE", case_id, "No listed Scenario owns this COVERED case.")
    for owner_id, scenario in scenario_by_id.items():
        intents = scenario.get("relation_intent")
        for index, relation in enumerate(intents if isinstance(intents, list) else []):
            location = f"{owner_id}.relation_intent[{index}]"
            if not isinstance(relation, dict):
                report.add("INVALID_RELATION", location, "Relation must be an object.")
                continue
            other_id, kind = relation.get("with"), relation.get("type")
            if not isinstance(other_id, str) or other_id not in scenario_by_id or other_id == owner_id:
                report.add("RELATION_REFERENCE", location, str(other_id))
                continue
            if scenario_by_id[other_id].get("project_id") != scenario.get("project_id"):
                report.add("CROSS_PROJECT_RELATION", location, str(other_id))
            if not isinstance(kind, str) or kind not in RELATION_TYPES:
                report.add("INVALID_RELATION_TYPE", location, str(kind))
                continue
            source, target = relation.get("source_scenario_id"), relation.get("target_scenario_id")
            if kind in DIRECTIONAL_TYPES:
                # Existing v0.1 preregistration locates CONTINUATION on its later
                # scenario and REACTION_TO on its reaction scenario.
                expected = (other_id, owner_id) if kind == "CONTINUATION" else (owner_id, other_id)
                if (source, target) != expected:
                    report.add("RELATION_DIRECTION", location, f"{kind} requires {expected[0]} → {expected[1]}.")
            elif source is not None or target is not None:
                report.add("SYMMETRIC_RELATION_DIRECTION", location, f"{kind} must not specify directional endpoints.")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_DIR)
    args = parser.parse_args()
    report = validate_manifest(args.dataset)
    print(f"{report.status}: {report.project_count} projects, {report.scenario_count} scenarios, {report.coverage_count} coverage cases; {len(report.issues)} issue(s)")
    for issue in report.issues:
        print(f"{issue.code} {issue.location}: {issue.detail}")
    return 0 if report.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
