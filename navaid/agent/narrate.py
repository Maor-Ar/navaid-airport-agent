"""Section narration from tool payloads. Template is the no-key path; Gemini optional."""

from __future__ import annotations

import json
from typing import Any

from navaid.agent.jsonutil import jsonable
from navaid.agent.number_lock import lock_prose
from navaid.schemas import Intent, Section, Subgoal, SubgoalStatus, UnsupportedPart


def template_section(subgoal: Subgoal, payload: dict[str, Any] | None, index: int) -> Section:
    heading = _heading(subgoal)
    if subgoal.intent == Intent.UNSUPPORTED:
        body = (
            f"Out of scope: {subgoal.query or 'this part'}. "
            f"{subgoal.notes or 'Navaid does not advise on securities or non-airport questions.'}"
        )
        return Section(heading=heading, body=body, subgoal_index=index)

    if not payload or payload.get("error"):
        err = (payload or {}).get("error") or "no tool payload"
        return Section(
            heading=heading,
            body=f"Could not answer this part ({err}).",
            subgoal_index=index,
        )

    result = payload.get("result", payload)
    if subgoal.intent == Intent.EXPANSION_RANK:
        ranking = result.get("ranking") or []
        peer = result.get("peer_set") or result.get("ranking_peer_set") or []
        if not peer and ranking:
            peer = [row.get("airport") for row in ranking if row.get("airport")]
        lines = [
            "### Expansion rank",
            "This is an **EXPANSION_RANK**: ordinals 1, 2, 3… after TEOI is computed "
            "**inside this peer set**, not a national airport grade and not FAA hub size.",
            "",
            f"**Peer set S:** {', '.join(str(c) for c in peer) or '—'}.",
            "Busy is not investable; a landside-constrained regional can outrank a larger hub "
            "because the comparison is only versus these airports.",
            "",
            "### Ranking",
        ]
        for row in ranking:
            lines.append(
                f"{row.get('rank')}. **{row.get('airport')}** — TEOI "
                f"**{row.get('teoi')}** (`{row.get('constraint_type')}`)"
            )
        traces = result.get("teoi_traces") or []
        if traces:
            lines.append("")
            lines.append(f"**Formula (first trace):** `{traces[0].get('formula_text')}`")
        body = "\n".join(str(x) for x in lines)
    elif subgoal.intent == Intent.EXPLAIN_TEOI:
        traces = result.get("teoi_traces") or []
        reused = result.get("reused_traces")
        peer = result.get("peer_set") or []
        lines = [
            "### Why the score depends on the other airports",
            "TEOI is **peer-relative**. Each feature is min-max scaled 0–1 **inside peer set S**, "
            "then weighted, then multiplied by the constraint factor.",
            "",
            f"**Peer set S:** {', '.join(peer) or '—'}.",
            (
                "This is **not a new ranking**. The numbers below are the last traces for that set."
                if reused
                else "Traces computed for this request."
            ),
            "",
            "- Highest in S on a feature scales to **1**; lowest scales to **0**.",
            "- A one-airport set has no spread, so every present feature scales to **0.5** "
            "(for example mixed × 0.75 → TEOI 37.5). That is a different *set*, not a different formula.",
            "- Follow-ups such as “why this score?” must reuse S. They must not re-rank a singleton.",
            "",
            "### Traces",
        ]
        for trace in traces:
            lines.append(
                f"- **{trace.get('airport')}**: TEOI **{trace.get('teoi')}**, "
                f"expansion rank {trace.get('rank')}, constraint `{trace.get('constraint_type')}` "
                f"× {trace.get('constraint_multiplier')}"
            )
        body = "\n".join(str(x) for x in lines)
    elif subgoal.intent == Intent.CONGESTION_COMPARE:
        winners = result.get("winner_on_each_axis") or {}
        airports = result.get("airports") or subgoal.entities
        lines = [
            f"Congestion compare for {' vs '.join(airports)} is **axis-by-axis**; "
            "there is no single congestion score.",
            "",
        ]
        for axis, winner in winners.items():
            lines.append(f"- **{axis}** winner: {winner}")
        metrics = result.get("metrics") or {}
        for code, mets in metrics.items():
            if isinstance(mets, dict):
                delay = mets.get("delay_pct")
                constraint = mets.get("constraint_type")
                lines.append(
                    f"- **{code}**: delay_pct={delay}, constraint_type={constraint}"
                )
        body = "\n".join(str(x) for x in lines)
    elif subgoal.intent == Intent.LONGHAUL_SHARE:
        body = (
            f"{result.get('airport')} long-haul share is {result.get('pct_longhaul')} percent "
            f"of T-100 segment passengers above {result.get('threshold_km')} km "
            f"({result.get('passengers_longhaul')} of {result.get('passengers_total')} passengers; "
            f"international share {result.get('pct_international')} percent). "
            f"Cargo excluded: {result.get('cargo_excluded')}."
        )
    elif subgoal.intent == Intent.UNMET_DEMAND:
        body = (
            f"{result.get('airport')} unmet demand is {result.get('unmet')} "
            f"(served {result.get('served')}, load_factor {result.get('load_factor')}, "
            f"lf_gap {result.get('lf_gap')}, taf_gap {result.get('taf_gap')}, "
            f"leakage {result.get('leakage')} to {result.get('leakage_peers')}). "
            "Unmet is max(0, implied - served). Much of a slot/curfew airport's gap can be airside."
        )
    else:
        # AIRPORT_BRIEF and unknown
        dump = json.dumps(jsonable(result), default=str)
        if len(dump) > 1800:
            dump = dump[:1800] + "…"
        body = f"Warehouse metrics: {dump}"

    return Section(heading=heading, body=body, subgoal_index=index)


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
            Section(heading=section.heading, body=body or section.body, subgoal_index=section.subgoal_index)
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
    if subgoal.intent == Intent.UNSUPPORTED:
        return "Unsupported"
    if subgoal.entities:
        return f"{subgoal.intent.value}: {', '.join(subgoal.entities)}"
    return subgoal.intent.value


