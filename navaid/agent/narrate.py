"""Section narration from tool payloads. Template is the no-key path; Gemini optional."""

from __future__ import annotations

import json
import re
from typing import Any

from navaid.agent.jsonutil import jsonable
from navaid.agent.number_lock import lock_prose
from navaid.schemas import Intent, Section, Subgoal, SubgoalStatus, UnsupportedPart, constraint_explanation_for, constraint_key

_CONSTRAINT_ORDER = ("landside", "mixed", "airside", "demand-bound")
_HEADING_HASH = re.compile(r"^#+\s*")

_HUMAN_HEADINGS = {
    Intent.EXPANSION_RANK: "Terminal expansion ranking",
    Intent.CONGESTION_COMPARE: "Congestion comparison",
    Intent.LONGHAUL_SHARE: "Long-haul share",
    Intent.UNMET_DEMAND: "Unmet demand",
    Intent.EXPLAIN_TEOI: "Why these scores",
    Intent.EXPLAIN_CONSTRAINT: "Why this constraint type",
    Intent.AIRPORT_BRIEF: "Airport snapshot",
    Intent.CHITCHAT: "Hello",
    Intent.CAPABILITIES: "Navaid",
    Intent.UNSUPPORTED: "Out of scope",
}


def _clean_heading(text: str) -> str:
    cleaned = _HEADING_HASH.sub("", (text or "").strip())
    cleaned = cleaned.replace("EXPANSION_RANK:", "").replace("CONGESTION_COMPARE:", "")
    cleaned = cleaned.replace("LONGHAUL_SHARE:", "").replace("UNMET_DEMAND:", "")
    cleaned = cleaned.replace("EXPLAIN_TEOI:", "").replace("EXPLAIN_CONSTRAINT:", "")
    cleaned = cleaned.replace("AIRPORT_BRIEF:", "")
    cleaned = cleaned.replace("UNSUPPORTED:", "").replace("CHITCHAT:", "").replace("CAPABILITIES:", "")
    return cleaned.strip() or "Answer"


def _fmt_num(value: Any, *, digits: int = 1, percent: bool = False) -> str:
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


def _append_constraint_whys(lines: list[str], types: list[Any]) -> None:
    present = {constraint_key(item) for item in types if item}
    notes = [
        constraint_explanation_for(key)
        for key in _CONSTRAINT_ORDER
        if key in present and constraint_explanation_for(key)
    ]
    if not notes:
        return
    lines.append("")
    lines.extend(notes)


def template_section(subgoal: Subgoal, payload: dict[str, Any] | None, index: int) -> Section:
    heading = _heading(subgoal)
    if subgoal.intent == Intent.UNSUPPORTED:
        body = (
            f"Out of scope: {subgoal.query or 'this part'}. "
            f"{subgoal.notes or 'Navaid does not advise on securities or non-airport questions.'}"
        )
        return Section(heading=heading, body=body, subgoal_index=index)
    if subgoal.intent == Intent.CHITCHAT:
        return Section(heading=heading, body=_chitchat_body(), subgoal_index=index)
    if subgoal.intent == Intent.CAPABILITIES:
        return Section(heading=heading, body=_capabilities_body(), subgoal_index=index)

    if not payload or payload.get("error"):
        err = (payload or {}).get("error") or "no tool payload"
        return Section(
            heading=heading,
            body=f"Could not answer this part ({err}).",
            subgoal_index=index,
        )

    result = payload.get("result", payload)
    if subgoal.intent == Intent.EXPANSION_RANK:
        body = _expansion_body(result)
    elif subgoal.intent == Intent.EXPLAIN_TEOI:
        body = _explain_body(result)
    elif subgoal.intent == Intent.EXPLAIN_CONSTRAINT:
        body = _constraint_body(result)
    elif subgoal.intent == Intent.CONGESTION_COMPARE:
        body = _congestion_body(result, subgoal)
    elif subgoal.intent == Intent.LONGHAUL_SHARE:
        body = _longhaul_body(result)
    elif subgoal.intent == Intent.UNMET_DEMAND:
        body = _unmet_body(result)
    elif "glossary faq" in (subgoal.notes or "").lower():
        body = _glossary_body(result)
    else:
        body = _brief_body(result)

    return Section(heading=heading, body=body, subgoal_index=index)


