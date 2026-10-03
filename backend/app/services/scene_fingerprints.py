from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
import hashlib
import json
from typing import Any
from uuid import UUID


def canonical_payload(value: Any) -> Any:
    """Return a path-independent, JSON-safe representation for result lineage."""
    if is_dataclass(value) and not isinstance(value, type):
        return canonical_payload(asdict(value))
    if isinstance(value, Enum):
        return canonical_payload(value.value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value.normalize(), "f")
    if isinstance(value, datetime):
        return value.isoformat(timespec="microseconds")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): canonical_payload(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (set, frozenset)):
        converted = [canonical_payload(item) for item in value]
        return sorted(converted, key=_canonical_json)
    if isinstance(value, (tuple, list)):
        return [canonical_payload(item) for item in value]
    if isinstance(value, float):
        if not value == value or value in (float("inf"), float("-inf")):
            raise ValueError("Non-finite values cannot be fingerprinted.")
        return value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"Unsupported fingerprint value: {type(value).__name__}")


def canonical_json(value: Any) -> str:
    return _canonical_json(canonical_payload(value))


def canonical_fingerprint(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
