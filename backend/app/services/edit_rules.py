"""TODO 27: "내 편집 규칙" — sentences the user saved from the chat ("한 컷은 8초 넘지 않게").

Shared by every project (taste does not change with the day), stored like the registered face in
``outputs/me/edit_rules.json`` (no database change). The story direction and the chat brain read them; a rule
like "N초 넘지 않게" is also kept by Python when the story direction fits scene lengths.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

MAX_RULES = 20
MAX_CHARS = 120
_STAMP = re.compile(r"^\s*\[\d{1,3}:\d{2}\]\s*")


class EditRuleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _path(project_output_root: Path) -> Path:
    """outputs/projects -> outputs/me/edit_rules.json"""
    return Path(project_output_root).parent / "me" / "edit_rules.json"


def load_rules(project_output_root: Path) -> list[dict]:
    try:
        data = json.loads(_path(project_output_root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    return [rule for rule in rules or [] if isinstance(rule, dict) and isinstance(rule.get("text"), str)
            and isinstance(rule.get("id"), str)]


def rule_texts(project_output_root: Path) -> list[str]:
    return [rule["text"] for rule in load_rules(project_output_root)]


def _save(project_output_root: Path, rules: list[dict]) -> None:
    path = _path(project_output_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"rules": rules}, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def add_rule(project_output_root: Path, text: str) -> list[dict]:
    text = re.sub(r"\s+", " ", _STAMP.sub("", text or "")).strip()[:MAX_CHARS]
    if not text:
        raise EditRuleError("EMPTY_RULE", "규칙으로 저장할 말이 비어 있어요.")
    rules = load_rules(project_output_root)
    if any(rule["text"] == text for rule in rules):
        return rules
    if len(rules) >= MAX_RULES:
        raise EditRuleError("TOO_MANY_RULES", f"규칙은 {MAX_RULES}개까지예요. 안 쓰는 규칙을 지워 주세요.")
    rules.append({"id": uuid4().hex[:12], "text": text, "created_at": datetime.now(timezone.utc).isoformat()})
    _save(project_output_root, rules)
    return rules


def delete_rule(project_output_root: Path, rule_id: str) -> list[dict]:
    rules = load_rules(project_output_root)
    kept = [rule for rule in rules if rule["id"] != rule_id]
    if len(kept) != len(rules):
        _save(project_output_root, kept)
    return kept


_MAX_CUT = re.compile(r"(\d+(?:\.\d+)?)\s*초\s*(?:를|을)?\s*(?:넘지|넘기지|안\s*넘|이하|이내|까지만?|보다\s*짧|넘으면\s*안)")


def max_cut_seconds(texts: list[str]) -> float | None:
    """'한 컷은 8초 넘지 않게' -> 8.0 (the smallest such limit; at least 1 second)."""
    limits = [float(match.group(1)) for text in texts for match in _MAX_CUT.finditer(text)]
    limits = [value for value in limits if value >= 1]
    return min(limits) if limits else None
