"""Turn a locked ``Answer`` into Gradio-ready markdown, HTML, and tables."""

from __future__ import annotations

import html
from typing import Any

from navaid.schemas import (
    Answer,
    Envelope,
    ScoringTrace,
    constraint_explanation_for,
    constraint_key,
)
from navaid.scoring.weights import FEATURE_ORDER

CONSTRAINT_COLORS = {
    "landside": ("#166534", "#dcfce7"),
    "mixed": ("#92400e", "#fef3c7"),
    "airside": ("#991b1b", "#fee2e2"),
    "demand-bound": ("#334155", "#e2e8f0"),
}

WATERFALL_STAGES = (
    "raw",
    "scaled 0–1",
    "weights",
    "contributions",
    "constraint multiplier",
    "TEOI score",
    "rank",
)

_CONSTRAINT_ORDER = ("landside", "mixed", "airside", "demand-bound")

_PCT_KEYS = {"delay_pct", "cancel_pct", "yoy", "lf", "load_factor"}


def _constraint_why_html(text: str) -> str:
    if not text:
        return ""
    return f'<p class="navaid-constraint-why">{_esc(text)}</p>'


def _unique_constraint_explanations(types: list[Any]) -> list[str]:
    present = {constraint_key(item) for item in types if item}
    return [
        constraint_explanation_for(key)
        for key in _CONSTRAINT_ORDER
        if key in present and constraint_explanation_for(key)
    ]


def _esc(value: Any) -> str:
    if value is None:
        return "—"
    return html.escape(str(value), quote=True)


def _fmt(value: Any, *, digits: int = 3, percent: bool = False) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int) and not isinstance(value, bool):
        return f"{value:,}"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if percent:
        return f"{100.0 * number:.1f}%"
    if abs(number) >= 1000:
        return f"{number:,.1f}"
    text = f"{number:.{digits}f}".rstrip("0").rstrip(".")
    return text or "0"


def _bullets(items: list[str] | None, empty: str = "—") -> str:
    if not items:
        return empty
    return "<ul>" + "".join(f"<li>{_esc(item)}</li>" for item in items) + "</ul>"


def _md_bullets(items: list[str] | None, empty: str = "_None listed._") -> str:
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def constraint_badge(constraint_type: str | None, *, multiplier: float | None = None) -> str:
    key = (constraint_type or "").strip().lower() or "unknown"
    fg, bg = CONSTRAINT_COLORS.get(key, ("#334155", "#e2e8f0"))
    extra = f" × {_fmt(multiplier, digits=2)}" if multiplier is not None else ""
    return (
        f'<span class="navaid-badge" style="background:{bg};color:{fg};'
        f'border:1px solid {fg}33;">{_esc(key)}{html.escape(extra)}</span>'
    )


def envelope_html(envelope: Envelope | None) -> str:
    """Compact cards always shown above the workbench tabs."""

    if envelope is None:
        return (
            '<div class="navaid-envelope">'
            '<div class="navaid-card"><h4>Envelope</h4>'
            "<p>Ask a question to see assumptions, uncertainties, scope, "
            "confidence, sources, and <code>as_of</code>.</p></div></div>"
        )
    as_of = envelope.as_of.isoformat() if envelope.as_of else "—"
    sources = ", ".join(envelope.sources) if envelope.sources else "—"
    return f"""
<div class="navaid-envelope">
  <div class="navaid-card navaid-card-meta">
    <h4>Confidence</h4>
    <p class="navaid-kpi">{_esc(envelope.confidence)}</p>
    <p><strong>as_of</strong> {_esc(as_of)}</p>
    <p><strong>sources</strong> {_esc(sources)}</p>
  </div>
  <div class="navaid-card">
    <h4>Assumptions</h4>
    {_bullets(envelope.assumptions)}
  </div>
  <div class="navaid-card">
    <h4>Uncertainties</h4>
    {_bullets(envelope.uncertainties)}
  </div>
  <div class="navaid-card">
    <h4>Out of scope</h4>
    {_bullets(envelope.out_of_scope)}
  </div>
</div>
"""