def _chitchat_body() -> str:
    return (
        "Hello — I'm **Navaid**. I help you decide where a terminal project can unlock capacity.\n"
        "\n"
        "- Rank expansion candidates among peers\n"
        "- Compare congestion axis by axis\n"
        "- Measure long-haul share\n"
        "- Estimate unmet passenger demand\n"
        "\n"
        "Ask a New England ranking, congestion at Los Angeles and Santa Ana, "
        "long-haul out of Anchorage, or unmet demand at SFO — or ask **what I can do**.\n"
        "\n"
        "Stocks, tickers, and NPV are outside this analysis."
    )


def _capabilities_body() -> str:
    return (
        "Hi — I'm **Navaid**. I help you decide where a terminal project can unlock capacity.\n"
        "\n"
        "- **Rank** terminal-expansion candidates among the peers you name — New England is the designed set\n"
        "- **Compare congestion** axis by axis — delay versus curfew, so there is no single congestion score\n"
        "- **Measure long-haul share** from published US segment traffic\n"
        "- **Estimate unmet passenger demand** from load factor, the forecast, and same-metro leakage, "
        "without inventing leakage the figures do not show\n"
        "\n"
        "Ask which New England airports are strong terminal-expansion candidates, "
        "how congestion differs at Los Angeles and Santa Ana, the long-haul share out of Anchorage, "
        "or unmet demand at SFO.\n"
        "\n"
        "Stocks, tickers, NPV, and general web search are outside this analysis."
    )


def _expansion_body(result: dict[str, Any]) -> str:
    ranking = result.get("ranking") or []
    peer = result.get("peer_set") or result.get("ranking_peer_set") or []
    if not peer and ranking:
        peer = [row.get("airport") for row in ranking if row.get("airport")]
    lines = [
        "This ranking is **peer-relative**: scores exist only inside the airports you asked about, "
        "not against every US hub. Busy is not automatically investable. "
        "Landside-constrained airports rank higher here because a terminal project can unlock "
        "capacity; airside and demand-bound peers are scaled down.",
        "",
        f"**Comparison set:** {', '.join(str(c) for c in peer) or '—'}.",
        "",
    ]
    teois = []
    for row in ranking:
        try:
            teois.append(float(row.get("teoi") or row.get("score") or 0))
        except (TypeError, ValueError):
            continue
    cutoff = 15.0
    if len(teois) >= 3:
        drops = [teois[i] - teois[i + 1] for i in range(len(teois) - 1)]
        if drops:
            cliff = max(range(len(drops)), key=lambda i: drops[i])
            if drops[cliff] >= 8:
                cutoff = max(15.0, (teois[cliff] + teois[cliff + 1]) / 2)
    strong = [
        row
        for row in ranking
        if float(row.get("teoi") or row.get("score") or 0) >= cutoff
    ]
    if strong:
        lines.append("### Stronger terminal-expansion candidates")
        for row in strong:
            lines.append(_rank_line(row))
        rest = [row for row in ranking if row not in strong]
        if rest:
            lines.append("")
            lines.append("### Lower in this set")
            for row in rest:
                lines.append(_rank_line(row))
    else:
        lines.append("### Ranking")
        for row in ranking:
            lines.append(_rank_line(row))
    _append_constraint_whys(
        lines,
        [row.get("constraint_type") for row in ranking if isinstance(row, dict)],
    )
    return "\n".join(str(x) for x in lines)


def _rank_line(row: dict[str, Any]) -> str:
    constraint = str(row.get("constraint_type") or "—")
    return (
        f"{row.get('rank')}. **{row.get('airport')}** — TEOI "
        f"**{_fmt_num(row.get('teoi') or row.get('score'), digits=1)}** "
        f"({constraint})"
    )


