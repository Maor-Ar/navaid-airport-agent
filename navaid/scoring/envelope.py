"""Envelope builder shared by every scoring engine.

A snapshot older than ``STALE_SNAPSHOT_DAYS`` is always listed as an uncertainty.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from navaid.config import STALE_SNAPSHOT_DAYS
from navaid.schemas import Confidence, Envelope

STALE_UNCERTAINTY = (
    f"warehouse snapshot is older than {STALE_SNAPSHOT_DAYS} days"
)
UNKNOWN_AS_OF_UNCERTAINTY = "snapshot as_of is unknown"


def snapshot_is_stale(as_of: date | None, *, now: date | None = None) -> bool:
    if as_of is None:
        return False
    today = now or date.today()
    return (today - as_of).days > STALE_SNAPSHOT_DAYS


def infer_confidence(
    *,
    stale: bool,
    unknown_as_of: bool,
    missing_optional: bool,
    missing_required: bool,
) -> Confidence:
    if missing_required or stale:
        return Confidence.LOW
    if unknown_as_of or missing_optional:
        return Confidence.MEDIUM
    return Confidence.HIGH


def make_envelope(
    *,
    assumptions: Sequence[str],
    sources: Sequence[str],
    as_of: date | None = None,
    now: date | None = None,
    uncertainties: Sequence[str] | None = None,
    out_of_scope: Sequence[str] | None = None,
    confidence: Confidence | None = None,
    missing_optional: bool = False,
    missing_required: bool = False,
) -> Envelope:
    notes = list(uncertainties or [])
    stale = snapshot_is_stale(as_of, now=now)
    unknown_as_of = as_of is None
    if stale and STALE_UNCERTAINTY not in notes:
        notes.append(STALE_UNCERTAINTY)
    if unknown_as_of and UNKNOWN_AS_OF_UNCERTAINTY not in notes:
        notes.append(UNKNOWN_AS_OF_UNCERTAINTY)
    if confidence is None:
        confidence = infer_confidence(
            stale=stale,
            unknown_as_of=unknown_as_of,
            missing_optional=missing_optional,
            missing_required=missing_required,
        )
    return Envelope(
        assumptions=list(assumptions),
        uncertainties=notes,
        out_of_scope=list(out_of_scope or []),
        confidence=confidence,
        sources=list(sources),
        as_of=as_of,
    )