def envelope_markdown(envelope: Envelope | None) -> str:
    if envelope is None:
        return "No envelope yet."
    as_of = envelope.as_of.isoformat() if envelope.as_of else "—"
    return (
        f"**Confidence:** {envelope.confidence}  \n"
        f"**as_of:** {as_of}  \n"
        f"**Sources:** {', '.join(envelope.sources) or '—'}\n\n"
        f"**Assumptions**\n{_md_bullets(envelope.assumptions)}\n\n"
        f"**Uncertainties**\n{_md_bullets(envelope.uncertainties)}\n\n"
        f"**Out of scope**\n{_md_bullets(envelope.out_of_scope)}"
    )


def chat_reply(answer: Answer) -> str:
    parts: list[str] = []
    for section in answer.sections:
        heading = section.heading or "Answer"
        parts.append(f"### {heading}\n{section.body}")
    if answer.unsupported_parts:
        lines = ["### Out of scope"]
        for part in answer.unsupported_parts:
            lines.append(f"- {part.text}: {part.reason}")
        parts.append("\n".join(lines))
    env = answer.envelope
    as_of = env.as_of.isoformat() if env.as_of else "—"
    parts.append(f"_Envelope: confidence={env.confidence}, as_of={as_of}._")
    return "\n\n".join(parts) if parts else "_Empty answer._"


def steps_markdown(answer: Answer) -> str:
    if not answer.steps:
        return "_No steps recorded._"
    lines = ["Ordered working: reconstruct → tools → number lock.", ""]
    for step in answer.steps:
        detail = f" — {step.detail}" if step.detail else ""
        lines.append(f"{step.index}. **{step.name}**{detail}")
    return "\n".join(lines)


def ranking_frame(answer: Answer) -> tuple[list[str], list[list[Any]]]:
    raw_rows = answer.tables.get("ranking") or []
    traces = {trace.airport: trace for trace in answer.teoi_traces}
    headers = ["rank", "airport", "icao", "teoi", "constraint"]
    rows: list[list[Any]] = []
    if isinstance(raw_rows, list):
        for item in raw_rows:
            if not isinstance(item, dict):
                continue
            airport = str(item.get("airport") or "").upper()
            trace = traces.get(airport)
            constraint = item.get("constraint_type")
            if constraint is None and trace is not None:
                constraint = str(trace.constraint_type)
            teoi = item.get("teoi", item.get("score"))
            rows.append(
                [
                    item.get("rank"),
                    airport,
                    item.get("icao") or "",
                    _fmt(teoi, digits=1),
                    str(constraint or "—"),
                ]
            )
    return headers, rows


def ranking_badges_html(answer: Answer) -> str:
    headers, rows = ranking_frame(answer)
    if not rows:
        extra = _other_tables_markdown(answer)
        empty = "<p>No ranking in this answer. Ask a regional expansion question.</p>"
        return empty + (f"<pre>{_esc(extra)}</pre>" if extra else "")
    traces = {trace.airport: trace for trace in answer.teoi_traces}
    chips: list[str] = []
    for row in rows:
        airport = str(row[1])
        constraint = str(row[4]) if len(row) > 4 else ""
        trace = traces.get(airport)
        multiplier = trace.constraint_multiplier if trace else None
        chips.append(
            f'<span class="navaid-rank-chip"><strong>{_esc(airport)}</strong> '
            f"{constraint_badge(constraint, multiplier=multiplier)}</span>"
        )
    extra = _other_tables_markdown(answer)
    extra_html = f"<p>{_esc(extra)}</p>" if extra else ""
    present_types = [str(row[4]) for row in rows if len(row) > 4]
    why_html = "".join(_constraint_why_html(text) for text in _unique_constraint_explanations(present_types))
    return (
        '<div class="navaid-rank-chips">'
        + " ".join(chips)
        + "</div>"
        + f"<p class='navaid-muted'>Columns: {', '.join(headers)}.</p>"
        + why_html
        + extra_html
    )


