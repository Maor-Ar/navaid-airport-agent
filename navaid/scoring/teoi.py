"""Terminal Expansion Opportunity Index (TEOI) scorer.

Peer-relative min-max inside comparison set S. Missing features are dropped
and remaining weights renormalized. Constraint multiplier is applied after the
weighted sum. Every airport gets a full ScoringTrace.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from navaid.schemas import ConstraintType
from navaid.scoring._util import icao_of, iata_of, merge_metrics, optional_float
from navaid.scoring.envelope import make_envelope
from navaid.scoring.models import TeoiResult
from navaid.scoring.rank import stable_rank
from navaid.scoring.trace import build_trace, drop_and_renormalize, minmax_scale
from navaid.scoring.weights import FEATURE_ORDER

_TEOI_ASSUMPTIONS = (
    "TEOI is peer-relative min-max inside the comparison set S, not a national score",
    "Missing features are dropped and remaining weights are renormalized to 1.0",
    "Constraint multiplier encodes landside vs airside vs demand-bound investability",
    "Profit proxy is capacity unlock, not PFC/bond/NPV",
)

_TEOI_SOURCES = (
    "FAA enplanements",
    "BTS delay-cause",
    "FAA TAF",
    "NPIAS",
    "curated constraints",
)

_RAW_EXTRA = (
    "enplanements",
    "yoy",
    "pax_per_gate",
    "delay_pct",
    "lf",
    "load_factor",
    "gate_count",
    "operations",
)


def _feature_value(row: Mapping[str, Any], name: str) -> float | None:
    nested = row.get("features")
    if isinstance(nested, Mapping) and name in nested:
        return optional_float(nested.get(name))
    return optional_float(row.get(name))


def _constraint_type(row: Mapping[str, Any]) -> ConstraintType:
    raw = row.get("constraint_type")
    if raw is None or str(raw).strip() == "":
        raise ValueError(f"{iata_of(row)} is missing constraint_type")
    return ConstraintType(str(raw).strip())


def _raw_payload(row: Mapping[str, Any], features: Mapping[str, float | None]) -> dict[str, float | None]:
    payload: dict[str, float | None] = dict(features)
    for key in _RAW_EXTRA:
        value = optional_float(row.get(key))
        if value is not None:
            payload[key] = value
    nested = row.get("raw")
    if isinstance(nested, Mapping):
        for key, value in nested.items():
            number = optional_float(value)
            if number is not None:
                payload[str(key)] = number
    return payload


def score_teoi(
    airports: Sequence[Mapping[str, Any]],
    *,
    as_of: date | None = None,
    now: date | None = None,
    sources: Sequence[str] | None = None,
) -> TeoiResult:
    """Score every airport in S and attach a full ScoringTrace.

    Each row is an in-memory metrics dict. Feature keys are the seven TEOI
    terms; extra numeric fields are copied into ``raw`` for the waterfall.
    """

    if not airports:
        raise ValueError("peer set S must not be empty")

    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw_row in airports:
        row = merge_metrics(raw_row)
        airport = iata_of(row)
        if airport in seen:
            raise ValueError(f"duplicate airport in peer set S: {airport}")
        seen.add(airport)
        row["airport"] = airport
        row["icao"] = icao_of(row, fallback=airport)
        row["constraint_type"] = _constraint_type(row)
        rows.append(row)

    peer_set = [row["airport"] for row in rows]

    feature_raw: dict[str, dict[str, float | None]] = {
        name: {row["airport"]: _feature_value(row, name) for row in rows}
        for name in FEATURE_ORDER
    }
    feature_scaled = {
        name: minmax_scale(values) for name, values in feature_raw.items()
    }

    scored: list[dict[str, Any]] = []
    any_dropped = False
    all_dropped = True
    for row in rows:
        airport = row["airport"]
        dropped = [
            name
            for name in FEATURE_ORDER
            if feature_raw[name][airport] is None
        ]
        if dropped:
            any_dropped = True
        used = drop_and_renormalize(dropped)
        if used:
            all_dropped = False
        scaled = {name: feature_scaled[name][airport] for name in FEATURE_ORDER}
        raw = _raw_payload(row, {name: feature_raw[name][airport] for name in FEATURE_ORDER})
        scored.append(
            {
                "airport": airport,
                "icao": row["icao"],
                "dropped": dropped,
                "used": used,
                "scaled": scaled,
                "raw": raw,
                "constraint_type": row["constraint_type"],
            }
        )

    # Provisional TEOI (rank 1 placeholder) so the ranker can sort, then rebuild traces.
    provisional: list[dict[str, Any]] = []
    for item in scored:
        trace = build_trace(
            airport=item["airport"],
            peer_set=peer_set,
            raw=item["raw"],
            scaled_0_1=item["scaled"],
            weights_dropped=item["dropped"],
            weights_used=item["used"],
            constraint_type=item["constraint_type"],
            rank=1,
        )
        item["teoi"] = trace.teoi
        item["_trace"] = trace
        provisional.append(item)

    ranking = stable_rank(provisional, score_key="teoi")
    rank_by_airport = {item.airport: item.rank for item in ranking}

    traces = []
    for item in provisional:
        traces.append(
            build_trace(
                airport=item["airport"],
                peer_set=peer_set,
                raw=item["raw"],
                scaled_0_1=item["scaled"],
                weights_dropped=item["dropped"],
                weights_used=item["used"],
                constraint_type=item["constraint_type"],
                rank=rank_by_airport[item["airport"]],
            )
        )

    trace_by_airport = {trace.airport: trace for trace in traces}
    ordered_traces = [trace_by_airport[item.airport] for item in ranking]
    table = [
        {
            "rank": item.rank,
            "airport": item.airport,
            "icao": item.icao,
            "teoi": item.score,
            "constraint_type": str(trace_by_airport[item.airport].constraint_type),
        }
        for item in ranking
    ]

    dropped_names = sorted(
        {name for item in scored for name in item["dropped"]}
    )
    uncertainties: list[str] = []
    if dropped_names:
        uncertainties.append(
            "dropped and renormalized missing TEOI features: " + ", ".join(dropped_names)
        )

    envelope = make_envelope(
        assumptions=_TEOI_ASSUMPTIONS,
        sources=sources or _TEOI_SOURCES,
        as_of=as_of,
        now=now,
        uncertainties=uncertainties,
        out_of_scope=["PFC / NPV / airline equity"],
        missing_optional=any_dropped,
        missing_required=all_dropped,
    )
    return TeoiResult(
        peer_set=peer_set,
        traces=ordered_traces,
        ranking=table,
        envelope=envelope,
    )


def rank_expansion(
    airports: Sequence[Mapping[str, Any]],
    *,
    as_of: date | None = None,
    now: date | None = None,
    sources: Sequence[str] | None = None,
) -> TeoiResult:
    """Tool-facing alias: rank terminal-expansion candidates in set S."""

    return score_teoi(airports, as_of=as_of, now=now, sources=sources)
