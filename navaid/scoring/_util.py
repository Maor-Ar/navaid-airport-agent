"""Shared parsing helpers for in-memory metric dicts (no warehouse required)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number:  # NaN
        return None
    return number


def merge_metrics(
    metrics: Mapping[str, Any] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Shallow-merge a metrics dict with kwargs; explicit kwargs win when not None."""

    data = dict(metrics or {})
    for key, value in kwargs.items():
        if value is not None:
            data[key] = value
    return data


def iata_of(row: Mapping[str, Any], default: str | None = None) -> str:
    raw = row.get("airport") or row.get("iata") or default
    if raw is None or str(raw).strip() == "":
        raise ValueError("airport IATA code is required")
    return str(raw).strip().upper()


def icao_of(row: Mapping[str, Any], *, fallback: str | None = None) -> str:
    raw = row.get("icao") or row.get("ident") or fallback
    if raw is None or str(raw).strip() == "":
        return iata_of(row) if "airport" in row or "iata" in row else ""
    return str(raw).strip().upper()


def coords_of(row: Mapping[str, Any] | None) -> tuple[float, float] | None:
    if not row:
        return None
    lat = optional_float(row.get("latitude", row.get("lat")))
    lon = optional_float(row.get("longitude", row.get("lon")))
    if lat is None or lon is None:
        return None
    return lat, lon
