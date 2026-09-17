"""Unmet demand: load-factor gap, optional TAF gap, same-CBSA leakage.

Every component is clamped at 0. Total unmet is the sum of present components.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any

from navaid.config import UNMET_LOAD_FACTOR_THRESHOLD
from navaid.scoring._util import iata_of, merge_metrics, optional_float
from navaid.scoring.envelope import make_envelope
from navaid.scoring.models import UnmetResult

_UNMET_ASSUMPTIONS = (
    "Unmet demand is max(0, implied - served); components are clamped at 0",
    f"Load-factor gap is served * max(0, LF - {UNMET_LOAD_FACTOR_THRESHOLD}) / {UNMET_LOAD_FACTOR_THRESHOLD}",
    "T-100 is segment traffic, not true O&D",
    "Leakage only counts same-CBSA peers growing faster while origin load factor is at or above the threshold",
)

_UNMET_SOURCES = (
    "BTS T-100",
    "FAA TAF",
    "FAA enplanements",
    "curated catchment CBSA",
)


def _lf_gap(served: float, load_factor: float | None, threshold: float) -> float | None:
    if load_factor is None:
        return None
    return served * max(0.0, load_factor - threshold) / threshold


def _taf_gap(
    taf_10y: float | None,
    implied_current_capacity: float | None,
) -> float | None:
    if taf_10y is None:
        return None
    if implied_current_capacity is None:
        return None
    return max(0.0, taf_10y - implied_current_capacity)


def _leakage(
    *,
    airport: str,
    load_factor: float | None,
    yoy: float | None,
    cbsa: str | None,
    peers: Sequence[Mapping[str, Any]],
    threshold: float,
) -> tuple[float, list[str], list[str]]:
    notes: list[str] = []
    if load_factor is None or load_factor < threshold:
        return 0.0, [], notes
    if not cbsa:
        notes.append("leakage skipped (origin CBSA missing)")
        return 0.0, [], notes
    if yoy is None:
        notes.append("leakage skipped (origin YoY missing)")
        return 0.0, [], notes

    leaked = 0.0
    names: list[str] = []
    comparable = False
    for peer in peers:
        peer_code = iata_of(peer)
        if peer_code == airport:
            continue
        peer_cbsa = str(peer.get("cbsa") or peer.get("cbsa_code") or "").strip()
        if peer_cbsa != str(cbsa).strip():
            continue
        peer_yoy = optional_float(peer.get("yoy"))
        if peer_yoy is None:
            continue
        comparable = True
        if peer_yoy > yoy:
            served = optional_float(peer.get("served") or peer.get("enplanements")) or 0.0
            leaked += max(0.0, (peer_yoy - yoy) * served)
            names.append(peer_code)
    if peers and not comparable:
        notes.append("leakage skipped (no same-CBSA peer YoY)")
    return leaked, names, notes


def unmet_demand(
    metrics: Mapping[str, Any] | None = None,
    /,
    *,
    airport: str | None = None,
    served: float | None = None,
    load_factor: float | None = None,
    taf_10y: float | None = None,
    implied_current_capacity: float | None = None,
    yoy: float | None = None,
    cbsa: str | None = None,
    peers: Sequence[Mapping[str, Any]] | None = None,
    as_of: date | None = None,
    now: date | None = None,
    lf_threshold: float | None = None,
) -> UnmetResult:
    """Compute clamped unmet demand from an in-memory metrics dict and optional peers."""

    row = merge_metrics(
        metrics,
        airport=airport,
        served=served,
        load_factor=load_factor,
        lf=load_factor,
        taf_10y=taf_10y,
        implied_current_capacity=implied_current_capacity,
        yoy=yoy,
        cbsa=cbsa,
    )
    code = iata_of(row)
    served_pax = optional_float(row.get("served") if row.get("served") is not None else row.get("enplanements"))
    if served_pax is None:
        raise ValueError(f"{code} unmet demand requires served passengers")

    lf = optional_float(row.get("load_factor"))
    if lf is None:
        lf = optional_float(row.get("lf"))
    threshold = float(lf_threshold if lf_threshold is not None else UNMET_LOAD_FACTOR_THRESHOLD)
    taf = optional_float(row.get("taf_10y"))
    capacity = optional_float(row.get("implied_current_capacity"))
    if capacity is None:
        capacity = served_pax

    lf_gap = _lf_gap(served_pax, lf, threshold)
    taf_gap = _taf_gap(taf, capacity if taf is not None else None)

    peer_rows = list(peers if peers is not None else row.get("peers") or ())
    leakage, leakage_peers, leak_notes = _leakage(
        airport=code,
        load_factor=lf,
        yoy=optional_float(row.get("yoy")),
        cbsa=(str(row["cbsa"]) if row.get("cbsa") else None),
        peers=peer_rows,
        threshold=threshold,
    )

    components = [value for value in (lf_gap, taf_gap) if value is not None]
    unmet = sum(components) + leakage

    uncertainties = list(leak_notes)
    missing_optional = False
    missing_required = lf is None
    if lf is None:
        uncertainties.append("load factor missing; load-factor gap omitted")
        missing_optional = True
    if taf is None:
        uncertainties.append("TAF 10-year forecast missing; forecast gap omitted")
        missing_optional = True

    envelope = make_envelope(
        assumptions=_UNMET_ASSUMPTIONS,
        sources=_UNMET_SOURCES,
        as_of=as_of if as_of is not None else row.get("as_of"),
        now=now,
        uncertainties=uncertainties,
        out_of_scope=["true O&D demand", "PFC / NPV"],
        missing_optional=missing_optional,
        missing_required=missing_required,
    )
    return UnmetResult(
        airport=code,
        served=served_pax,
        load_factor=lf,
        lf_threshold=threshold,
        lf_gap=lf_gap,
        taf_10y=taf,
        implied_current_capacity=capacity,
        taf_gap=taf_gap,
        leakage=leakage,
        leakage_peers=leakage_peers,
        unmet=unmet,
        envelope=envelope,
    )
