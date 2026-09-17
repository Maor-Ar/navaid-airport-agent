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
from navaid.config import NAVAID_MODEL, NAVAID_OFFLINE
from navaid.schemas import (
    Answer,
    Citation,
    Confidence,
    Envelope,
    Intent,
    ScoringTrace,
    Section,
    Step,
    Subgoal,
    UnsupportedPart,
)
from navaid.scoring.envelope import make_envelope
from navaid.warehouse.db import connect, init_schema
from navaid.warehouse.metrics import MetricsCatalog, require_snapshot


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

        for index, subgoal in enumerate(subgoals):
            if subgoal.intent == Intent.UNSUPPORTED:
                payload_by_subgoal[index] = {"unsupported": True}
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
            last_payload: dict[str, Any] | None = None
            for name, arguments in planned:
                result = call_tool(ctx, name, arguments)
                last_payload = {"tool": name, "arguments": arguments, "result": result}
                payloads.append(last_payload)
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

        template_sections = [
            template_section(sg, payload_by_subgoal.get(i), i) for i, sg in enumerate(subgoals)
        ]
        sections = template_sections
        if use_model and gemini is not None:
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
                        if sg.intent != Intent.UNSUPPORTED:
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
            elif payload_by_subgoal.get(i, {}).get("result", {}).get("error"):
                ok = False
            finished.append(mark_status(sg, ok))

        envelope = _merge_envelopes(envelopes, catalog.as_of())
        entities = _entities_from(finished, reconstruction.filled_airports)
        peer_set = tables.get("ranking_peer_set") or reconstruction.filled_airports or entities

        memory.remember(
            question=q,
            reconstructed_query=reconstruction.reconstructed_query,
            entities=entities,
            peer_set=list(peer_set) if isinstance(peer_set, list) else entities,
            payloads={p["tool"]: p["result"] for p in payloads if "tool" in p},
            traces=traces,
            intent=next(
                (s.intent.value for s in finished if s.intent != Intent.UNSUPPORTED),
                None,
            ),
        )
        save_session(con, memory)

        return Answer(
            reconstructed_query=reconstruction.reconstructed_query,
            reconstruction_notes=reconstruction.notes,
            subgoals=finished,
            steps=steps,
            sections=sections,
            teoi_traces=traces,
            tables=tables,
            envelope=envelope,
            citations=citations,
            unsupported_parts=unsupported,
        )
    finally:
        con.close()


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
                "pct_international",
                "threshold_km",
                "passengers_total",
                "passengers_longhaul",
            )
        }
    if tool_name == "unmet_demand":
        tables["unmet"] = {
            k: result.get(k)
            for k in ("airport", "unmet", "lf_gap", "taf_gap", "leakage", "leakage_peers", "served")
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
    if len(parsed) == len(template):
        return [
            Section(heading=p.heading or t.heading, body=p.body, subgoal_index=i)
            for i, (p, t) in enumerate(zip(parsed, template))
        ]
    out = list(template)
    for i, section in enumerate(parsed):
        if i < len(out):
            out[i] = Section(
                heading=section.heading or out[i].heading,
                body=section.body,
                subgoal_index=i,
            )
    return out


def _merge_envelopes(envelopes: list[Envelope], as_of: Any) -> Envelope:
    if not envelopes:
        return make_envelope(
            assumptions=["US commercial primary airports; TEOI is a capacity-unlock proxy, not NPV"],
            sources=["DuckDB warehouse"],
            as_of=as_of,
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
    return Envelope(
        assumptions=assumptions,
        uncertainties=uncertainties,
        out_of_scope=out_of_scope,
        confidence=confidence,
        sources=sources,
        as_of=as_of_date,
    )


def _entities_from(subgoals: Sequence[Subgoal], filled: list[str]) -> list[str]:
    seen: list[str] = []
    for sg in subgoals:
        if sg.intent == Intent.UNSUPPORTED:
            continue
        for code in sg.entities:
            if code not in seen:
                seen.append(code)
    for code in filled:
        if code not in seen:
            seen.append(code)
    return seen


__all__ = ["ask", "new_session_id"]
