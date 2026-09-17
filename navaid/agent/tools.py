"""Typed Python tools Gemini may call. Engines do the math; RAG never ranks."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from navaid.agent.entities import extract_airports, is_new_england, resolve_one
from navaid.agent.jsonutil import jsonable
from navaid.agent.sessions import SessionMemory
from navaid.config import LONGHAUL_KM, NAVAID_OFFLINE, NEW_ENGLAND_IATA
from navaid.net.errors import CircuitOpenError, NavaidNetworkError, OfflineNetworkError
from navaid.net.faa_live import live_status_for
from navaid.rag.search import search_corpus as rag_search_corpus
from navaid.scoring.congestion import compare_congestion as engine_congestion
from navaid.scoring.longhaul import longhaul_share as engine_longhaul
from navaid.scoring.teoi import rank_expansion as engine_rank
from navaid.scoring.unmet import unmet_demand as engine_unmet
from navaid.warehouse.metrics import MetricsCatalog

TOOL_NAMES = (
    "resolve_airport",
    "rank_expansion",
    "compare_congestion",
    "longhaul_share",
    "unmet_demand",
    "airport_metrics",
    "explain_teoi",
    "search_corpus",
    "get_live_status",
)


@dataclass
class ToolContext:
    catalog: MetricsCatalog
    session: SessionMemory
    offline: bool = NAVAID_OFFLINE
    extra_traces: list[dict[str, Any]] = field(default_factory=list)


def _as_of(ctx: ToolContext):
    return ctx.catalog.as_of()


def _codes(airports: list[str] | str | None) -> list[str]:
    if airports is None:
        return []
    if isinstance(airports, str):
        airports = [airports]
    return [str(code).strip().upper() for code in airports if str(code).strip()]


def resolve_airport(ctx: ToolContext, query: str) -> dict[str, Any]:
    return jsonable(resolve_one(query, session=ctx.session, catalog=ctx.catalog))


def rank_expansion(
    ctx: ToolContext,
    airports: list[str] | str | None = None,
    region: str | None = None,
) -> dict[str, Any]:
    """Peer-relative TEOI rank. Always attaches a ScoringTrace list."""

    codes = _codes(airports)
    if region and not codes:
        codes = ctx.catalog.iata_in_region(region)
        if not codes and is_new_england(region):
            codes = list(NEW_ENGLAND_IATA)
    if not codes:
        codes = list(NEW_ENGLAND_IATA)
    rows = ctx.catalog.teoi_rows(codes)
    result = engine_rank(rows, as_of=_as_of(ctx))
    traces = jsonable(result.traces)
    ctx.extra_traces = list(traces)
    return jsonable(
        {
            "peer_set": result.peer_set,
            "ranking": result.ranking,
            "teoi_traces": traces,
            "envelope": result.envelope,
            "note": "Gemini may narrate these traces; it may not invent a rank",
        }
    )


def compare_congestion(ctx: ToolContext, airports: list[str] | str) -> dict[str, Any]:
    codes = _codes(airports)
    if len(codes) < 2:
        raise ValueError("compare_congestion needs at least two airports")
    rows = []
    for code in codes:
        row = ctx.catalog.base_metrics(code)
        if not ctx.offline:
            live = _live_overlay(code)
            if live.get("status"):
                row["live_faa_status"] = live["status"]
        rows.append(row)
    result = engine_congestion(rows, as_of=_as_of(ctx))
    return jsonable(
        {
            "airports": result.airports,
            "metrics": result.metrics,
            "winner_on_each_axis": result.winner_on_each_axis,
            "envelope": result.envelope,
            "note": "No single congestion score; compare axes",
        }
    )


def longhaul_share(
    ctx: ToolContext,
    airport: str,
    include_cargo: bool = False,
    threshold_km: float | None = None,
) -> dict[str, Any]:
    code = airport.strip().upper()
    row = ctx.catalog.base_metrics(code)
    result = engine_longhaul(
        row,
        segments=ctx.catalog.segments(code),
        airports=ctx.catalog.airport_coords(),
        threshold_km=threshold_km or LONGHAUL_KM,
        include_cargo=include_cargo,
        as_of=_as_of(ctx),
    )
    return jsonable(result)


def unmet_demand(ctx: ToolContext, airport: str) -> dict[str, Any]:
    code = airport.strip().upper()
    row = ctx.catalog.base_metrics(code)
    result = engine_unmet(
        row,
        peers=ctx.catalog.cbsa_peers(code),
        as_of=_as_of(ctx),
    )
    return jsonable(result)


def airport_metrics(ctx: ToolContext, airport: str) -> dict[str, Any]:
    row = ctx.catalog.teoi_row(airport.strip().upper())
    return jsonable(row)


def explain_teoi(
    ctx: ToolContext,
    airports: list[str] | str | None = None,
    ranks: list[int] | None = None,
    reuse_session: bool = True,
) -> dict[str, Any]:
    """Return traces without re-ranking when session traces exist."""

    traces = list(ctx.session.last_traces) if reuse_session else []
    if not traces:
        payload = rank_expansion(ctx, airports=airports)
        traces = list(payload.get("teoi_traces") or [])
        reused = False
    else:
        reused = True
    selected: list[dict[str, Any]] = list(traces)
    if ranks:
        want = {int(r) for r in ranks}
        selected = [t for t in traces if int(t.get("rank", -1)) in want]
    codes = _codes(airports)
    if codes:
        by_code = [t for t in selected if str(t.get("airport", "")).upper() in set(codes)]
        if by_code:
            selected = by_code
    return jsonable(
        {
            "reused_traces": reused,
            "ranks": ranks or [],
            "teoi_traces": selected,
            "peer_set": traces[0]["peer_set"] if traces else [],
            "note": "Reuse traces; do not invent a new ranking",
        }
    )


def search_corpus(ctx: ToolContext, query: str, airport: str | None = None) -> dict[str, Any]:
    """Airport-keyed FTS. Never returns a rank or TEOI."""

    hits = rag_search_corpus(
        query,
        airport=airport,
        db=ctx.catalog.connection,
        limit=8,
    )
    chunks = [hit.as_payload() for hit in hits]
    return {
        "chunks": chunks,
        "count": len(chunks),
        "note": "RAG never ranks. If notes and T-100 disagree, T-100 wins.",
    }


def get_live_status(ctx: ToolContext, airport: str) -> dict[str, Any]:
    code = airport.strip().upper()
    if ctx.offline:
        return {
            "airport": code,
            "available": False,
            "reason": "NAVAID_OFFLINE=1; live FAA status skipped",
        }
    return _live_overlay(code)


def _live_overlay(airport: str) -> dict[str, Any]:
    code = airport.strip().upper()
    try:
        status = live_status_for(code)
        return jsonable(
            {
                "airport": code,
                "available": True,
                "source": status.source,
                "delay": status.delay,
                "status": status.status,
                "reason": status.reason,
                "programs": status.programs,
                "fetched_at": status.fetched_at,
                "note": "Live overlay is operations delay, not a TEOI input",
            }
        )
    except (OfflineNetworkError, CircuitOpenError, NavaidNetworkError) as exc:
        return {"airport": code, "available": False, "reason": str(exc)}
    except Exception as exc:  # live feed must not fail the turn
        return {"airport": code, "available": False, "reason": str(exc)}


DISPATCH: dict[str, Callable[..., dict[str, Any]]] = {
    "resolve_airport": lambda ctx, **kw: resolve_airport(ctx, query=kw["query"]),
    "rank_expansion": lambda ctx, **kw: rank_expansion(
        ctx, airports=kw.get("airports"), region=kw.get("region")
    ),
    "compare_congestion": lambda ctx, **kw: compare_congestion(ctx, airports=kw["airports"]),
    "longhaul_share": lambda ctx, **kw: longhaul_share(
        ctx,
        airport=kw["airport"],
        include_cargo=bool(kw.get("include_cargo", False)),
        threshold_km=kw.get("threshold_km"),
    ),
    "unmet_demand": lambda ctx, **kw: unmet_demand(ctx, airport=kw["airport"]),
    "airport_metrics": lambda ctx, **kw: airport_metrics(ctx, airport=kw["airport"]),
    "explain_teoi": lambda ctx, **kw: explain_teoi(
        ctx,
        airports=kw.get("airports"),
        ranks=kw.get("ranks"),
        reuse_session=bool(kw.get("reuse_session", True)),
    ),
    "search_corpus": lambda ctx, **kw: search_corpus(
        ctx, query=kw.get("query") or "", airport=kw.get("airport")
    ),
    "get_live_status": lambda ctx, **kw: get_live_status(ctx, airport=kw["airport"]),
}


def call_tool(ctx: ToolContext, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in DISPATCH:
        return {"error": f"unknown tool {name}"}
    try:
        return DISPATCH[name](ctx, **(arguments or {}))
    except Exception as exc:
        return {"error": str(exc), "tool": name}


def plan_tools_for_subgoal(intent: str, entities: list[str], notes: str = "") -> list[tuple[str, dict[str, Any]]]:
    """Deterministic tool plan so every subgoal runs even if Gemini is silent."""

    codes = [c.upper() for c in entities]
    if intent == "EXPANSION_RANK":
        args: dict[str, Any] = {}
        if codes:
            args["airports"] = codes
        else:
            args["region"] = "New England"
        return [("rank_expansion", args)]
    if intent == "CONGESTION_COMPARE":
        return [("compare_congestion", {"airports": codes})]
    if intent == "LONGHAUL_SHARE":
        airport = codes[0] if codes else "ANC"
        return [
            (
                "longhaul_share",
                {
                    "airport": airport,
                    "include_cargo": "include cargo" in notes.lower() or "cargo" in notes.lower(),
                },
            )
        ]
    if intent == "UNMET_DEMAND":
        return [("unmet_demand", {"airport": codes[0] if codes else "SFO"})]
    if intent == "AIRPORT_BRIEF":
        airport = codes[0] if codes else "BOS"
        return [("airport_metrics", {"airport": airport}), ("search_corpus", {"query": airport, "airport": airport})]
    if intent == "EXPLAIN_TEOI":
        ranks = None
        return [("explain_teoi", {"airports": codes or None, "ranks": ranks, "reuse_session": True})]
    return []


# JSON schemas for Gemini function declarations (AFC disabled; we dispatch).
TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "resolve_airport",
        "description": "Resolve a place name or code to IATA. LA→LAX not metro; Santa Ana→SNA not SAT; Anchorage→ANC; those two from session.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "rank_expansion",
        "description": "Rank terminal-expansion candidates with full TEOI ScoringTrace list. Never invent a rank.",
        "parameters": {
            "type": "object",
            "properties": {
                "airports": {"type": "array", "items": {"type": "string"}},
                "region": {"type": "string", "description": "e.g. New England"},
            },
        },
    },
    {
        "name": "compare_congestion",
        "description": "Axis-by-axis congestion compare. No composite congestion score.",
        "parameters": {
            "type": "object",
            "properties": {
                "airports": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["airports"],
        },
    },
    {
        "name": "longhaul_share",
        "description": "T-100 long-haul passenger share. Default threshold 4000 km. Cargo out unless include_cargo.",
        "parameters": {
            "type": "object",
            "properties": {
                "airport": {"type": "string"},
                "include_cargo": {"type": "boolean"},
                "threshold_km": {"type": "number"},
            },
            "required": ["airport"],
        },
    },
    {
        "name": "unmet_demand",
        "description": "Clamped unmet demand: LF gap + TAF gap + same-CBSA leakage.",
        "parameters": {
            "type": "object",
            "properties": {"airport": {"type": "string"}},
            "required": ["airport"],
        },
    },
    {
        "name": "airport_metrics",
        "description": "Warehouse metrics dict for one IATA (enplanements, yoy, gates, delay, LF, TAF, CBSA, constraint, lat/lon).",
        "parameters": {
            "type": "object",
            "properties": {"airport": {"type": "string"}},
            "required": ["airport"],
        },
    },
    {
        "name": "explain_teoi",
        "description": "Return TEOI traces, reusing session traces when present. Do not invent a new ranking.",
        "parameters": {
            "type": "object",
            "properties": {
                "airports": {"type": "array", "items": {"type": "string"}},
                "ranks": {"type": "array", "items": {"type": "integer"}},
                "reuse_session": {"type": "boolean"},
            },
        },
    },
    {
        "name": "search_corpus",
        "description": "Search airport-keyed notes via DuckDB FTS. RAG never ranks. T-100 wins facts.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "airport": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_live_status",
        "description": "FAA NAS/ASWS live delay overlay. Not a TEOI input. Circuit-broken on failure.",
        "parameters": {
            "type": "object",
            "properties": {"airport": {"type": "string"}},
            "required": ["airport"],
        },
    },
]


__all__ = [
    "DISPATCH",
    "TOOL_NAMES",
    "TOOL_SCHEMAS",
    "ToolContext",
    "airport_metrics",
    "call_tool",
    "compare_congestion",
    "explain_teoi",
    "extract_airports",
    "get_live_status",
    "longhaul_share",
    "plan_tools_for_subgoal",
    "rank_expansion",
    "resolve_airport",
    "search_corpus",
    "unmet_demand",
]
