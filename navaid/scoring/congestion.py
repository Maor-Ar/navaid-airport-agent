"""Axis-by-axis congestion compare. There is no single congestion score."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from navaid.schemas import ConstraintType
from navaid.scoring._util import iata_of, merge_metrics, optional_float
from navaid.scoring.envelope import make_envelope
from navaid.scoring.models import CongestionMetrics, CongestionResult

NUMERIC_AXES: tuple[str, ...] = (
    "delay_pct",
    "avg_arrival_delay_min",
    "cancel_pct",
    "ops_per_runway",
)
QUALITATIVE_AXES: tuple[str, ...] = (
    "live_faa_status",
    "constraint_type",
)
CONGESTION_AXES: tuple[str, ...] = NUMERIC_AXES + QUALITATIVE_AXES

_CONSTRAINT_BINDING = {
    ConstraintType.DEMAND_BOUND: 0,
    ConstraintType.LANDSIDE: 1,
    ConstraintType.MIXED: 2,
    ConstraintType.AIRSIDE: 3,
}

_CONGESTION_ASSUMPTIONS = (
    "Congestion is compared axis-by-axis; there is no single congestion score",
    "Higher delay, cancel, arrival delay, and ops per runway mean more congested on that axis",
    "Live FAA status is operations delay overlay, not passenger demand",
    "constraint_type winner is the more operationally binding constraint (airside > mixed > landside > demand-bound)",
)

_CONGESTION_SOURCES = (
    "BTS delay-cause",
    "OurAirports",
    "FAA NAS/ASWS",
    "curated constraints",
)


def _ops_per_runway(row: Mapping[str, Any]) -> float | None:
    direct = optional_float(row.get("ops_per_runway"))
    if direct is not None:
        return direct
    operations = optional_float(row.get("operations"))
    runways = optional_float(row.get("runway_count") or row.get("runways"))
    if operations is None or runways is None or runways <= 0:
        return None
    return operations / runways


def _constraint(row: Mapping[str, Any]) -> ConstraintType | None:
    raw = row.get("constraint_type")
    if raw is None or str(raw).strip() == "":
        return None
    return ConstraintType(str(raw).strip())


def _status_severity(status: str | None) -> float | None:
    if status is None or str(status).strip() == "":
        return None
    text = str(status).strip().lower()
    if text in {"normal", "none", "ok", "no delay", "no_delay", "clear"}:
        return 0.0
    if "ground stop" in text or text in {"gs", "ground_stop"}:
        return 2.0
    if any(token in text for token in ("delay", "gdp", "hold", "ground delay")):
        return 1.0
    return 1.0


def _metrics_for(row: Mapping[str, Any]) -> CongestionMetrics:
    return CongestionMetrics(
        delay_pct=optional_float(row.get("delay_pct")),
        avg_arrival_delay_min=optional_float(row.get("avg_arrival_delay_min")),
        cancel_pct=optional_float(row.get("cancel_pct")),
        ops_per_runway=_ops_per_runway(row),
        live_faa_status=(
            str(row["live_faa_status"]).strip()
            if row.get("live_faa_status") not in (None, "")
            else None
        ),
        constraint_type=_constraint(row),
        curfew=(
            str(row["curfew"]).strip()
            if row.get("curfew") not in (None, "")
            else None
        ),
    )


def _winner(values: Mapping[str, float | None]) -> str | None:
    present = {airport: value for airport, value in values.items() if value is not None}
    if not present:
        return None
    best = max(present.values())
    winners = [airport for airport, value in present.items() if value == best]
    if len(winners) > 1:
        return "tie"
    return winners[0]


def compare_congestion(
    airports: Sequence[Mapping[str, Any]],
    *,
    as_of: date | None = None,
    now: date | None = None,
    sources: Sequence[str] | None = None,
) -> CongestionResult:
    """Compare two or more airports on typed congestion axes. No composite score."""

    if len(airports) < 2:
        raise ValueError("congestion compare needs at least two airports")

    metrics: dict[str, CongestionMetrics] = {}
    order: list[str] = []
    for raw_row in airports:
        row = merge_metrics(raw_row)
        code = iata_of(row)
        if code in metrics:
            raise ValueError(f"duplicate airport in congestion compare: {code}")
        order.append(code)
        metrics[code] = _metrics_for(row)

    winners: dict[str, str | None] = {}
    for axis in NUMERIC_AXES:
        winners[axis] = _winner(
            {code: getattr(metrics[code], axis) for code in order}
        )
    winners["live_faa_status"] = _winner(
        {code: _status_severity(metrics[code].live_faa_status) for code in order}
    )
    winners["constraint_type"] = _winner(
        {
            code: (
                float(_CONSTRAINT_BINDING[metrics[code].constraint_type])
                if metrics[code].constraint_type is not None
                else None
            )
            for code in order
        }
    )

    missing_optional = any(
        getattr(metrics[code], axis) is None
        for code in order
        for axis in NUMERIC_AXES
    ) or any(metrics[code].live_faa_status is None for code in order)

    envelope = make_envelope(
        assumptions=_CONGESTION_ASSUMPTIONS,
        sources=sources or _CONGESTION_SOURCES,
        as_of=as_of,
        now=now,
        uncertainties=[],
        out_of_scope=["single congestion index", "passenger-perceived wait time"],
        missing_optional=missing_optional,
        missing_required=False,
    )
    return CongestionResult(
        airports=order,
        metrics=metrics,
        winner_on_each_axis=winners,
        envelope=envelope,
    )
