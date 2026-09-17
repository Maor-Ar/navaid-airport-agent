"""Rewrite follow-ups into a standalone reconstructed_query using session memory."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from navaid.agent.entities import extract_airports, resolve_one
from navaid.agent.sessions import SessionMemory

_THOSE = re.compile(
    r"\b(those two|those airports|the two|both of them)\b",
    re.IGNORECASE,
)
_WHY_ABOVE = re.compile(
    r"why is #?(?P<a>\d+)\s+above\s+#?(?P<b>\d+)",
    re.IGNORECASE,
)
_WHY_RANK = re.compile(
    r"why is (?:rank\s+)?#?(?P<a>\d+)\b",
    re.IGNORECASE,
)
_WHY_SCORE = re.compile(
    r"\b(why|explain|how)\b.+\b(teoi|score|ranked|ranking)\b"
    r"|\bwhy\b.+\b(this|that|the)\b.+\b(score|teoi)\b"
    r"|\bhow (?:is|was|did|does)\b.+\b(scored|score|teoi)\b",
    re.IGNORECASE,
)
_ADD = re.compile(
    r"\b(?:add|include|plus)\s+(?P<tok>[A-Za-z]{3}|[A-Za-z][A-Za-z .'-]{2,})",
    re.IGNORECASE,
)
_CURFEW = re.compile(r"\bcurfew|constraint[- ]type\b", re.IGNORECASE)
_CARGO = re.compile(r"\bcargo\b", re.IGNORECASE)


@dataclass
class Reconstruction:
    reconstructed_query: str
    notes: str
    independent: bool
    reuse_traces: bool = False
    rerun_ranker: bool = False
    added_airports: list[str] = field(default_factory=list)
    filled_airports: list[str] = field(default_factory=list)


def reconstruct(question: str, session: SessionMemory | None) -> Reconstruction:
    """Build a standalone question. First-turn and independent questions are no-ops."""

    q = question.strip()
    if session is None or not session.turns:
        return Reconstruction(
            reconstructed_query=q,
            notes="first turn; reconstruction is a no-op",
            independent=True,
        )

    add_match = _ADD.search(q)
    if add_match and session.last_peer_set:
        token = add_match.group("tok").strip()
        resolved = resolve_one(token)
        code = resolved.get("iata") or (resolved.get("matches") or [None])[0]
        if code:
            peer = [c.upper() for c in session.last_peer_set]
            if code.upper() not in peer:
                peer.append(code.upper())
            return Reconstruction(
                reconstructed_query=(
                    f"Rank terminal expansion candidates in peer set "
                    f"[{', '.join(peer)}] using the same TEOI recipe; add {code.upper()}"
                ),
                notes=f"added {code.upper()} to last peer set; re-run ranker",
                independent=False,
                rerun_ranker=True,
                added_airports=[code.upper()],
                filled_airports=peer,
            )

    why = _WHY_ABOVE.search(q) or _WHY_RANK.search(q)
    if why and (session.last_traces or session.last_peer_set):
        rank_a = int(why.group("a"))
        rank_b = int(why.group("b")) if "b" in why.re.groupindex and why.groupdict().get("b") else rank_a + 1
        peer = session.last_peer_set
        peer_txt = ", ".join(peer) if peer else "last peer set"
        return Reconstruction(
            reconstructed_query=(
                f"Explain TEOI traces for rank {rank_a} vs rank {rank_b} "
                f"in peer set [{peer_txt}]"
            ),
            notes="reuse last TEOI traces; do not invent a new ranking",
            independent=False,
            reuse_traces=True,
            filled_airports=list(peer),
        )

    codes_in_q = extract_airports(q, session=None)
    if session.last_traces and _is_teoi_explain(q, codes_in_q, session):
        peer = [c.upper() for c in session.last_peer_set]
        codes = [c for c in codes_in_q if not peer or c in set(peer)] or codes_in_q
        focus = ", ".join(codes) if codes else "the last ranking"
        peer_txt = ", ".join(peer) if peer else "last peer set"
        return Reconstruction(
            reconstructed_query=(
                f"Explain TEOI traces for {focus} in peer set [{peer_txt}]; "
                "reuse last traces, do not re-rank a singleton set"
            ),
            notes="reuse last TEOI traces; do not invent a new ranking",
            independent=False,
            reuse_traces=True,
            filled_airports=codes or list(peer),
        )

    those = _THOSE.search(q)
    if those:
        pair = list(session.last_entities or session.last_peer_set)[:2]
        if pair:
            filled = " and ".join(pair)
            rewritten = _THOSE.sub(filled, q, count=1)
            extra = ""
            if _CURFEW.search(q):
                rewritten = (
                    f"Compare constraint type and curfew for {' vs '.join(pair)} "
                    "using last congestion payload; re-run only if needed."
                )
                extra = "; copied last congestion payload"
            return Reconstruction(
                reconstructed_query=rewritten,
                notes=f"filled anaphora from session: {pair}{extra}",
                independent=False,
                filled_airports=pair,
            )

    if _CURFEW.search(q) and session.last_entities and not extract_airports(q, session=None):
        pair = list(session.last_entities)
        return Reconstruction(
            reconstructed_query=(
                f"Compare constraint type and curfew for {' vs '.join(pair)} "
                "using last congestion payload; re-run only if needed."
            ),
            notes="copied last congestion airports for curfew/constraint follow-up",
            independent=False,
            filled_airports=pair,
        )

    if _CARGO.search(q) and session.last_entities and not extract_airports(q, session=None):
        airport = session.last_entities[0]
        return Reconstruction(
            reconstructed_query=(
                f"What is the long-haul share out of {airport} including cargo"
            ),
            notes=f"copied last airport {airport} for cargo follow-up",
            independent=False,
            filled_airports=[airport],
        )

    new_codes = extract_airports(q, session=None)
    if new_codes and not those:
        return Reconstruction(
            reconstructed_query=q,
            notes="independent question; reconstruction is a no-op",
            independent=True,
        )

    if session.last_entities and _looks_like_followup(q):
        pair = list(session.last_entities)
        return Reconstruction(
            reconstructed_query=f"{q} (airports: {', '.join(pair)})",
            notes=f"copied last entities {pair} onto an underspecified follow-up",
            independent=False,
            filled_airports=pair,
        )

    return Reconstruction(
        reconstructed_query=q,
        notes="independent question; reconstruction is a no-op",
        independent=True,
    )


def _is_teoi_explain(question: str, codes: list[str], session: SessionMemory) -> bool:
    last = {str(t.get("airport", "")).upper() for t in session.last_traces}
    last.update(code.upper() for code in session.last_peer_set)
    if codes and last and not any(code in last for code in codes):
        return False
    if _WHY_SCORE.search(question):
        return True
    q = question.lower()
    if "why" not in q and "explain" not in q:
        return False
    return bool(last and codes and any(code in last for code in codes))


def _looks_like_followup(question: str) -> bool:
    q = question.lower()
    if re.search(r"\b(it|they|them|that|those|the same|again)\b", q):
        return True
    if len(question.split()) <= 6 and not extract_airports(question, session=None):
        return True
    return False