def _explain_body(result: dict[str, Any]) -> str:
    traces = result.get("teoi_traces") or []
    reused = result.get("reused_traces")
    peer = result.get("peer_set") or []
    lines = [
        "TEOI is **peer-relative**. Each feature is scaled 0–1 inside this comparison set, "
        "weighted, then multiplied by the constraint factor.",
        "",
        f"**Comparison set:** {', '.join(str(c) for c in peer) or '—'}.",
        (
            "This is not a new ranking. The numbers below reuse the last traces for that set."
            if reused
            else "Traces computed for this request."
        ),
        "",
    ]
    if len(traces) >= 2:
        a, b = traces[0], traces[1]
        lines.append(
            f"**{a.get('airport')}** (rank {a.get('rank')}, TEOI {_fmt_num(a.get('teoi'), digits=1)}) "
            f"sits above **{b.get('airport')}** (rank {b.get('rank')}, TEOI {_fmt_num(b.get('teoi'), digits=1)}) "
            "because its weighted contributions are larger after the same recipe."
        )
        lines.append("")
        contrib_a = a.get("contributions") or {}
        contrib_b = b.get("contributions") or {}
        keys = [k for k in contrib_a.keys() if k in contrib_b]
        deltas = sorted(
            keys,
            key=lambda k: abs(float(contrib_a.get(k) or 0) - float(contrib_b.get(k) or 0)),
            reverse=True,
        )
        if deltas:
            lines.append("Largest contribution gaps:")
            for key in deltas[:4]:
                lines.append(
                    f"- **{key.replace('_', ' ')}**: "
                    f"{a.get('airport')} {_fmt_num(contrib_a.get(key), digits=1)} vs "
                    f"{b.get('airport')} {_fmt_num(contrib_b.get(key), digits=1)}"
                )
            lines.append("")
    for trace in traces:
        lines.append(
            f"- **{trace.get('airport')}**: TEOI **{_fmt_num(trace.get('teoi'), digits=1)}**, "
            f"rank {trace.get('rank')}, constraint `{trace.get('constraint_type')}` "
            f"× {_fmt_num(trace.get('constraint_multiplier'), digits=2)}"
        )
    _append_constraint_whys(
        lines,
        [trace.get("constraint_type") for trace in traces if isinstance(trace, dict)],
    )
    return "\n".join(str(x) for x in lines)


def _constraint_body(result: dict[str, Any]) -> str:
    code = str(result.get("airport") or result.get("iata") or "This airport")
    constraint = constraint_key(result.get("constraint_type")) or str(result.get("constraint_type") or "unknown")
    notes = " ".join(str(result.get("constraint_notes") or "").split())
    why = result.get("constraint_explanation") or constraint_explanation_for(constraint)
    multiplier = result.get("constraint_multiplier")
    lines: list[str] = []
    if constraint == "mixed":
        lines.append(
            f"**{code}** is labeled **mixed** because landside and airside both bind. "
            "That is the constraint classifier rule — a curated warehouse label, not a TEOI rank."
        )
    elif constraint == "landside":
        lines.append(
            f"**{code}** is labeled **landside** because the building (gates, holdrooms, curb) "
            "binds before the airfield. Terminal capex can unlock capacity here."
        )
    elif constraint == "airside":
        lines.append(
            f"**{code}** is labeled **airside** because runways, slots, weather, ATC, or a curfew "
            "bind before the terminal. More concourse does not create slots."
        )
    elif constraint == "demand-bound":
        lines.append(
            f"**{code}** is labeled **demand-bound** because catchment, load factor, or nearby "
            "leakage bind before gates. Expansion is speculative without demand."
        )
    else:
        lines.append(f"**{code}** is labeled **{constraint}** in the warehouse constraints table.")
    if notes:
        lines.append("")
        lines.append(notes)
    figures: list[str] = []
    if result.get("gate_count") is not None:
        figures.append(f"gates {_fmt_num(result.get('gate_count'))}")
    if result.get("pax_per_gate") is not None:
        figures.append(f"pax per gate {_fmt_num(result.get('pax_per_gate'))}")
    if result.get("delay_pct") is not None:
        figures.append(f"delay share {_fmt_num(result.get('delay_pct'), percent=True)}")
    if result.get("avg_arrival_delay_min") is not None:
        figures.append(
            f"arrival delay {_fmt_num(result.get('avg_arrival_delay_min'), digits=0)} min"
        )
    if result.get("load_factor") is not None:
        figures.append(f"load factor {_fmt_num(result.get('load_factor'), percent=True)}")
    if result.get("ops_per_runway") is not None:
        figures.append(f"ops/runway {_fmt_num(result.get('ops_per_runway'))}")
    if result.get("curfew"):
        figures.append(f"curfew {result.get('curfew')}")
    if figures:
        lines.append("")
        lines.append("Warehouse figures that support the label: " + "; ".join(figures[:6]) + ".")
    lines.append("")
    haircut = _fmt_num(multiplier, digits=2) if multiplier is not None else None
    if haircut and haircut != "—":
        lines.append(
            f"The **{haircut}** multiplier is the {constraint} haircut applied later to TEOI, "
            "not the reason it was labeled this way. I can open the TEOI traces if you want the score math."
        )
    elif why:
        lines.append(why)
        lines.append("I can open the TEOI traces if you want the score math.")
    else:
        lines.append("I can open the TEOI traces if you want the score math.")
    return "\n".join(lines)