def gemini_prompt(
    reconstructed_query: str,
    subgoals: list[Subgoal],
    payloads: list[dict[str, Any]],
) -> str:
    blob = json.dumps(jsonable(payloads), default=str)
    if len(blob) > 80_000:
        blob = blob[:80_000] + "…(truncated)"
    lines = [
        f"Reconstructed question: {reconstructed_query}",
        "Subgoals (answer every one; one section per subgoal):",
    ]
    for i, sg in enumerate(subgoals):
        lines.append(f"{i}. {sg.intent.value} entities={sg.entities} notes={sg.notes}")
    lines.append("Tool JSON (the only numbers you may quote):")
    lines.append(blob)
    lines.append(
        "Write sections as:\n===SECTION 0===\nheading on this line\nbody\n===SECTION 1===\n..."
        "\nKeep Markdown line breaks. Use ##/### headings, **bold**, and lists. "
        "Do not flatten a list into one paragraph."
    )
    return "\n".join(lines)


def parse_gemini_sections(text: str, subgoals: list[Subgoal]) -> list[Section] | None:
    if "===SECTION" not in text:
        return None
    parts = text.split("===SECTION")
    sections: list[Section] = []
    for part in parts[1:]:
        # format: " 0 ===\nheading\nbody" — keep Markdown newlines in the body
        rest = part.split("===", 1)
        chunk = rest[1] if len(rest) > 1 else rest[0]
        raw_lines = [ln.rstrip() for ln in chunk.strip().splitlines()]
        while raw_lines and not raw_lines[0].strip():
            raw_lines.pop(0)
        if not raw_lines:
            continue
        heading = raw_lines[0].strip()
        body = "\n".join(raw_lines[1:]).strip() if len(raw_lines) > 1 else heading
        idx = len(sections)
        sections.append(Section(heading=heading, body=body, subgoal_index=idx))
    if len(sections) < len([s for s in subgoals if s.intent != Intent.UNSUPPORTED]) and len(sections) < 1:
        return None
    return sections or None
