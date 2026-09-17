"""TEOI waterfall helpers: min-max, drop-and-renormalize, formula text, traces."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from navaid.schemas import ConstraintType, ScoringTrace, constraint_multiplier_for
from navaid.scoring.weights import FEATURE_ORDER, TEOI_WEIGHTS


def minmax_scale(raw_by_airport: Mapping[str, float | None]) -> dict[str, float | None]:
    """Peer-relative min-max. Equal values in S scale to 0.5; missing stay None."""

    present = [value for value in raw_by_airport.values() if value is not None]
    scaled: dict[str, float | None] = {}
    if not present:
        return {key: None for key in raw_by_airport}
    lo = min(present)
    hi = max(present)
    span = hi - lo
    for airport, value in raw_by_airport.items():
        if value is None:
            scaled[airport] = None
        elif span == 0:
            scaled[airport] = 0.5
        else:
            scaled[airport] = (value - lo) / span
    return scaled


def drop_and_renormalize(dropped: Sequence[str]) -> dict[str, float]:
    dropped_set = set(dropped)
    remaining = {
        name: TEOI_WEIGHTS[name]
        for name in FEATURE_ORDER
        if name not in dropped_set
    }
    total = sum(remaining.values())
    if total <= 0:
        return {}
    return {name: weight / total for name, weight in remaining.items()}


def formula_text(weights_used: Mapping[str, float], multiplier: float) -> str:
    if not weights_used:
        return f"TEOI = 100 * (0) * {multiplier:.2f}"
    inner = " + ".join(
        f"{weights_used[name]:.3f}*{name}"
        for name in FEATURE_ORDER
        if name in weights_used
    )
    return f"TEOI = 100 * ({inner}) * {multiplier:.2f}"


def build_trace(
    *,
    airport: str,
    peer_set: Sequence[str],
    raw: Mapping[str, float | None],
    scaled_0_1: Mapping[str, float | None],
    weights_dropped: Sequence[str],
    weights_used: Mapping[str, float],
    constraint_type: ConstraintType | str,
    rank: int,
) -> ScoringTrace:
    constraint = ConstraintType(str(constraint_type))
    multiplier = constraint_multiplier_for(constraint)
    contributions = {
        name: 100.0 * weights_used[name] * float(scaled_0_1[name] or 0.0)
        for name in weights_used
    }
    weighted_sum = sum(contributions.values())
    return ScoringTrace(
        airport=airport,
        peer_set=list(peer_set),
        raw=dict(raw),
        scaled_0_1=dict(scaled_0_1),
        weights_original=dict(TEOI_WEIGHTS),
        weights_dropped=list(weights_dropped),
        weights_used=dict(weights_used),
        contributions=contributions,
        weighted_sum=weighted_sum,
        constraint_type=constraint,
        constraint_multiplier=multiplier,
        teoi=weighted_sum * multiplier,
        rank=rank,
        formula_text=formula_text(weights_used, multiplier),
    )
