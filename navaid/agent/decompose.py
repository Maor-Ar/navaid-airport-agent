"""Split a (reconstructed) question into closed-intent subgoals. All are executed."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from navaid.agent.entities import extract_airports, is_new_england
from navaid.agent.reconstruct import core_question, is_constraint_explain, is_meta_question
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
_CHITCHAT = re.compile(
    r"^\s*(hi+|hello|hey+|thanks|thank you|thx|good (morning|afternoon|evening)|yo)"
    r"[\s!.?,]*$",
    re.IGNORECASE,
)
_CAPABILITIES = re.compile(
    r"what can you do|what do you do|who are you|what are you|"
    r"tell me what (you can|can you) do|your capabilities|\bcapabilities\b|"
    r"^\s*help(?:\s+me)?\s*[?.!]?\s*$",
    re.IGNORECASE,
)
_GLOSSARY = re.compile(
    r"\b(what(?:'s|s| is| are)|define|meaning of|explain)\b.{0,48}"
    r"\b(teoi|landside|airside|t-?100|leakage|taf|npias)\b",
    re.IGNORECASE,
)


def _domain_question(q: str) -> bool:
    return bool(
        _EXPAND.search(q)
        or _CONGEST.search(q)
        or _COMPARE.search(q)
        or _LONGHAUL.search(q)
        or _UNMET.search(q)
        or _BRIEF.search(q)
        or _EXPLAIN.search(q)
        or is_new_england(q)
    )


def decompose(
    question: str,
    *,
    session: SessionMemory | None = None,
    catalog: MetricsCatalog | None = None,
    reuse_traces: bool = False,
    rerun_ranker: bool = False,
    explain_constraint: bool = False,
) -> list[Subgoal]:
    """Emit one closed intent per part. Compound questions keep every part."""

    q = question.strip()
    core = core_question(q)
    if not _domain_question(core) and (
        is_meta_question(q) or _CAPABILITIES.search(core) or _CHITCHAT.search(core)
    ):
        if _CHITCHAT.search(core) and not _CAPABILITIES.search(core):
            return [
                Subgoal(
                    intent=Intent.CHITCHAT,
                    status=SubgoalStatus.PENDING,
                    query=core,
                    notes="greeting",
                )
            ]
        return [
            Subgoal(
                intent=Intent.CAPABILITIES,
                status=SubgoalStatus.PENDING,
                query=core,
                notes="product capabilities",
            )
        ]

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

    if (
        not reuse_traces
        and _GLOSSARY.search(q)
        and not _EXPLAIN.search(q)
        and not _CONGEST.search(q)
        and not _LONGHAUL.search(q)
        and not _UNMET.search(q)
        and not _COMPARE.search(q)
        and not _BRIEF.search(q)
        and not is_new_england(q)
        and not entities
    ):
        return [
            Subgoal(
                intent=Intent.AIRPORT_BRIEF,
                entities=[],
                status=SubgoalStatus.PENDING,
                query=q,
                notes=f"glossary faq: {q}",
            )
        ]

    constraint_q = explain_constraint or is_constraint_explain(q, codes=entities, session=session)
    if constraint_q:
        focus = list(entities[:1])
        if not focus and session is not None:
            kind_match = re.search(
                r"\b(mixed|landside|airside|demand[- ]bound)\b", q, re.IGNORECASE
            )
            kind = (kind_match.group(1) if kind_match else "").lower().replace(" ", "-")
            for trace in session.last_traces or []:
                if not isinstance(trace, dict):
                    continue
                code = str(trace.get("airport") or "").strip().upper()
                if not code:
                    continue
                if kind and str(trace.get("constraint_type") or "").strip().lower() == kind:
                    focus = [code]
                    break
                if not focus:
                    focus = [code]
            if not focus and session.last_entities:
                focus = [session.last_entities[0]]
        subgoals.append(
            Subgoal(
                intent=Intent.EXPLAIN_CONSTRAINT,
                entities=focus,
                status=SubgoalStatus.PENDING,
                query=q,
                notes="constraint classifier; not a TEOI dump",
            )
        )
    elif reuse_traces or _EXPLAIN.search(q):
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
                notes="include cargo" if _CARGO.search(q) else "passenger segments only",
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
        if any(s.intent == Intent.UNSUPPORTED for s in subgoals):
            return subgoals
        if _GLOSSARY.search(q):
            subgoals.insert(
                0,
                Subgoal(
                    intent=Intent.AIRPORT_BRIEF,
                    entities=[],
                    status=SubgoalStatus.PENDING,
                    query=q,
                    notes=f"glossary faq: {q}",
                ),
            )
            return subgoals
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
