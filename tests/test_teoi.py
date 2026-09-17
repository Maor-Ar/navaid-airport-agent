from __future__ import annotations

from datetime import date

from navaid.config import CONSTRAINT_MULTIPLIERS, TEOI_WEIGHTS
from navaid.schemas import Confidence, ConstraintType, ScoringTrace
from navaid.scoring import drop_and_renormalize, rank_expansion, score_teoi
from navaid.scoring.weights import FEATURE_ORDER


def _base_features(**overrides: float | None) -> dict[str, float | None]:
    features = {
        "demand_pressure": 50.0,
        "congestion": 0.20,
        "landside_saturation": 80_000.0,
        "unmet_demand": 100_000.0,
        "yield_mix": 0.30,
        "growth_outlook": 0.04,
        "capital_feasibility": 0.8,
    }
    features.update(overrides)
    return features


def test_teoi_weights_sum_to_one() -> None:
    assert abs(sum(TEOI_WEIGHTS.values()) - 1.0) < 1e-12
    assert FEATURE_ORDER == tuple(TEOI_WEIGHTS.keys())


def test_drop_and_renormalize_capital_feasibility() -> None:
    used = drop_and_renormalize(["capital_feasibility"])
    assert "capital_feasibility" not in used
    assert abs(sum(used.values()) - 1.0) < 1e-12
    assert used["demand_pressure"] == TEOI_WEIGHTS["demand_pressure"] / 0.95


def test_peer_minmax_and_full_trace() -> None:
    result = score_teoi(
        [
            {
                "airport": "bos",
                "icao": "KBOS",
                "constraint_type": "mixed",
                "enplanements": 20_000_000,
                **_base_features(demand_pressure=100.0, congestion=0.40),
            },
            {
                "airport": "bdl",
                "icao": "KBDL",
                "constraint_type": "landside",
                "enplanements": 3_285_194,
                "yoy": 0.052,
                **_base_features(demand_pressure=40.0, congestion=0.20),
            },
            {
                "airport": "pvd",
                "icao": "KPVD",
                "constraint_type": "landside",
                **_base_features(demand_pressure=10.0, congestion=0.10),
            },
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )

    assert result.envelope.as_of == date(2024, 12, 31)
    assert result.envelope.confidence in {Confidence.HIGH, Confidence.MEDIUM}
    assert result.peer_set == ["BOS", "BDL", "PVD"]

    by_code = {trace.airport: trace for trace in result.traces}
    bos = by_code["BOS"]
    bdl = by_code["BDL"]
    pvd = by_code["PVD"]

    assert isinstance(bos, ScoringTrace)
    assert bos.scaled_0_1["demand_pressure"] == 1.0
    assert pvd.scaled_0_1["demand_pressure"] == 0.0
    assert abs(bdl.scaled_0_1["demand_pressure"] - (40.0 - 10.0) / (100.0 - 10.0)) < 1e-12

    assert bdl.raw["enplanements"] == 3_285_194
    assert bdl.constraint_type is ConstraintType.LANDSIDE
    assert bdl.constraint_multiplier == CONSTRAINT_MULTIPLIERS["landside"] == 1.00
    assert bos.constraint_multiplier == 0.75
    assert abs(bdl.teoi - bdl.weighted_sum * 1.00) < 1e-12
    assert abs(bos.teoi - bos.weighted_sum * 0.75) < 1e-12
    assert bdl.formula_text.startswith("TEOI = 100 * (")
    assert bdl.formula_text.endswith("* 1.00")
    assert set(bdl.weights_original) == set(TEOI_WEIGHTS)
    assert bdl.weights_dropped == []
    assert abs(sum(bdl.weights_used.values()) - 1.0) < 1e-9
    for name, weight in bdl.weights_used.items():
        assert abs(bdl.contributions[name] - 100.0 * weight * bdl.scaled_0_1[name]) < 1e-9
    assert abs(bdl.weighted_sum - sum(bdl.contributions.values())) < 1e-9
    assert all(trace.rank >= 1 for trace in result.traces)
    assert {row["airport"] for row in result.ranking} == {"BOS", "BDL", "PVD"}


def test_missing_feature_dropped_per_airport() -> None:
    result = score_teoi(
        [
            {
                "airport": "BDL",
                "icao": "KBDL",
                "constraint_type": "landside",
                **_base_features(capital_feasibility=None),
            },
            {
                "airport": "PVD",
                "icao": "KPVD",
                "constraint_type": "landside",
                **_base_features(),
            },
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    bdl = next(trace for trace in result.traces if trace.airport == "BDL")
    pvd = next(trace for trace in result.traces if trace.airport == "PVD")
    assert bdl.weights_dropped == ["capital_feasibility"]
    assert bdl.scaled_0_1["capital_feasibility"] is None
    assert abs(sum(bdl.weights_used.values()) - 1.0) < 1e-9
    assert "capital_feasibility" not in bdl.weights_used
    assert "capital_feasibility" in pvd.weights_used
    assert "dropped and renormalized" in " ".join(result.envelope.uncertainties)


def test_airside_multiplier_penalizes_versus_landside() -> None:
    shared = _base_features(demand_pressure=50.0)
    result = score_teoi(
        [
            {"airport": "AAA", "icao": "KAAA", "constraint_type": "landside", **shared},
            {"airport": "BBB", "icao": "KBBB", "constraint_type": "airside", **shared},
            {"airport": "CCC", "icao": "KCCC", "constraint_type": "demand-bound", **shared},
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    by_code = {trace.airport: trace for trace in result.traces}
    assert by_code["AAA"].constraint_multiplier == 1.00
    assert by_code["BBB"].constraint_multiplier == 0.40
    assert by_code["CCC"].constraint_multiplier == 0.30
    assert by_code["AAA"].teoi > by_code["BBB"].teoi > by_code["CCC"].teoi
    assert by_code["AAA"].rank == 1


def test_rank_expansion_alias_and_single_peer() -> None:
    result = rank_expansion(
        [
            {
                "airport": "PWM",
                "icao": "KPWM",
                "constraint_type": "landside",
                **_base_features(),
            }
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.traces[0].scaled_0_1["demand_pressure"] == 0.5
    assert result.traces[0].rank == 1
    assert result.envelope.sources
