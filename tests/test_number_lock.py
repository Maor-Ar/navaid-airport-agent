from __future__ import annotations

from navaid.agent.number_lock import collect_allowed_numbers, lock_prose


def test_lock_allows_trace_numbers() -> None:
    payload = {
        "teoi_traces": [
            {
                "airport": "BDL",
                "teoi": 61.2,
                "rank": 2,
                "raw": {"enplanements": 3_285_194, "yoy": 0.052},
            }
        ]
    }
    allowed = collect_allowed_numbers(payload)
    assert "61.2" in allowed
    prose = "BDL ranks 2 with TEOI 61.2 on 3,285,194 enplanements."
    locked, stripped = lock_prose(prose, [payload])
    assert stripped == []
    assert "61.2" in locked
    assert "3,285,194" in locked


def test_lock_strips_invented_numbers() -> None:
    payload = {"unmet": 120000, "airport": "SFO"}
    locked, stripped = lock_prose(
        "SFO unmet is 120000 but TEOI is 99.4 and delay is 18%.",
        [payload],
    )
    assert "99.4" in stripped
    assert "18" in stripped or "18%" in stripped
    assert "99.4" not in locked
    assert "120000" in locked or "120,000" in locked


def test_lock_allows_ten_year_prose() -> None:
    locked, stripped = lock_prose("TAF 10-year forecast gap on a 100-point TEOI.", {"airport": "SFO"})
    assert "10" not in stripped
    assert "100" not in stripped
    assert "10-year" in locked

