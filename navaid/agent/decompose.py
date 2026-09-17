"""Split a (reconstructed) question into closed-intent subgoals. All are executed."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from navaid.agent.entities import extract_airports, is_new_england
from navaid.config import NEW_ENGLAND_IATA
from navaid.schemas import Intent, Subgoal, SubgoalStatus

if TYPE_CHECKING:
    from navaid.agent.sessions import SessionMemory
    from navaid.warehouse.metrics import MetricsCatalog

_UNSUPPORTED_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bbuy\s+([A-Z]{1,5})\b", re.IGNORECASE), "equity ticker is out of scope"),
    (re.compile(r"\bAAL\b"), "airline ticker AAL is not an airport"),
    (re.compile(r"\brestaurant\b", re.IGNORECASE), "restaurants are out of scope"),
    (re.compile(r"\b(stock|ticker|equities|share price)\b", re.IGNORECASE), "securities are out of scope"),
)

_EXPLAIN = re.compile(
    r"explain teoi|why is #?\d+|traces for rank|why does|why has|this (teoi )?score|"
    r"do not re-rank|reuse last teoi",
    re.IGNORECASE,
)
_EXPAND = re.compile(
    r"\b(expand|expansion|candidates?|rank|ranking|teoi|terminal renovation|strong candidate)\b",
    re.IGNORECASE,
)
_CONGEST = re.compile(
    r"\b(congest|delay levels|compare .+ congest|congestion levels)\b",
    re.IGNORECASE,
)
_COMPARE = re.compile(r"\bcompare\b", re.IGNORECASE)
_LONGHAUL = re.compile(r"\blong[\s-]?haul\b", re.IGNORECASE)
_UNMET = re.compile(r"\bunmet\b", re.IGNORECASE)
_BRIEF = re.compile(r"\b(brief|metrics|snapshot|profile)\b", re.IGNORECASE)
_CARGO = re.compile(r"\bcargo\b", re.IGNORECASE)


def decompose(
    question: str,
    *,
    session: SessionMemory | None = None,
    catalog: MetricsCatalog | None = None,
    reuse_traces: bool = False,
    rerun_ranker: bool = False,
) -> list[Subgoal]:
    """Emit one closed intent per part. Compound questions keep every part."""

    q = question.strip()
    subgoals: list[Subgoal] = []
    used_unsupported: set[str] = set()

    for pattern, reason in _UNSUPPORTED_PATTERNS:
        match = pattern.search(q)
        if match and reason not in used_unsupported:
            used_unsupported.add(reason)
            snippet = match.group(0)
            # One refusal for equity (buy AAL + AAL ticker are the same part).
            if subgoals and subgoals[-1].intent == Intent.UNSUPPORTED and "ticker" in reason:
                continue
            subgoals.append(
                Subgoal(
                    intent=Intent.UNSUPPORTED,
                    entities=[],
                    status=SubgoalStatus.PENDING,
                    query=snippet,
                    notes=reason,
                )
            )

    entities = extract_airports(q, session=session, catalog=catalog)
    if is_new_england(q) and not entities:
        entities = list(NEW_ENGLAND_IATA)
        if catalog is not None:
            try:
                entities = catalog.iata_in_region("New England") or entities
            except Exception:
                pass

    if reuse_traces or _EXPLAIN.search(q):
        subgoals.append(
            Subgoal(
                intent=Intent.EXPLAIN_TEOI,
                entities=entities,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="reuse traces" if reuse_traces else "explain TEOI working",
            )
        )
    elif rerun_ranker or (
        (_EXPAND.search(q) or is_new_england(q)) and not _EXPLAIN.search(q)
    ):
        region_entities = entities
        if is_new_england(q) and not rerun_ranker:
            region_entities = list(NEW_ENGLAND_IATA)
            if catalog is not None:
                try:
                    region_entities = catalog.iata_in_region("New England") or region_entities
                except Exception:
                    pass
        if rerun_ranker and entities:
            region_entities = entities
        subgoals.append(
            Subgoal(
                intent=Intent.EXPANSION_RANK,
                entities=region_entities,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="peer-relative TEOI; Gemini may not invent a rank",
            )
        )

    if _CONGEST.search(q) or (_COMPARE.search(q) and not _EXPAND.search(q) and not _EXPLAIN.search(q)):
        compare_entities = list(entities)
        extra = [c for c in entities if c not in set(NEW_ENGLAND_IATA)]
        if is_new_england(q) and len(extra) >= 2:
            compare_entities = extra[:2]
        if len(compare_entities) < 2 and session is not None:
            compare_entities = list(session.last_entities or [])
        subgoals.append(
            Subgoal(
                intent=Intent.CONGESTION_COMPARE,
                entities=compare_entities,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="axis-by-axis congestion; no composite score",
            )
        )

    if _LONGHAUL.search(q):
        airport = entities[:1]
        if not airport and session is not None:
            airport = list(session.last_entities[:1])
        subgoals.append(
            Subgoal(
                intent=Intent.LONGHAUL_SHARE,
                entities=airport,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="include cargo" if _CARGO.search(q) else "cargo excluded unless asked",
            )
        )

    if _UNMET.search(q):
        airport = entities[:1]
        if not airport and session is not None:
            airport = list(session.last_entities[:1])
        subgoals.append(
            Subgoal(
                intent=Intent.UNMET_DEMAND,
                entities=airport,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="unmet = max(0, implied - served)",
            )
        )

    if _BRIEF.search(q) and not any(
        s.intent in {Intent.EXPANSION_RANK, Intent.AIRPORT_BRIEF} for s in subgoals
    ):
        subgoals.append(
            Subgoal(
                intent=Intent.AIRPORT_BRIEF,
                entities=entities[:1],
                status=SubgoalStatus.PENDING,
                query=q,
                notes="warehouse metrics only",
            )
        )

    # Compound: "compare LAX and SNA" inside a larger expansion question.
    if (
        _COMPARE.search(q)
        and len(entities) >= 2
        and not any(s.intent == Intent.CONGESTION_COMPARE for s in subgoals)
        and (_EXPAND.search(q) or is_new_england(q) or any(s.intent == Intent.UNSUPPORTED for s in subgoals))
    ):
        # Prefer the pair that is not the full New England set.
        pair = [c for c in entities if c not in set(NEW_ENGLAND_IATA)] or entities[:2]
        if len(pair) >= 2:
            subgoals.append(
                Subgoal(
                    intent=Intent.CONGESTION_COMPARE,
                    entities=pair[:2],
                    status=SubgoalStatus.PENDING,
                    query=q,
                    notes="axis-by-axis congestion; no composite score",
                )
            )

    supported = [s for s in subgoals if s.intent != Intent.UNSUPPORTED]
    if not supported:
        if len(entities) >= 2 and _COMPARE.search(q):
            subgoals.insert(
                0,
                Subgoal(
                    intent=Intent.CONGESTION_COMPARE,
                    entities=entities,
                    status=SubgoalStatus.PENDING,
                    query=q,
                ),
            )
        elif len(entities) == 1:
            subgoals.insert(
                0,
                Subgoal(
                    intent=Intent.AIRPORT_BRIEF,
                    entities=entities,
                    status=SubgoalStatus.PENDING,
                    query=q,
                ),
            )
        elif is_new_england(q):
            subgoals.insert(
                0,
                Subgoal(
                    intent=Intent.EXPANSION_RANK,
                    entities=list(NEW_ENGLAND_IATA),
                    status=SubgoalStatus.PENDING,
                    query=q,
                ),
            )
        elif subgoals:
            pass
        else:
            subgoals.append(
                Subgoal(
                    intent=Intent.AIRPORT_BRIEF,
                    entities=entities,
                    status=SubgoalStatus.PENDING,
                    query=q,
                    notes="fallback brief",
                )
            )

    return subgoals
