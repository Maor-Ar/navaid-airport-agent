"""Reconstruct → decompose → tools → number lock → Answer. Not LangChain."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from navaid.agent.decompose import decompose
from navaid.agent.gemini import GeminiRuntime, run_tool_loop
from navaid.agent.narrate import (
    gemini_prompt,
    lock_sections,
    mark_status,
    parse_gemini_sections,
    template_section,
    unsupported_from,
)
from navaid.agent.reconstruct import reconstruct
from navaid.agent.sessions import load_session, new_session_id, save_session
from navaid.agent.tools import ToolContext, call_tool, plan_tools_for_subgoal
from navaid.config import NAVAID_MODEL, NAVAID_OFFLINE, NEW_ENGLAND_IATA
from navaid.schemas import (
    Answer,
    Citation,
    Confidence,
    Envelope,
    Intent,
    MapPoint,
    ProcessEvent,
    ScoringTrace,
    Section,
    Step,
    Subgoal,
    UnsupportedPart,
    constraint_explanation_for,
)
from navaid.scoring.envelope import make_envelope
from navaid.warehouse.db import connect, init_schema
from navaid.warehouse.metrics import MetricsCatalog, require_snapshot


_SKIP_ENGINE_INTENTS = frozenset({Intent.UNSUPPORTED, Intent.CHITCHAT, Intent.CAPABILITIES})
_META_INTENTS = frozenset({Intent.CHITCHAT, Intent.CAPABILITIES})


def ask(
    question: str,
    *,
    session_id: str | None = None,
    warehouse_path: str | None = None,
    use_gemini: bool | None = None,
    runtime: GeminiRuntime | None = None,
) -> Answer:
    """Run one analyst turn and persist session memory in DuckDB."""

    q = (question or "").strip()
    if not q:
        raise ValueError("question is required")

    path = require_snapshot(warehouse_path)
    con = connect(path, read_only=False)
    steps: list[Step] = []
    try:
        init_schema(con)
        memory = load_session(con, session_id)
        catalog = MetricsCatalog(path, con=con)
        reconstruction = reconstruct(q, memory)
        _step(
            steps,
            "reconstruct",
            reconstruction.notes or ("no-op" if reconstruction.independent else "follow-up rewritten"),
        )

        subgoals = decompose(
            reconstruction.reconstructed_query,
            session=memory,
            catalog=catalog,
            reuse_traces=reconstruction.reuse_traces,
            rerun_ranker=reconstruction.rerun_ranker,
            explain_constraint=reconstruction.explain_constraint,
        )
        _step(
            steps,
            "decompose",
            ", ".join(f"{sg.intent.value}:{','.join(sg.entities) or '-'}" for sg in subgoals),
        )

        ctx = ToolContext(catalog=catalog, session=memory, offline=NAVAID_OFFLINE)
        payloads: list[dict[str, Any]] = []
        payload_by_subgoal: dict[int, dict[str, Any]] = {}
        traces: list[ScoringTrace] = []
        tables: dict[str, Any] = {}
        envelopes: list[Envelope] = []
        citations: list[Citation] = []
        process: list[ProcessEvent] = []

        for index, subgoal in enumerate(subgoals):
            if subgoal.intent in _SKIP_ENGINE_INTENTS:
                payload_by_subgoal[index] = (
                    {"unsupported": True} if subgoal.intent == Intent.UNSUPPORTED else {"meta": True}
                )
                continue
            planned = plan_tools_for_subgoal(subgoal.intent.value, subgoal.entities, subgoal.notes)
            if subgoal.intent == Intent.EXPLAIN_TEOI:
                ranks = _ranks_from_query(reconstruction.reconstructed_query)
                planned = [
                    (
                        "explain_teoi",
                        {
                            "airports": subgoal.entities or None,
                            "ranks": ranks,
                            "reuse_session": reconstruction.reuse_traces,
                        },
                    )
                ]
            thought_title, thought_detail = _thought_for(subgoal)
            process.append(ProcessEvent(kind="thought", title=thought_title, detail=thought_detail))
            last_payload: dict[str, Any] | None = None
            for name, arguments in planned:
                title = _tool_title(name, arguments, subgoal)
                process.append(ProcessEvent(kind="tool", title=title, detail=name))
                result = call_tool(ctx, name, arguments)
                last_payload = {"tool": name, "arguments": arguments, "result": result}
                payloads.append(last_payload)
                process.append(
                    ProcessEvent(kind="result", title=f"{title}", detail=_compact_result(name, result))
                )
                _step(steps, "tool", f"{name}({_brief_args(arguments)})")
                _ingest_result(result, traces, tables, envelopes, citations, name)
            if last_payload is not None:
                payload_by_subgoal[index] = last_payload
            _step(steps, "engines", f"subgoal {index} {subgoal.intent.value} executed")

        gemini = runtime
        if use_gemini is None:
            use_model = gemini.available if gemini is not None else bool(GeminiRuntime().available)
        else:
            use_model = bool(use_gemini)
        if use_model and gemini is None:
            gemini = GeminiRuntime()
            use_model = gemini.available

        meta_only = bool(subgoals) and all(sg.intent in _META_INTENTS for sg in subgoals)
        template_sections = [
            template_section(sg, payload_by_subgoal.get(i), i) for i, sg in enumerate(subgoals)
        ]
        sections = template_sections
        if use_model and gemini is not None and not meta_only:
            prompt = gemini_prompt(reconstruction.reconstructed_query, subgoals, payloads)
            try:
                text, extra_payloads, gemini_steps = run_tool_loop(
                    gemini, prompt, ctx, prior_payloads=payloads
                )
                payloads.extend(extra_payloads[len(payloads) :])
                for detail in gemini_steps:
                    _step(steps, "gemini", detail)
                parsed = parse_gemini_sections(text, subgoals)
                if parsed:
                    sections = _align_sections(parsed, template_sections, subgoals)
                elif text:
                    # Single blob: keep template structure, replace first supported body.
                    sections = list(template_sections)
                    for i, sg in enumerate(subgoals):
                        if sg.intent not in _SKIP_ENGINE_INTENTS:
                            sections[i] = Section(
                                heading=sections[i].heading,
                                body=text,
                                subgoal_index=i,
                            )
                            break
                _step(steps, "narrate", f"gemini {NAVAID_MODEL}")
            except Exception as exc:
                _step(steps, "narrate", f"gemini failed ({exc}); template fallback")
                sections = template_sections
        elif meta_only:
            _step(steps, "narrate", "template (meta; no engines)")
        else:
            _step(steps, "narrate", "template (Gemini not used)")

        locked, stripped = lock_sections(sections, payloads + traces)
        sections = locked
        if stripped:
            _step(steps, "lock", f"stripped invented numbers: {stripped[:12]}")
        else:
            _step(steps, "lock", "all numeric tokens present in tool JSON / traces")

        finished: list[Subgoal] = []
        unsupported: list[UnsupportedPart] = []
        for i, sg in enumerate(subgoals):
            ok = i in payload_by_subgoal and not (payload_by_subgoal[i].get("result") or {}).get("error")
            if sg.intent == Intent.UNSUPPORTED:
                ok = True
                unsupported.append(unsupported_from(sg, i))
            elif sg.intent in _META_INTENTS:
                ok = True
            elif payload_by_subgoal.get(i, {}).get("result", {}).get("error"):
                ok = False
            finished.append(mark_status(sg, ok))

        envelope = _merge_envelopes(envelopes, catalog.as_of(), unsupported)
        entities = _entities_from(finished, reconstruction.filled_airports)
        peer_set = tables.get("ranking_peer_set") or reconstruction.filled_airports or entities
        map_points = _map_points(catalog, tables, traces, finished)

        memory.remember(
            question=q,
            reconstructed_query=reconstruction.reconstructed_query,
            entities=entities,
            peer_set=list(peer_set) if isinstance(peer_set, list) else entities,
            payloads={p["tool"]: p["result"] for p in payloads if "tool" in p},
            traces=traces,
            intent=next(
                (s.intent.value for s in finished if s.intent not in _SKIP_ENGINE_INTENTS),
                None,
            ),
        )
        save_session(con, memory)

        return Answer(
            reconstructed_query=reconstruction.reconstructed_query,
            reconstruction_notes=reconstruction.notes,
            subgoals=finished,
            steps=steps,
            process=process,
            sections=sections,
            teoi_traces=traces,
            tables=tables,
            map_points=map_points,
            envelope=envelope,
            citations=citations,
            unsupported_parts=unsupported,
        )
    finally:
        con.close()


def _thought_for(subgoal: Subgoal) -> tuple[str, str]:
    if subgoal.intent == Intent.EXPANSION_RANK:
        return (
            "Peer-relative ranking",
            "TEOI is scored only inside this peer set. Ranker next.",
        )
    if subgoal.intent == Intent.CONGESTION_COMPARE:
        return (
            "Axis-by-axis congestion",
            "No single congestion score. Delay, cancellations, ops/runway, and constraint.",
        )
    if subgoal.intent == Intent.LONGHAUL_SHARE:
        return (
            "Long-haul on T-100 segments",
            "4000 km threshold; cargo off unless asked. Flight-segment share is the headline.",
        )
    if subgoal.intent == Intent.UNMET_DEMAND:
        return (
            "Unmet demand recipe",
            "Load-factor rule + TAF gap + same-metro leakage (gated if LF is under 85%).",
        )
    if subgoal.intent == Intent.EXPLAIN_TEOI:
        return (
            "Explain last TEOI",
            "Reuse traces; do not re-rank a singleton set.",
        )
    if subgoal.intent == Intent.EXPLAIN_CONSTRAINT:
        airport = (subgoal.entities[0] if subgoal.entities else "this airport")
        return (
            f"Constraint type at {airport}",
            "Classifier rule plus the warehouse figures that triggered the label. Not a TEOI dump.",
        )
    if subgoal.intent == Intent.AIRPORT_BRIEF:
        if "glossary" in (subgoal.notes or "").lower():
            return ("Local glossary", "Search warehouse notes only. No internet.")
        return ("Airport snapshot", "Warehouse metrics and notes for this airport.")
    return ("Plan", subgoal.notes or subgoal.intent.value)


def _tool_title(name: str, arguments: dict[str, Any], subgoal: Subgoal) -> str:
    codes = [str(c).upper() for c in (arguments.get("airports") or subgoal.entities or []) if c]
    airport = str(arguments.get("airport") or (codes[0] if codes else "")).upper()
    if name == "rank_expansion":
        region = arguments.get("region")
        if region or (codes and set(codes) <= set(NEW_ENGLAND_IATA)) or not codes:
            return "Ranking New England"
        return f"Ranking {', '.join(codes[:4])}"
    if name == "compare_congestion":
        if len(codes) >= 2:
            return f"Congestion {codes[0]} vs {codes[1]}"
        return "Congestion compare"
    if name == "longhaul_share":
        return f"Long-haul at {airport}" if airport else "Long-haul share"
    if name == "unmet_demand":
        return f"Unmet demand at {airport}" if airport else "Unmet demand"
    if name == "search_corpus":
        return "Notes search"
    if name == "airport_metrics":
        return f"Metrics for {airport}" if airport else "Airport metrics"
    if name == "explain_teoi":
        return "TEOI traces"
    if name == "explain_constraint":
        return f"Constraint type at {airport}" if airport else "Constraint type"
    if name == "get_live_status":
        return f"Live FAA at {airport}" if airport else "Live FAA status"
    if name == "resolve_airport":
        return "Resolve airport"
    return name.replace("_", " ")


def _fmt_compact(value: Any, *, digits: int = 1, percent: bool = False) -> str:
    if value is None or value == "":
        return "—"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if percent:
        shown = number * 100.0 if 0 <= abs(number) <= 1 else number
        text = f"{shown:.1f}".rstrip("0").rstrip(".")
        return f"{text}%"
    if abs(number) >= 1000:
        return f"{number:,.0f}"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _compact_result(tool: str, result: dict[str, Any] | None) -> str:
    if not isinstance(result, dict):
        return "no result"
    if result.get("error"):
        return str(result.get("error"))
    if tool == "rank_expansion":
        ranking = result.get("ranking") or []
        parts = []
        for row in ranking[:6]:
            if not isinstance(row, dict):
                continue
            teoi = _fmt_compact(row.get("teoi") or row.get("score"), digits=1)
            constraint = row.get("constraint_type") or ""
            parts.append(f"{row.get('airport')} {teoi} {constraint}".strip())
        extra = f" (+{len(ranking) - 6})" if len(ranking) > 6 else ""
        return " · ".join(parts) + extra
    if tool == "compare_congestion":
        winners = result.get("winner_on_each_axis") or {}
        axis_labels = {
            "delay_pct": "delay share",
            "avg_arrival_delay_min": "arrival delay",
            "cancel_pct": "cancellations",
            "ops_per_runway": "ops/runway",
            "live_faa_status": "live FAA",
            "constraint_type": "constraint",
        }
        bits = [
            f"{axis_labels.get(str(axis), str(axis).replace('_', ' '))}: {winner}"
            for axis, winner in list(winners.items())[:4]
        ]
        metrics = result.get("metrics") or {}
        for code, mets in metrics.items():
            if isinstance(mets, dict) and mets.get("curfew"):
                bits.append(f"{code} curfew")
        return " · ".join(bits) or "axis compare"
    if tool == "longhaul_share":
        return (
            f"flight-segment {_fmt_compact(result.get('pct_longhaul_flights'), digits=2)}% · "
            f"passenger {_fmt_compact(result.get('pct_longhaul'), digits=2)}%"
        )
    if tool == "unmet_demand":
        gated = result.get("leakage_gated")
        leak = "leakage gated" if gated else "leakage counted"
        return (
            f"LF {_fmt_compact(result.get('load_factor'), percent=True)} · {leak} · "
            f"unmet {_fmt_compact(result.get('unmet'))}"
        )
    if tool == "search_corpus":
        return f"{result.get('count') or 0} notes"
    if tool == "explain_teoi":
        traces = result.get("teoi_traces") or []
        parts = [
            f"{t.get('airport')} {_fmt_compact(t.get('teoi'), digits=1)}"
            for t in traces[:4]
            if isinstance(t, dict)
        ]
        return " · ".join(parts) or "traces"
    if tool == "explain_constraint":
        code = result.get("iata") or result.get("airport") or ""
        constraint = result.get("constraint_type") or ""
        return f"{code} {constraint}".strip() or "constraint"
    if tool == "airport_metrics":
        code = result.get("iata") or result.get("airport") or ""
        return f"{code} enplanements {_fmt_compact(result.get('enplanements'))}".strip()
    return "ok"


def _map_points(
    catalog: MetricsCatalog,
    tables: dict[str, Any],
    traces: Sequence[ScoringTrace],
    subgoals: Sequence[Subgoal],
) -> list[MapPoint]:
    if all(sg.intent in _SKIP_ENGINE_INTENTS for sg in subgoals):
        return []

    wanted: dict[str, dict[str, Any]] = {}

    def _mark(code: Any, **fields: Any) -> None:
        iata = str(code or "").strip().upper()
        if not iata:
            return
        slot = wanted.setdefault(iata, {})
        for key, value in fields.items():
            if value is None:
                continue
            if key == "highlight":
                slot[key] = bool(slot.get(key) or value)
            elif key not in slot:
                slot[key] = value

    ranking = tables.get("ranking") or []
    for i, row in enumerate(ranking):
        if not isinstance(row, dict):
            continue
        _mark(
            row.get("airport"),
            role="peer",
            teoi=row.get("teoi") or row.get("score"),
            constraint=row.get("constraint_type"),
            highlight=i == 0,
        )

    congestion = tables.get("congestion") or {}
    for code in congestion.get("airports") or []:
        mets = (congestion.get("metrics") or {}).get(code) or {}
        _mark(
            code,
            role="compare",
            constraint=mets.get("constraint_type") if isinstance(mets, dict) else None,
            delay_pct=mets.get("delay_pct") if isinstance(mets, dict) else None,
            highlight=True,
        )

    unmet = tables.get("unmet") or {}
    focus = unmet.get("airport")
    if focus:
        _mark(
            focus,
            role="focus",
            highlight=True,
            load_factor=unmet.get("load_factor"),
        )
        for peer in unmet.get("leakage_peers") or []:
            _mark(peer, role="leakage peer")

    longhaul = tables.get("longhaul") or {}
    if longhaul.get("airport"):
        _mark(longhaul.get("airport"), role="focus", highlight=True)

    for sg in subgoals:
        if sg.intent in _SKIP_ENGINE_INTENTS:
            continue
        for code in sg.entities:
            _mark(code, role=wanted.get(str(code).upper(), {}).get("role") or "airport")

    by_teoi = {t.airport: t for t in traces}
    points: list[MapPoint] = []
    for iata, extra in wanted.items():
        try:
            row = catalog.base_metrics(iata)
        except Exception:
            continue
        lat = row.get("latitude")
        lon = row.get("longitude")
        if lat is None or lon is None:
            continue
        trace = by_teoi.get(iata)
        constraint = extra.get("constraint") or row.get("constraint_type")
        points.append(
            MapPoint(
                iata=iata,
                name=str(row.get("name") or iata),
                lat=float(lat),
                lon=float(lon),
                role=str(extra.get("role") or "airport"),
                enplanements=row.get("enplanements"),
                constraint=str(constraint) if constraint else None,
                teoi=extra.get("teoi") if extra.get("teoi") is not None else (trace.teoi if trace else None),
                highlight=bool(extra.get("highlight")),
                load_factor=extra.get("load_factor") if extra.get("load_factor") is not None else row.get("load_factor"),
                delay_pct=extra.get("delay_pct") if extra.get("delay_pct") is not None else row.get("delay_pct"),
                why=constraint_explanation_for(constraint),
            )
        )
    return points


def _step(steps: list[Step], name: str, detail: str) -> None:
    steps.append(Step(index=len(steps) + 1, name=name, detail=detail))


def _brief_args(arguments: dict[str, Any]) -> str:
    parts = []
    for key, value in arguments.items():
        parts.append(f"{key}={value}")
    return ", ".join(parts)


def _ranks_from_query(query: str) -> list[int] | None:
    import re

    found = [int(x) for x in re.findall(r"rank\s+(\d+)", query, flags=re.IGNORECASE)]
    return found or None


def _ingest_result(
    result: dict[str, Any],
    traces: list[ScoringTrace],
    tables: dict[str, Any],
    envelopes: list[Envelope],
    citations: list[Citation],
    tool_name: str,
) -> None:
    if not isinstance(result, dict) or result.get("error"):
        return
    raw_traces = result.get("teoi_traces") or []
    for item in raw_traces:
        try:
            traces.append(ScoringTrace.model_validate(item))
        except Exception:
            continue
    if result.get("ranking") is not None:
        tables["ranking"] = result["ranking"]
        tables["ranking_peer_set"] = result.get("peer_set")
    if result.get("winner_on_each_axis") is not None:
        tables["congestion"] = {
            "airports": result.get("airports"),
            "metrics": result.get("metrics"),
            "winner_on_each_axis": result["winner_on_each_axis"],
        }
    if tool_name == "longhaul_share":
        tables["longhaul"] = {
            k: result.get(k)
            for k in (
                "airport",
                "pct_longhaul",
                "pct_longhaul_flights",
                "pct_international",
                "threshold_km",
                "passengers_total",
                "passengers_longhaul",
                "segments_counted",
                "segments_longhaul",
                "cargo_excluded",
                "anc_jfk_km",
                "anc_jfk_mi",
            )
        }
    if tool_name == "unmet_demand":
        tables["unmet"] = {
            k: result.get(k)
            for k in (
                "airport",
                "unmet",
                "lf_gap",
                "taf_gap",
                "leakage",
                "leakage_peers",
                "leakage_gated",
                "served",
                "load_factor",
                "lf_threshold",
            )
        }
    env = result.get("envelope")
    if env:
        try:
            envelopes.append(Envelope.model_validate(env))
        except Exception:
            pass
    sources = []
    if isinstance(env, dict):
        sources = list(env.get("sources") or [])
    elif env is not None:
        sources = list(getattr(env, "sources", []) or [])
    for src in sources:
        label = str(src)
        if not any(c.label == label for c in citations):
            citations.append(Citation(label=label, source=label))
    chunks = result.get("chunks") or []
    for chunk in chunks:
        meta = chunk.get("metadata") or {}
        sources_list = chunk.get("sources") or []
        for src in sources_list:
            label = src.get("title") or src.get("chunk_id") or "note"
            citations.append(
                Citation(
                    label=str(label),
                    url=src.get("url"),
                    source=src.get("doc_type"),
                )
            )


def _align_sections(
    parsed: list[Section],
    template: list[Section],
    subgoals: Sequence[Subgoal],
) -> list[Section]:
    out = list(template)
    for i, section in enumerate(parsed):
        if i >= len(out):
            break
        if i < len(subgoals) and subgoals[i].intent in _META_INTENTS:
            continue
        out[i] = Section(
            heading=section.heading or out[i].heading,
            body=section.body,
            subgoal_index=i,
        )
    return out


def _merge_envelopes(
    envelopes: list[Envelope],
    as_of: Any,
    unsupported: Sequence[UnsupportedPart] | None = None,
) -> Envelope:
    if not envelopes:
        extra_oos = []
        for part in unsupported or []:
            label = f"{part.text}: {part.reason}".strip(": ")
            if label:
                extra_oos.append(label)
        return make_envelope(
            assumptions=["US commercial primary airports; TEOI is a capacity-unlock proxy, not NPV"],
            sources=["DuckDB warehouse"],
            as_of=as_of,
            out_of_scope=extra_oos or ["PFC / NPV / airline equity"],
        )
    assumptions: list[str] = []
    uncertainties: list[str] = []
    out_of_scope: list[str] = []
    sources: list[str] = []
    order = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}
    confidence = Confidence.HIGH
    as_of_date = as_of
    for env in envelopes:
        for item in env.assumptions:
            if item not in assumptions:
                assumptions.append(item)
        for item in env.uncertainties:
            if item not in uncertainties:
                uncertainties.append(item)
        for item in env.out_of_scope:
            if item not in out_of_scope:
                out_of_scope.append(item)
        for item in env.sources:
            if item not in sources:
                sources.append(item)
        if order[env.confidence] < order[confidence]:
            confidence = env.confidence
        if env.as_of is not None:
            as_of_date = env.as_of
    for part in unsupported or []:
        label = f"{part.text}: {part.reason}".strip(": ")
        if label and label not in out_of_scope:
            out_of_scope.append(label)
    return Envelope(
        assumptions=assumptions,
        uncertainties=uncertainties,
        out_of_scope=out_of_scope,
        confidence=confidence,
        sources=sources,
        as_of=as_of_date,
    )


def _entities_from(subgoals: Sequence[Subgoal], filled: list[str]) -> list[str]:
    if all(sg.intent in _SKIP_ENGINE_INTENTS for sg in subgoals):
        return []
    seen: list[str] = []
    for sg in subgoals:
        if sg.intent in _SKIP_ENGINE_INTENTS:
            continue
        for code in sg.entities:
            if code not in seen:
                seen.append(code)
    for code in filled:
        if code not in seen:
            seen.append(code)
    return seen


__all__ = ["ask", "new_session_id"]
