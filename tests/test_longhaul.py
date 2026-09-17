from __future__ import annotations

from datetime import date

from navaid.config import LONGHAUL_KM
from navaid.scoring import great_circle_km, km_to_statute_miles, longhaul_share

# OurAirports-style reference points. Tests pin km and miles separately.
ANC = (61.1744, -149.9960)
JFK = (40.6398, -73.7789)


def test_anc_jfk_great_circle_km_not_miles() -> None:
    km = great_circle_km(*ANC, *JFK)
    miles = km_to_statute_miles(km)
    assert 5300 < km < 5550
    assert abs(km - 5420) < 50
    assert 3300 < miles < 3450
    assert abs(miles - 3370) < 30
    # Mixing units would put ~3370 in the kilometre field.
    assert km > 5000
    assert miles < 4000
    assert km != miles


def test_default_threshold_is_4000_km() -> None:
    result = longhaul_share(
        airport="ANC",
        segments=[
            {"origin": "ANC", "dest": "SEA", "passengers": 100, "distance_km": 2300, "international": False},
            {"origin": "ANC", "dest": "JFK", "passengers": 50, "distance_km": 5420, "international": False},
            {"origin": "ANC", "dest": "NRT", "passengers": 50, "distance_km": 5500, "international": True},
        ],
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.threshold_km == LONGHAUL_KM == 4000
    assert result.passengers_total == 200
    assert result.passengers_longhaul == 100
    assert result.pct_longhaul == 50.0
    assert result.pct_international == 25.0
    assert result.pct_over_6h is None
    assert result.cargo_excluded is True


def test_pct_over_6h_optional_and_cargo_excluded() -> None:
    result = longhaul_share(
        {
            "airport": "ANC",
            "segments": [
                {
                    "origin": "ANC",
                    "dest": "JFK",
                    "passengers": 80,
                    "distance_km": 5420,
                    "hours": 7.5,
                    "international": False,
                },
                {
                    "origin": "ANC",
                    "dest": "SEA",
                    "passengers": 20,
                    "distance_km": 2300,
                    "hours": 3.5,
                    "international": False,
                },
                {
                    "origin": "ANC",
                    "dest": "ORD",
                    "passengers": 0,
                    "freight": 40,
                    "distance_km": 4500,
                    "cargo": True,
                },
            ],
        },
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.passengers_total == 100
    assert result.pct_over_6h == 80.0
    assert result.pct_longhaul == 80.0
    assert result.envelope.assumptions


def test_distance_from_coordinates_when_km_missing() -> None:
    result = longhaul_share(
        airport="ANC",
        segments=[
            {
                "origin": "ANC",
                "dest": "JFK",
                "passengers": 10,
                "international": False,
            }
        ],
        airports={
            "ANC": {"lat": ANC[0], "lon": ANC[1]},
            "JFK": {"latitude": JFK[0], "longitude": JFK[1]},
        },
        as_of=date(2024, 12, 31),
        now=date(2025, 1, 15),
    )
    assert result.passengers_longhaul == 10
    assert result.pct_longhaul == 100.0
    assert result.envelope.sources
