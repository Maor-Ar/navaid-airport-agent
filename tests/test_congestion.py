from __future__ import annotations

from datetime import date

from navaid.scoring import compare_congestion
from navaid.scoring.congestion import CONGESTION_AXES
from navaid.scoring.models import CongestionResult


def test_typed_payload_no_fake_score() -> None:
    result = compare_congestion(
        [
            {
                "airport": "LAX",
                "delay_pct": 0.25,
                "avg_arrival_delay_min": 18.4,
                "cancel_pct": 0.04,
                "ops_per_runway": 80_000,
                "live_faa_status": "ground delay program",
                "constraint_type": "mixed",
            },
            {
                "airport": "SNA",
                "delay_pct": 0.18,
                "avg_arrival_delay_min": 12.1,
                "cancel_pct": 0.02,
                "operations": 300_000,
                "runway_count": 2,
                "live_faa_status": "normal",
                "constraint_type": "airside",
            },
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )

    assert result.airports == ["LAX", "SNA"]
    assert set(result.winner_on_each_axis) == set(CONGESTION_AXES)
    assert set(CONGESTION_AXES) == {
        "delay_pct",
        "avg_arrival_delay_min",
        "cancel_pct",
        "ops_per_runway",
        "live_faa_status",
        "constraint_type",
    }
    assert result.metrics["LAX"].delay_pct == 0.25
    assert result.metrics["SNA"].ops_per_runway == 150_000
    assert result.winner_on_each_axis["delay_pct"] == "LAX"
    assert result.winner_on_each_axis["avg_arrival_delay_min"] == "LAX"
    assert result.winner_on_each_axis["cancel_pct"] == "LAX"
    assert result.winner_on_each_axis["ops_per_runway"] == "SNA"
    assert result.winner_on_each_axis["live_faa_status"] == "LAX"
    assert result.winner_on_each_axis["constraint_type"] == "SNA"

    dumped = result.model_dump()
    assert "congestion_score" not in dumped
    assert "score" not in dumped
    assert "congestion_score" not in CongestionResult.model_fields
    assert result.envelope.as_of == date(2024, 12, 31)
    assert "no single congestion score" in " ".join(result.envelope.assumptions).lower()


def test_tie_on_axis_and_missing_live_status() -> None:
    result = compare_congestion(
        [
            {"airport": "AAA", "delay_pct": 0.20, "constraint_type": "landside"},
            {"airport": "BBB", "delay_pct": 0.20, "constraint_type": "landside"},
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.winner_on_each_axis["delay_pct"] == "tie"
    assert result.winner_on_each_axis["ops_per_runway"] is None
    assert result.winner_on_each_axis["live_faa_status"] is None
    assert result.winner_on_each_axis["constraint_type"] == "tie"
    assert result.envelope.confidence.value in {"medium", "low"}
