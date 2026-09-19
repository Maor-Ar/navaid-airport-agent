"""JSON-able dumps for tool payloads (number lock + Gemini + sessions)."""

from __future__ import annotations

import math
from datetime import date, datetime
from enum import Enum
from typing import Any


def round_display_float(value: float) -> float | int:
    """Compact floats so Gemini never quotes 15-decimal engine noise."""

    if math.isnan(value) or math.isinf(value):
        return value
    abs_value = abs(value)
    if abs(value - round(value)) < 1e-9 and abs_value < 1e15:
        return int(round(value))
    if abs_value >= 10:
        return round(value, 1)
    if abs_value >= 1:
        return round(value, 2)
    return round(value, 4)


def jsonable(value: Any, *, round_floats: bool = False) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return round_display_float(value) if round_floats else value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump(mode="json"), round_floats=round_floats)
    if isinstance(value, dict):
        return {str(key): jsonable(item, round_floats=round_floats) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(item, round_floats=round_floats) for item in value]
    if hasattr(value, "__dict__"):
        return jsonable(vars(value), round_floats=round_floats)
    return str(value)
