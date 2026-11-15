"""TODO 23: the user's own "오늘 있었던 일" note for a project, kept as a small file next to the project's outputs.

It is the strongest hint for the story direction: what the day was about, in the user's words. Stored as a file
(no database change). An empty note deletes the file.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

MAX_CHARS = 1000


def _path(output_root: Path, project_id: UUID) -> Path:
    return Path(output_root) / str(project_id) / "day_brief.json"


def load_day_brief(output_root: Path, project_id: UUID) -> str:
    try:
        value = json.loads(_path(output_root, project_id).read_text(encoding="utf-8")).get("text", "")
    except (OSError, ValueError, AttributeError):
        return ""
    return value.strip()[:MAX_CHARS] if isinstance(value, str) else ""


def save_day_brief(output_root: Path, project_id: UUID, text: str) -> str:
    text = (text or "").strip()[:MAX_CHARS]
    path = _path(output_root, project_id)
    if not text:
        path.unlink(missing_ok=True)
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"text": text, "updated_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return text
