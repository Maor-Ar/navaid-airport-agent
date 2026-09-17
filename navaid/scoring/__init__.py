"""Deterministic engines (TEOI, unmet, long-haul, congestion, ranker).

Gemini may narrate these results; it may never produce a rank or KPI.
Every engine returns an Envelope. Inputs are in-memory metric dicts/lists.
"""

from navaid.scoring.congestion import CONGESTION_AXES, compare_congestion
from navaid.scoring.envelope import make_envelope, snapshot_is_stale
from navaid.scoring.longhaul import (
    great_circle_km,
    km_to_statute_miles,
    longhaul_share,
)
from navaid.scoring.models import (
    CongestionResult,
    LonghaulResult,
    RankedItem,
    TeoiResult,
    UnmetResult,
)
from navaid.scoring.rank import stable_rank
from navaid.scoring.teoi import rank_expansion, score_teoi
from navaid.scoring.trace import drop_and_renormalize, formula_text, minmax_scale
from navaid.scoring.unmet import unmet_demand
from navaid.scoring.weights import CONSTRAINT_MULTIPLIERS, FEATURE_ORDER, TEOI_WEIGHTS

__all__ = [
    "CONGESTION_AXES",
    "CONSTRAINT_MULTIPLIERS",
    "FEATURE_ORDER",
    "TEOI_WEIGHTS",
    "CongestionResult",
    "LonghaulResult",
    "RankedItem",
    "TeoiResult",
    "UnmetResult",
    "compare_congestion",
    "drop_and_renormalize",
    "formula_text",
    "great_circle_km",
    "km_to_statute_miles",
    "longhaul_share",
    "make_envelope",
    "minmax_scale",
    "rank_expansion",
    "score_teoi",
    "snapshot_is_stale",
    "stable_rank",
    "unmet_demand",
]
