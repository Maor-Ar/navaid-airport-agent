"""Stable competition ranker.

Equal scores share a rank (3, 3, 5 — the next rank is skipped). Leftover ties
are ordered by ICAO ident ascending so the listing is deterministic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from math import isclose
from typing import Any

from navaid.scoring._util import icao_of, iata_of
from navaid.scoring.models import RankedItem


def _scores_tie(left: float, right: float) -> bool:
    return isclose(left, right, rel_tol=0.0, abs_tol=1e-9)


def stable_rank(
    items: Sequence[Mapping[str, Any]],
    *,
    score_key: str = "score",
    icao_key: str = "icao",
) -> list[RankedItem]:
    """Return items sorted by score descending, then ICAO ascending, with shared ranks.

    Competition ranking: two tied for 3rd both get rank 3; the next item is rank 5.
    """

    if not items:
        return []

    decorated: list[tuple[float, str, str, int, Mapping[str, Any]]] = []
    for index, row in enumerate(items):
        airport = iata_of(row)
        icao = str(row.get(icao_key) or icao_of(row, fallback=airport)).strip().upper()
        score = float(row[score_key])
        decorated.append((score, icao, airport, index, row))

    decorated.sort(key=lambda item: (-item[0], item[1], item[2], item[3]))

    ranked: list[RankedItem] = []
    i = 0
    n = len(decorated)
    while i < n:
        j = i + 1
        while j < n and _scores_tie(decorated[j][0], decorated[i][0]):
            j += 1
        rank = i + 1
        for score, icao, airport, _index, _row in decorated[i:j]:
            ranked.append(
                RankedItem(airport=airport, icao=icao, score=score, rank=rank)
            )
        i = j
    return ranked
