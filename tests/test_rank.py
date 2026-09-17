from __future__ import annotations

from navaid.scoring import stable_rank


def test_shared_ranks_three_three_five() -> None:
    ranked = stable_rank(
        [
            {"airport": "BOS", "icao": "KBOS", "score": 90.0},
            {"airport": "MHT", "icao": "KMHT", "score": 80.0},
            {"airport": "PVD", "icao": "KPVD", "score": 70.0},
            {"airport": "BDL", "icao": "KBDL", "score": 70.0},
            {"airport": "BTV", "icao": "KBTV", "score": 50.0},
        ]
    )
    by_code = {item.airport: item for item in ranked}
    assert [item.rank for item in ranked] == [1, 2, 3, 3, 5]
    assert by_code["BOS"].rank == 1
    assert by_code["MHT"].rank == 2
    assert by_code["BDL"].rank == 3
    assert by_code["PVD"].rank == 3
    assert by_code["BTV"].rank == 5
    # Leftover ties ordered by ICAO ident ascending (KBDL before KPVD).
    tied = [item.airport for item in ranked if item.rank == 3]
    assert tied == ["BDL", "PVD"]
    assert [item.airport for item in ranked] == ["BOS", "MHT", "BDL", "PVD", "BTV"]


def test_first_place_tie_skips_to_three() -> None:
    ranked = stable_rank(
        [
            {"airport": "AAA", "icao": "KCCC", "score": 10.0},
            {"airport": "BBB", "icao": "KAAA", "score": 10.0},
            {"airport": "DDD", "icao": "KBBB", "score": 1.0},
        ]
    )
    assert [item.rank for item in ranked] == [1, 1, 3]
    assert [item.airport for item in ranked] == ["BBB", "AAA", "DDD"]
    assert [item.icao for item in ranked] == ["KAAA", "KCCC", "KBBB"]


def test_fallback_to_iata_when_icao_missing() -> None:
    ranked = stable_rank(
        [
            {"airport": "PVD", "score": 5.0},
            {"airport": "BDL", "score": 5.0},
        ]
    )
    assert [item.airport for item in ranked] == ["BDL", "PVD"]
    assert ranked[0].rank == ranked[1].rank == 1
