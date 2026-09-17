from __future__ import annotations

from datetime import date

from navaid.config import STALE_SNAPSHOT_DAYS
from navaid.schemas import Confidence
from navaid.scoring import make_envelope, score_teoi, snapshot_is_stale, unmet_demand


def test_stale_snapshot_is_always_an_uncertainty() -> None:
    as_of = date(2024, 1, 1)
    now = date(2024, 6, 1)
    assert (now - as_of).days > STALE_SNAPSHOT_DAYS
    assert snapshot_is_stale(as_of, now=now)

    envelope = make_envelope(
        assumptions=["test"],
        sources=["FAA"],
        as_of=as_of,
        now=now,
    )
    assert any("90" in note for note in envelope.uncertainties)
    assert envelope.confidence is Confidence.LOW


def test_fresh_snapshot_is_not_stale() -> None:
    as_of = date(2024, 12, 1)
    now = date(2025, 1, 15)
    assert not snapshot_is_stale(as_of, now=now)
    envelope = make_envelope(
        assumptions=["test"],
        sources=["FAA"],
        as_of=as_of,
        now=now,
    )
    assert not any("older than" in note for note in envelope.uncertainties)


def test_every_engine_returns_envelope() -> None:
    teoi = score_teoi(
        [
            {
                "airport": "BDL",
                "icao": "KBDL",
                "constraint_type": "landside",
                "demand_pressure": 1,
                "congestion": 1,
                "landside_saturation": 1,
                "unmet_demand": 1,
                "yield_mix": 1,
                "growth_outlook": 1,
                "capital_feasibility": 1,
            }
        ],
        as_of=date(2022, 1, 1),
        now=date(2024, 12, 31),
    )
    unmet = unmet_demand(
        airport="SFO",
        served=1,
        load_factor=0.9,
        as_of=date(2022, 1, 1),
        now=date(2024, 12, 31),
    )
    for envelope in (teoi.envelope, unmet.envelope):
        assert envelope.assumptions
        assert envelope.sources
        assert envelope.as_of == date(2022, 1, 1)
        assert any("90" in note for note in envelope.uncertainties)