def _congestion_body(result: dict[str, Any], subgoal: Subgoal) -> str:
    winners = result.get("winner_on_each_axis") or {}
    airports = result.get("airports") or subgoal.entities
    metrics = result.get("metrics") or {}
    codes = [str(c) for c in list(airports)[:2]]
    lines = [
        f"Congestion for {' vs '.join(str(c) for c in airports)} is compared **axis by axis**. "
        "There is no single congestion score — delay volume and a curfew are different investment problems.",
        "",
    ]
    if len(codes) >= 2:
        a, b = codes[0], codes[1]
        ma, mb = metrics.get(a) or {}, metrics.get(b) or {}
        if not isinstance(ma, dict):
            ma = {}
        if not isinstance(mb, dict):
            mb = {}
        curfew_a, curfew_b = ma.get("curfew"), mb.get("curfew")
        type_a = constraint_key(ma.get("constraint_type"))
        type_b = constraint_key(mb.get("constraint_type"))
        delay_a, delay_b = ma.get("delay_pct"), mb.get("delay_pct")
        ops_a, ops_b = ma.get("ops_per_runway"), mb.get("ops_per_runway")
        delay_winner = winners.get("delay_pct")
        ops_winner = winners.get("ops_per_runway")
        volume = None
        if delay_winner and str(delay_winner) not in {"tie", ""}:
            volume = str(delay_winner)
        elif ops_winner and str(ops_winner) not in {"tie", ""}:
            volume = str(ops_winner)
        curfew_code = None
        if curfew_b and not curfew_a:
            curfew_code = b
        elif curfew_a and not curfew_b:
            curfew_code = a
        airside_code = b if type_b == "airside" else (a if type_a == "airside" else None)
        policy = curfew_code or airside_code
        if volume and policy and volume != policy:
            vol_row = ma if volume == a else mb
            pol_row = ma if policy == a else mb
            curfew_txt = pol_row.get("curfew")
            curfew_bit = f" ({curfew_txt})" if curfew_txt else ""
            lines.append(
                f"**{volume}** is the delay-volume / operations story "
                f"(delay share {_fmt_num(vol_row.get('delay_pct'), percent=True)}"
                f"{', ops/runway ' + _fmt_num(vol_row.get('ops_per_runway')) if vol_row.get('ops_per_runway') is not None else ''}). "
                f"**{policy}** is airside-bound{curfew_bit}, so more terminal does not create night slots. "
                "Calling one airport “more congested” collapses two different problems."
            )
            lines.append("")
        elif curfew_b and not curfew_a:
            lines.append(
                f"**{a}** is the delay-volume story; **{b}** is the curfew/slots constraint. "
                "Those are different investment problems."
            )
            lines.append("")
        elif curfew_a and not curfew_b:
            lines.append(
                f"**{a}** carries the curfew/slots constraint; **{b}** is the delay-volume story. "
                "Those are different investment problems."
            )
            lines.append("")
        for code, mets, delay, ops in ((a, ma, delay_a, ops_a), (b, mb, delay_b, ops_b)):
            constraint = mets.get("constraint_type") or "—"
            curfew = mets.get("curfew")
            bits = [
                f"delay share {_fmt_num(delay, percent=True)}",
                f"arrival delay {_fmt_num(mets.get('avg_arrival_delay_min'), digits=0)} min",
                f"ops/runway {_fmt_num(ops)}",
                f"constraint {constraint}",
            ]
            if curfew:
                bits.append(f"curfew {curfew}")
            lines.append(f"- **{code}**: " + "; ".join(bits) + ".")
    else:
        for code, mets in metrics.items():
            if not isinstance(mets, dict):
                continue
            lines.append(
                f"- **{code}**: delay share {_fmt_num(mets.get('delay_pct'), percent=True)}, "
                f"arrival delay {_fmt_num(mets.get('avg_arrival_delay_min'), digits=0)} min, "
                f"ops/runway {_fmt_num(mets.get('ops_per_runway'))}, "
                f"constraint {mets.get('constraint_type') or '—'}"
            )
            if mets.get("curfew"):
                lines.append(f"  - Curfew / policy: {mets.get('curfew')}")
    _append_constraint_whys(
        lines,
        [
            mets.get("constraint_type")
            for mets in metrics.values()
            if isinstance(mets, dict)
        ],
    )
    return "\n".join(str(x) for x in lines)


