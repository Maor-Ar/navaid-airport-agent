from __future__ import annotations

from datetime import date

from navaid.config import UNMET_LOAD_FACTOR_THRESHOLD
from navaid.scoring import unmet_demand


def test_load_factor_gap_formula() -> None:
    result = unmet_demand(
        airport="SFO",
        served=1_000.0,
        load_factor=0.90,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    expected = 1_000.0 * (0.90 - 0.85) / 0.85
    assert result.lf_threshold == UNMET_LOAD_FACTOR_THRESHOLD == 0.85
    assert abs(result.lf_gap - expected) < 1e-12
    assert result.taf_gap is None
    assert result.leakage == 0.0
    assert abs(result.unmet - expected) < 1e-12
    assert result.envelope.as_of == date(2024, 12, 31)


def test_load_factor_gap_clamped_at_zero() -> None:
    result = unmet_demand(
        {"airport": "SFO", "served": 5_000_000, "load_factor": 0.80},
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.lf_gap == 0.0
    assert result.unmet == 0.0


def test_exact_threshold_is_zero_gap() -> None:
    result = unmet_demand(
        airport="SFO",
        served=2_000_000,
        load_factor=0.85,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.lf_gap == 0.0


def test_optional_taf_gap_clamped() -> None:
    over = unmet_demand(
        airport="SFO",
        served=10_000_000,
        load_factor=0.80,
        taf_10y=12_000_000,
        implied_current_capacity=10_000_000,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert over.taf_gap == 2_000_000
    assert over.unmet == 2_000_000

    under = unmet_demand(
        airport="SFO",
        served=10_000_000,
        load_factor=0.80,
        taf_10y=9_000_000,
        implied_current_capacity=10_000_000,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert under.taf_gap == 0.0


def test_same_cbsa_leakage_only_when_lf_high() -> None:
    peers = [
        {"airport": "OAK", "cbsa": "41860", "yoy": 0.08, "served": 5_000_000},
        {"airport": "SJC", "cbsa": "41860", "yoy": 0.01, "served": 6_000_000},
        {"airport": "LAX", "cbsa": "31080", "yoy": 0.20, "served": 40_000_000},
    ]
    leaking = unmet_demand(
        airport="SFO",
        served=20_000_000,
        load_factor=0.90,
        yoy=0.02,
        cbsa="41860",
        peers=peers,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert leaking.leakage_peers == ["OAK"]
    assert abs(leaking.leakage - 5_000_000 * (0.08 - 0.02)) < 1e-6
    assert leaking.unmet > leaking.lf_gap

    quiet = unmet_demand(
        airport="SFO",
        served=20_000_000,
        load_factor=0.80,
        yoy=0.02,
        cbsa="41860",
        peers=peers,
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert quiet.leakage == 0.0
    assert quiet.leakage_peers == []
