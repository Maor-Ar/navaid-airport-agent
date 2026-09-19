"""Typed payloads returned by deterministic engines."""

from __future__ import annotations

from typing import Any

from navaid.schemas import ConstraintType, Envelope, LockedModel, ScoringTrace


class RankedItem(LockedModel):
    airport: str
    icao: str
    score: float
    rank: int


class TeoiResult(LockedModel):
    peer_set: list[str]
    traces: list[ScoringTrace]
    ranking: list[dict[str, Any]]
    envelope: Envelope


class UnmetResult(LockedModel):
    airport: str
    served: float
    load_factor: float | None
    lf_threshold: float
    lf_gap: float | None
    taf_10y: float | None
    implied_current_capacity: float | None
    taf_gap: float | None
    leakage: float
    leakage_peers: list[str]
    leakage_gated: bool = False
    unmet: float
    envelope: Envelope


class LonghaulResult(LockedModel):
    airport: str
    threshold_km: float
    threshold_hours: float
    passengers_total: float
    passengers_longhaul: float
    pct_longhaul: float
    pct_longhaul_flights: float = 0.0
    pct_international: float
    pct_over_6h: float | None
    segments_counted: int
    segments_longhaul: int = 0
    cargo_excluded: bool
    anc_jfk_km: float | None = None
    anc_jfk_mi: float | None = None
    envelope: Envelope


class CongestionMetrics(LockedModel):
    delay_pct: float | None = None
    avg_arrival_delay_min: float | None = None
    cancel_pct: float | None = None
    ops_per_runway: float | None = None
    live_faa_status: str | None = None
    constraint_type: ConstraintType | None = None
    curfew: str | None = None


class CongestionResult(LockedModel):
    airports: list[str]
    metrics: dict[str, CongestionMetrics]
    winner_on_each_axis: dict[str, str | None]
    envelope: Envelope