def _longhaul_body(result: dict[str, Any]) -> str:
    airport = result.get("airport")
    cargo = result.get("cargo_excluded")
    cargo_txt = "Cargo segments are excluded." if cargo else "This run includes cargo segments."
    flight_pct = result.get("pct_longhaul_flights")
    pax_pct = result.get("pct_longhaul")
    intl = result.get("pct_international")
    lines = [
        f"**{airport}** long-haul share uses T-100 **segments** (one takeoff to landing), "
        f"not true origin-and-destination itineraries. Threshold is "
        f"{_fmt_num(result.get('threshold_km') or 4000, digits=0)} km (Eurocontrol).",
        "",
    ]
    if flight_pct is not None:
        lines.append(
            f"- **Flight-segment share** above the threshold: **{_fmt_num(flight_pct, digits=2)}%** "
            f"({result.get('segments_longhaul')} of {result.get('segments_counted')} counted segments)."
        )
    lines.append(
        f"- **Passenger share** above the threshold: **{_fmt_num(pax_pct, digits=2)}%** "
        f"({_fmt_num(result.get('passengers_longhaul'))} of "
        f"{_fmt_num(result.get('passengers_total'))} passengers in the warehouse sample)."
    )
    lines.append(f"- **International passenger share:** {_fmt_num(intl, digits=2)}%.")
    lines.append(f"- {cargo_txt}")
    if result.get("anc_jfk_km") or result.get("airport") == "ANC":
        lines.append("- Pin: ANC→JFK is about 5420 km / 3370 miles.")
    lines.append("")
    lines.append(
        "Warehouse T-100 is a filtered commercial sample, not every cargo and connecting itinerary "
        "through the airport. Totals will not match full-year FAA enplanements."
    )
    return "\n".join(lines)


def _unmet_body(result: dict[str, Any]) -> str:
    airport = result.get("airport")
    lf = result.get("load_factor")
    threshold = result.get("lf_threshold") or 0.85
    peers = result.get("leakage_peers") or []
    constraint = result.get("constraint_type")
    lines = [
        f"**{airport}** unmet demand is a **passenger** gap, not a count of missing flights: "
        f"**{_fmt_num(result.get('unmet'))}**.",
        "",
    ]
    lf_below = lf is not None and float(lf) < float(threshold)
    if lf_below:
        lines.append(
            f"Load factor is {_fmt_num(lf, percent=True)}, below the "
            f"{_fmt_num(threshold, percent=True)} seat-pressure rule, so same-metro leakage is "
            "**qualitative only** — not in this number. A TAF forecast gap is not a missing concourse."
        )
        lines.append("")
    lines.extend(
        [
            f"- Served (warehouse): {_fmt_num(result.get('served'))}",
            f"- Load-factor gap: {_fmt_num(result.get('lf_gap'))} "
            f"(load factor {_fmt_num(lf, percent=True)}, rule threshold {_fmt_num(threshold, percent=True)})",
            f"- TAF 10-year forecast gap: {_fmt_num(result.get('taf_gap'))}",
            f"- Same-metro leakage: {_fmt_num(result.get('leakage'))}"
            + (f" toward {', '.join(str(p) for p in peers)}" if peers else ""),
        ]
    )
    if lf_below:
        lines.append(
            f"- Leakage is **not counted** here because load factor is below the "
            f"{_fmt_num(threshold, percent=True)} seat-pressure rule. Nearby airports can still "
            "take metro demand, but that is qualitative, not in this number."
        )
    if constraint:
        lines.append(f"- Constraint type: **{constraint}**.")
        why = constraint_explanation_for(constraint)
        if why:
            lines.append(f"- {why}")
    lines.append("")
    lines.append("Unmet is max(0, implied − served). A forecast gap is not a missing concourse.")
    return "\n".join(lines)


