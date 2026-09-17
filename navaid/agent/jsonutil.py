"""JSON-able dumps for tool payloads (number lock + Gemini + sessions)."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any


def jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item) for item in value]
    if hasattr(value, "__dict__"):
        return jsonable(vars(value))
    return str(value)