def _other_tables_markdown(answer: Answer) -> str:
    chunks: list[str] = []
    unmet = answer.tables.get("unmet")
    if isinstance(unmet, dict) and unmet:
        chunks.append(
            "Unmet "
            f"{unmet.get('airport')}: unmet={_fmt(unmet.get('unmet'))}, "
            f"lf_gap={_fmt(unmet.get('lf_gap'))}, taf_gap={_fmt(unmet.get('taf_gap'))}, "
            f"leakage={_fmt(unmet.get('leakage'))}"
        )
    longhaul = answer.tables.get("longhaul")
    if isinstance(longhaul, dict) and longhaul:
        flight = longhaul.get("pct_longhaul_flights")
        pax = longhaul.get("pct_longhaul")
        chunks.append(
            "Long-haul "
            f"{longhaul.get('airport')}: "
            f"flights {_fmt(flight, digits=2)}%, passengers {_fmt(pax, digits=2)}% "
            f"> {longhaul.get('threshold_km') or 4000} km"
        )
    return "\n".join(chunks)


def waterfall_airports(answer: Answer) -> list[str]:
    return [trace.airport for trace in answer.teoi_traces]


def waterfall_markdown(traces: list[ScoringTrace], airport: str | None = None) -> str:
    if not traces:
        return (
            "_No TEOI traces in this answer._ Ask a ranking question "
            "(for example New England expansion candidates) to see "
            "raw → scaled → weights → contributions → multiplier → score → rank."
        )
    chosen = None
    if airport:
        needle = airport.strip().upper()
        chosen = next((t for t in traces if t.airport == needle), None)
    if chosen is None:
        chosen = traces[0]
    return _one_waterfall(chosen, peer_count=len(traces))


def waterfall_html(traces: list[ScoringTrace], airport: str | None = None) -> str:
    md = waterfall_markdown(traces, airport)
    if not traces:
        return f"<p>{_esc(md)}</p>"
    chosen = traces[0]
    if airport:
        needle = airport.strip().upper()
        chosen = next((t for t in traces if t.airport == needle), traces[0])
    return _one_waterfall_html(chosen) + f"<pre class='navaid-formula'>{_esc(chosen.formula_text)}</pre>"