def _glossary_body(result: dict[str, Any]) -> str:
    chunks = result.get("chunks") or []
    lines = [
        "Local glossary and airport notes only — no web search. If notes and T-100 disagree, T-100 wins.",
        "",
    ]
    if not chunks:
        lines.append(
            "No matching note in the warehouse. Open the Glossary or Methodology pages on this site."
        )
        return "\n".join(lines)
    for chunk in chunks[:4]:
        if not isinstance(chunk, dict):
            continue
        sources = chunk.get("sources") or []
        title = ""
        if sources and isinstance(sources[0], dict):
            title = str(sources[0].get("title") or "")
        title = title or str((chunk.get("metadata") or {}).get("doc_type") or "note")
        snippet = " ".join(str(chunk.get("text") or "").split())[:420]
        if snippet:
            lines.append(f"- **{title}:** {snippet}")
    return "\n".join(lines)


def _brief_body(result: dict[str, Any]) -> str:
    if not isinstance(result, dict):
        return str(result)
    skip = {"envelope", "error", "tool"}
    lines = ["Warehouse snapshot:"]
    for key, value in result.items():
        if key in skip or isinstance(value, (dict, list)):
            continue
        label = str(key).replace("_", " ")
        if "pct" in key or key in {"yoy", "load_factor", "lf"}:
            lines.append(f"- **{label}:** {_fmt_num(value, percent=True)}")
        else:
            lines.append(f"- **{label}:** {_fmt_num(value) if _looks_numeric(value) else value}")
    return "\n".join(lines)


