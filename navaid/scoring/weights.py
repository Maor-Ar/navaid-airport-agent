"""TEOI feature weights and constraint multipliers.

Source of truth is ``navaid.config`` (sum-to-1.0 is checked at import).
This module is the scoring-package import path referenced by the architecture doc.
"""

from __future__ import annotations

from navaid.config import CONSTRAINT_EXPLANATIONS, CONSTRAINT_MULTIPLIERS, TEOI_WEIGHTS

FEATURE_ORDER: tuple[str, ...] = tuple(TEOI_WEIGHTS.keys())

__all__ = [
    "CONSTRAINT_EXPLANATIONS",
    "CONSTRAINT_MULTIPLIERS",
    "FEATURE_ORDER",
    "TEOI_WEIGHTS",
]