def _one_waterfall(trace: ScoringTrace, *, peer_count: int) -> str:
    stages = " → ".join(WATERFALL_STAGES)
    lines = [
        f"### {trace.airport} — rank {trace.rank} — TEOI {_fmt(trace.teoi, digits=1)}",
        f"Peer set ({peer_count} scored): {', '.join(trace.peer_set)}",
        f"Waterfall: {stages}",
        f"Constraint: **{trace.constraint_type}** × {_fmt(trace.constraint_multiplier, digits=2)}",
    ]
    why = constraint_explanation_for(trace.constraint_type)
    if why:
        lines.append(why)
    lines.extend(
        [
            "",
            "| Feature | Raw | Scaled 0–1 | Weight original | Weight used | Contribution |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    features = list(FEATURE_ORDER)
    extra: list[str] = []
    seen = set(features)
    for key in list(trace.raw) + list(trace.scaled_0_1) + list(trace.weights_used):
        if key not in seen:
            seen.add(key)
            extra.append(key)
    for name in features + extra:
        raw = trace.raw.get(name)
        scaled = trace.scaled_0_1.get(name)
        w_orig = trace.weights_original.get(name)
        w_used = trace.weights_used.get(name)
        contrib = trace.contributions.get(name)
        dropped = " *(dropped)*" if name in trace.weights_dropped else ""
        lines.append(
            f"| {name}{dropped} | {_fmt(raw, percent=name in _PCT_KEYS)} | "
            f"{_fmt(scaled)} | {_fmt(w_orig)} | {_fmt(w_used)} | {_fmt(contrib, digits=2)} |"
        )
    if trace.weights_dropped:
        lines.append("")
        lines.append("Dropped and renormalized: " + ", ".join(trace.weights_dropped))
    lines.extend(
        [
            "",
            f"Weighted sum: **{_fmt(trace.weighted_sum, digits=2)}**",
            f"× constraint multiplier **{_fmt(trace.constraint_multiplier, digits=2)}** ({trace.constraint_type})",
            f"= TEOI **{_fmt(trace.teoi, digits=2)}** → rank **{trace.rank}**",
            "",
            f"`{trace.formula_text}`",
        ]
    )
    # Raw-only metrics that are not TEOI features (enplanements, gates, …)
    leftover_raw = [k for k in trace.raw if k not in FEATURE_ORDER]
    if leftover_raw:
        lines.append("")
        lines.append(
            "Raw inputs: "
            + ", ".join(f"{k}={_fmt(trace.raw[k], percent=k in _PCT_KEYS)}" for k in leftover_raw)
        )
    return "\n".join(lines)


def _one_waterfall_html(trace: ScoringTrace) -> str:
    max_contrib = max([abs(v) for v in trace.contributions.values()] or [1.0]) or 1.0
    bars: list[str] = []
    for name in FEATURE_ORDER:
        if name not in trace.weights_used and name not in trace.contributions:
            if name in trace.weights_dropped:
                bars.append(
                    f'<div class="navaid-bar-row"><span>{_esc(name)}</span>'
                    f'<div class="navaid-bar-track dropped"></div><span>dropped</span></div>'
                )
            continue
        contrib = float(trace.contributions.get(name) or 0.0)
        width = max(2.0, 100.0 * abs(contrib) / max_contrib)
        bars.append(
            f'<div class="navaid-bar-row"><span>{_esc(name)}</span>'
            f'<div class="navaid-bar-track"><div class="navaid-bar" style="width:{width:.1f}%"></div></div>'
            f"<span>{_esc(_fmt(contrib, digits=2))}</span></div>"
        )
    badge = constraint_badge(str(trace.constraint_type), multiplier=trace.constraint_multiplier)
    why = constraint_explanation_for(trace.constraint_type)
    return f"""
<div class="navaid-waterfall">
  <h3>{_esc(trace.airport)} {badge} rank {_esc(trace.rank)} · TEOI {_esc(_fmt(trace.teoi, digits=1))}</h3>
  <p class="navaid-muted">raw → scaled 0–1 → weights → contributions → multiplier → score → rank</p>
  {_constraint_why_html(why)}
  {''.join(bars)}
  <p>Weighted sum {_esc(_fmt(trace.weighted_sum, digits=2))}
     × {_esc(_fmt(trace.constraint_multiplier, digits=2))}
     = <strong>{_esc(_fmt(trace.teoi, digits=2))}</strong></p>
</div>
"""


def compare_markdown(answer: Answer) -> str:
    congestion = answer.tables.get("congestion")
    if not isinstance(congestion, dict) or not congestion:
        return (
            "_No two-airport compare payload in this answer._ "
            "Try: **Compare LA and Santa Ana airport congestion levels.** "
            "There is no single congestion score; axes are shown separately."
        )
    airports = [str(code).upper() for code in (congestion.get("airports") or [])]
    metrics = congestion.get("metrics") or {}
    winners = congestion.get("winner_on_each_axis") or {}
    if not airports and isinstance(metrics, dict):
        airports = [str(code).upper() for code in metrics.keys()]
    if len(airports) >= 2:
        title = f"{airports[0]} vs {airports[1]}"
        if len(airports) > 2:
            title += " (+ " + ", ".join(airports[2:]) + ")"
    else:
        title = "Congestion compare"
    lines = [
        f"### {title}",
        "Axis-by-axis compare. No composite congestion score.",
        "",
    ]
    axes = [
        ("delay_pct", "Delay %", True),
        ("avg_arrival_delay_min", "Avg arrival delay (min)", False),
        ("cancel_pct", "Cancel %", True),
        ("ops_per_runway", "Ops per runway", False),
        ("live_faa_status", "Live FAA status", False),
        ("constraint_type", "Constraint", False),
        ("curfew", "Curfew / policy", False),
    ]
    header = "| Axis | " + " | ".join(airports) + " | Winner |"
    sep = "| --- | " + " | ".join(["---"] * len(airports)) + " | --- |"
    lines.extend([header, sep])
    for key, label, is_pct in axes:
        cells: list[str] = []
        for code in airports:
            row = metrics.get(code) or metrics.get(code.lower()) or {}
            if not isinstance(row, dict):
                row = {}
            value = row.get(key)
            if key in {"constraint_type", "live_faa_status", "curfew"}:
                cells.append(str(value or "—"))
            else:
                cells.append(_fmt(value, percent=is_pct, digits=2))
        winner = winners.get(key) if isinstance(winners, dict) else None
        lines.append(f"| {label} | " + " | ".join(cells) + f" | {winner or '—'} |")
    lines.append("")
    lines.append("Constraint badge: airside (SNA-style curfew/slots) vs landside (terminal can help).")
    present_types: list[Any] = []
    if isinstance(metrics, dict):
        for row in metrics.values():
            if isinstance(row, dict) and row.get("constraint_type"):
                present_types.append(row.get("constraint_type"))
    for why in _unique_constraint_explanations(present_types):
        lines.append(why)
    if len(airports) >= 2:
        a, b = airports[0], airports[1]
        a_row = metrics.get(a) if isinstance(metrics.get(a), dict) else {}
        b_row = metrics.get(b) if isinstance(metrics.get(b), dict) else {}
        lines.append(
            f"{a} {constraint_badge((a_row or {}).get('constraint_type'))} vs "
            f"{b} {constraint_badge((b_row or {}).get('constraint_type'))}"
        )
    return "\n".join(lines)


def citations_markdown(answer: Answer) -> str:
    if not answer.citations:
        sources = answer.envelope.sources if answer.envelope else []
        if sources:
            return "Envelope sources:\n" + "\n".join(f"- {s}" for s in sources)
        return "_No citations on this turn._"
    lines = ["Sources quoted on this turn:", ""]
    for cite in answer.citations:
        bit = f"- **{cite.label}**"
        extras: list[str] = []
        if cite.source:
            extras.append(cite.source)
        if cite.as_of:
            extras.append(str(cite.as_of))
        if cite.url:
            extras.append(cite.url)
        if extras:
            bit += " — " + " · ".join(extras)
        lines.append(bit)
    return "\n".join(lines)


def eval_markdown(payload: dict[str, Any] | None) -> str:
    if not payload:
        return "_Could not load `/eval/summary`._"
    status = payload.get("status", "unknown")
    message = payload.get("message", "")
    lines = [
        f"**GET /eval/summary** — status `{status}`",
        "",
        str(message or ""),
    ]
    extras = {k: v for k, v in payload.items() if k not in {"status", "message"}}
    if extras:
        lines.append("")
        for key, value in extras.items():
            lines.append(f"- **{key}:** {value}")
    if status == "stub":
        lines.append("")
        lines.append("_Gold eval runner is a later phase; this panel shows whatever the API returns._")
    return "\n".join(lines).strip()


__all__ = [
    "WATERFALL_STAGES",
    "chat_reply",
    "citations_markdown",
    "compare_markdown",
    "constraint_badge",
    "envelope_html",
    "envelope_markdown",
    "eval_markdown",
    "ranking_badges_html",
    "ranking_frame",
    "steps_markdown",
    "waterfall_airports",
    "waterfall_html",
    "waterfall_markdown",
]
