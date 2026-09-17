"""Long-haul share on T-100 segments (great-circle kilometres).

Default threshold is Eurocontrol >4000 km. International share is always
reported; ``pct_over_6h`` is optional when block hours exist. Cargo is out
unless asked. Distances are kilometres unless explicitly converted to statute
miles — never mix units in one field.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from math import atan2, cos, radians, sin, sqrt
from typing import Any

from navaid.config import LONGHAUL_HOURS, LONGHAUL_KM
from navaid.scoring._util import coords_of, iata_of, merge_metrics, optional_float
from navaid.scoring.envelope import make_envelope
from navaid.scoring.models import LonghaulResult

# Mean Earth radius (km). Statute mile is the only miles conversion we allow.
EARTH_RADIUS_KM = 6371.0
KM_PER_STATUTE_MILE = 1.609344

_LONGHAUL_ASSUMPTIONS = (
    f"Long-haul default is great-circle distance > {LONGHAUL_KM:.0f} km (Eurocontrol) on T-100 segments",
    "T-100 is segment traffic, not true O&D",
    "Cargo segments are excluded unless include_cargo=True",
    "Distances are kilometres; statute miles are a separate conversion (do not mix units)",
)

_LONGHAUL_SOURCES = (
    "BTS T-100",
    "OurAirports",
)


def great_circle_km(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    *,
    radius_km: float = EARTH_RADIUS_KM,
) -> float:
    """Haversine great-circle distance in kilometres."""

    phi1, lambda1, phi2, lambda2 = (radians(lat1), radians(lon1), radians(lat2), radians(lon2))
    d_phi = phi2 - phi1
    d_lambda = lambda2 - lambda1
    a = sin(d_phi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(d_lambda / 2) ** 2
    return 2 * radius_km * atan2(sqrt(a), sqrt(1 - a))


def km_to_statute_miles(km: float) -> float:
    """Convert kilometres to statute miles. Never treat this figure as kilometres."""

    return km / KM_PER_STATUTE_MILE


def _is_cargo(segment: Mapping[str, Any], include_cargo: bool) -> bool:
    if include_cargo:
        return False
    if segment.get("cargo") is True:
        return True
    passengers = optional_float(segment.get("passengers")) or 0.0
    freight = optional_float(segment.get("freight") or segment.get("cargo_tons"))
    return passengers <= 0 and freight is not None and freight > 0


def _segment_hours(segment: Mapping[str, Any]) -> float | None:
    return optional_float(segment.get("hours") or segment.get("block_hours"))


def _segment_distance_km(
    segment: Mapping[str, Any],
    *,
    origin: str,
    airports: Mapping[str, Mapping[str, Any]] | None,
) -> float | None:
    direct = optional_float(segment.get("distance_km"))
    if direct is not None:
        return direct
    origin_coords = coords_of(segment) or (
        coords_of(airports.get(origin) if airports else None)
    )
    dest = str(segment.get("dest") or segment.get("destination") or "").strip().upper()
    dest_lat = optional_float(segment.get("dest_lat") or segment.get("destination_lat"))
    dest_lon = optional_float(segment.get("dest_lon") or segment.get("destination_lon"))
    dest_coords = (
        (dest_lat, dest_lon)
        if dest_lat is not None and dest_lon is not None
        else coords_of(airports.get(dest) if airports and dest else None)
    )
    origin_lat = optional_float(segment.get("origin_lat"))
    origin_lon = optional_float(segment.get("origin_lon"))
    if origin_lat is not None and origin_lon is not None:
        origin_coords = (origin_lat, origin_lon)
    if origin_coords is None or dest_coords is None:
        return None
    return great_circle_km(origin_coords[0], origin_coords[1], dest_coords[0], dest_coords[1])


def longhaul_share(
    metrics: Mapping[str, Any] | None = None,
    /,
    *,
    airport: str | None = None,
    segments: Sequence[Mapping[str, Any]] | None = None,
    airports: Mapping[str, Mapping[str, Any]] | None = None,
    threshold_km: float | None = None,
    include_cargo: bool = False,
    as_of: date | None = None,
    now: date | None = None,
) -> LonghaulResult:
    """Passenger-weighted long-haul and international shares from in-memory segments."""

    row = merge_metrics(metrics, airport=airport)
    code = iata_of(row)
    rows = list(segments if segments is not None else row.get("segments") or ())
    cutoff = float(threshold_km if threshold_km is not None else LONGHAUL_KM)
    raw_airports = dict(airports or row.get("airports") or {})
    airport_lookup = {
        str(key).strip().upper(): value for key, value in raw_airports.items()
    }

    pax_total = 0.0
    pax_longhaul = 0.0
    pax_international = 0.0
    pax_over_6h = 0.0
    hours_weight = 0.0
    counted = 0
    missing_distance = 0
    cargo_skipped = 0

    for segment in rows:
        origin = str(segment.get("origin") or code).strip().upper()
        if origin != code:
            continue
        if _is_cargo(segment, include_cargo):
            cargo_skipped += 1
            continue
        passengers = optional_float(segment.get("passengers")) or 0.0
        distance = _segment_distance_km(segment, origin=origin, airports=airport_lookup)
        if distance is None:
            missing_distance += 1
            continue
        counted += 1
        pax_total += passengers
        if distance > cutoff:
            pax_longhaul += passengers
        if segment.get("international") is True:
            pax_international += passengers
        hours = _segment_hours(segment)
        if hours is not None:
            hours_weight += passengers
            if hours > LONGHAUL_HOURS:
                pax_over_6h += passengers

    pct_longhaul = (100.0 * pax_longhaul / pax_total) if pax_total else 0.0
    pct_international = (100.0 * pax_international / pax_total) if pax_total else 0.0
    pct_over_6h = (100.0 * pax_over_6h / hours_weight) if hours_weight else None

    uncertainties: list[str] = []
    if cargo_skipped and not include_cargo:
        uncertainties.append(f"excluded {cargo_skipped} cargo segment(s)")
    if missing_distance:
        uncertainties.append(f"{missing_distance} segment(s) missing distance_km and coordinates")
    if pct_over_6h is None:
        uncertainties.append("pct_over_6h omitted (no block hours on counted segments)")
    missing_required = pax_total <= 0

    envelope = make_envelope(
        assumptions=_LONGHAUL_ASSUMPTIONS,
        sources=_LONGHAUL_SOURCES,
        as_of=as_of if as_of is not None else row.get("as_of"),
        now=now,
        uncertainties=uncertainties,
        out_of_scope=["true O&D itineraries", "cargo share"] if not include_cargo else ["true O&D itineraries"],
        missing_optional=pct_over_6h is None or missing_distance > 0,
        missing_required=missing_required,
    )
    return LonghaulResult(
        airport=code,
        threshold_km=cutoff,
        threshold_hours=LONGHAUL_HOURS,
        passengers_total=pax_total,
        passengers_longhaul=pax_longhaul,
        pct_longhaul=pct_longhaul,
        pct_international=pct_international,
        pct_over_6h=pct_over_6h,
        segments_counted=counted,
        cargo_excluded=not include_cargo,
        envelope=envelope,
    )