def _looks_numeric(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def lock_sections(
    sections: list[Section],
    payloads: list[Any],
) -> tuple[list[Section], list[str]]:
    stripped_all: list[str] = []
    locked: list[Section] = []
    for section in sections:
        body, stripped = lock_prose(section.body, payloads)
        stripped_all.extend(stripped)
        locked.append(
            Section(
                heading=_clean_heading(section.heading),
                body=body or section.body,
                subgoal_index=section.subgoal_index,
            )
        )
    return locked, stripped_all


def unsupported_from(subgoal: Subgoal, index: int) -> UnsupportedPart:
    return UnsupportedPart(
        text=subgoal.query or subgoal.notes or "unsupported",
        reason=subgoal.notes or "out of scope",
        subgoal_index=index,
    )


def mark_status(subgoal: Subgoal, ok: bool) -> Subgoal:
    if subgoal.intent == Intent.UNSUPPORTED:
        status = SubgoalStatus.UNSUPPORTED
    elif subgoal.intent in {Intent.CHITCHAT, Intent.CAPABILITIES}:
        status = SubgoalStatus.ANSWERED
    elif ok:
        status = SubgoalStatus.ANSWERED
    else:
        status = SubgoalStatus.FAILED
    return Subgoal(
        intent=subgoal.intent,
        entities=list(subgoal.entities),
        status=status,
        query=subgoal.query,
        notes=subgoal.notes,
    )


def _heading(subgoal: Subgoal) -> str:
    base = _HUMAN_HEADINGS.get(subgoal.intent, "Answer")
    if subgoal.intent in {Intent.UNSUPPORTED, Intent.CHITCHAT, Intent.CAPABILITIES}:
        return base
    if subgoal.entities:
        joiner = " vs " if subgoal.intent == Intent.CONGESTION_COMPARE else ", "
        return f"{base}: {joiner.join(subgoal.entities)}"
    return base


def gemini_prompt(
    reconstructed_query: str,
    subgoals: list[Subgoal],
    payloads: list[dict[str, Any]],
) -> str:
    blob = json.dumps(jsonable(payloads, round_floats=True), default=str)
    if len(blob) > 80_000:
        blob = blob[:80_000] + "…(truncated)"
    lines = [
        f"Analyst question: {reconstructed_query}",
        "Write one section per subgoal. Headings must be plain English — never intent enums such as EXPANSION_RANK.",
        "Subgoals:",
    ]
    for i, sg in enumerate(subgoals):
        lines.append(f"{i}. {_HUMAN_HEADINGS.get(sg.intent, sg.intent.value)} airports={sg.entities}")
    lines.append("Tool JSON (the only numbers you may quote; already rounded):")
    lines.append(blob)
    lines.append(
        "Write sections as:\n===SECTION 0===\nheading on this line\nbody\n===SECTION 1===\n..."
        "\nKeep Markdown lists. Do not put ## in the heading line."
        "\nUse percent signs for rates (24.0% not 0.24). Round TEOI to one decimal."
        "\nWrite explanation-first: 3–6 key figures, not a warehouse field dump."
        "\nDo not dump snake_case field names. Explain the investment implication."
        "\nFor rankings, distinguish stronger candidates from the long tail and say why landside wins."
        "\nFor congestion, tell a two-airport story (delay volume vs curfew/slots); mention curfew when airside. Never print snake_case axis names. No single congestion score."
        "\nIf they ask why a constraint label, explain the classifier rule and 2–4 triggering metrics. The multiplier is a later TEOI haircut, not the reason for the label. Do not dump TEOI traces or snake_case field lists. Offer traces only if they ask for the math."
        "\nFor unmet demand, say which component is the gap. If load factor is under 85%, leakage is qualitative only. A forecast gap is not a concourse."
        "\nFor long-haul, lead with flight-segment share, then passenger share, and that T-100 is a sample. ANC→JFK is about 5420 km."
        "\nFor capabilities or greetings, a short welcome plus a compact markdown bullet list — "
        "not an essay, not a spec dump. Introduce Navaid as helping decide where a terminal "
        "project can unlock capacity. Four bullets: rank expansion candidates among named peers "
        "(New England is the designed set); compare congestion axis by axis with no single "
        "congestion score (delay versus curfew); long-haul share from published US segment traffic; "
        "unmet passenger demand from load factor, forecast, and same-metro leakage, without inventing "
        "leakage the figures do not show. Then invite New England ranking, Los Angeles vs Santa Ana "
        "congestion, Anchorage long-haul, and SFO unmet demand. One quiet line that stocks, "
        "tickers, NPV, and web search are out of scope. No metrics, no TEOI, no engines, "
        "no Gemini, no 'I refuse', no 'trading desk'. Greetings are the same voice, slightly shorter, "
        "with a shorter list and an invite to ask what I can do."
        "\nRefuse only unsupported parts; do not attach an airport brief to a stock question."
    )
    return "\n".join(lines)


def parse_gemini_sections(text: str, subgoals: list[Subgoal]) -> list[Section] | None:
    if "===SECTION" not in text:
        return None
    parts = text.split("===SECTION")
    sections: list[Section] = []
    for part in parts[1:]:
        rest = part.split("===", 1)
        chunk = rest[1] if len(rest) > 1 else rest[0]
        raw_lines = [ln.rstrip() for ln in chunk.strip().splitlines()]
        while raw_lines and not raw_lines[0].strip():
            raw_lines.pop(0)
        if not raw_lines:
            continue
        heading = _clean_heading(raw_lines[0])
        body = "\n".join(raw_lines[1:]).strip() if len(raw_lines) > 1 else heading
        idx = len(sections)
        sections.append(Section(heading=heading, body=body, subgoal_index=idx))
    if len(sections) < len(
        [s for s in subgoals if s.intent not in {Intent.UNSUPPORTED, Intent.CHITCHAT, Intent.CAPABILITIES}]
    ) and len(sections) < 1:
        return None
    return sections or None
