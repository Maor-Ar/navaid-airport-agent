"""Airport entity resolution. Aliases beat fuzzy search (LA→LAX, Santa Ana→SNA)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from navaid.config import DEEP_SLICE_IATA, NEW_ENGLAND_IATA

if TYPE_CHECKING:
    from navaid.agent.sessions import SessionMemory
    from navaid.warehouse.metrics import MetricsCatalog

# Longest keys first when matching. "LA" is Los Angeles International, not the metro.
_ALIAS_PAIRS: tuple[tuple[str, str], ...] = (
    ("los angeles international", "LAX"),
    ("john wayne", "SNA"),
    ("santa ana", "SNA"),
    ("orange county", "SNA"),
    ("ted stevens", "ANC"),
    ("anchorage", "ANC"),
    ("san francisco", "SFO"),
    ("san jose", "SJC"),
    ("los angeles", "LAX"),
    ("t.f. green", "PVD"),
    ("tf green", "PVD"),
    ("portland maine", "PWM"),
    ("portland me", "PWM"),
    ("portland jetport", "PWM"),
    ("san antonio", "SAT"),
    ("bradley", "BDL"),
    ("hartford", "BDL"),
    ("providence", "PVD"),
    ("oakland", "OAK"),
    ("manchester", "MHT"),
    ("burlington", "BTV"),
    ("worcester", "ORH"),
    ("bangor", "BGR"),
    ("logan", "BOS"),
    ("boston", "BOS"),
    ("portland", "PWM"),  # assignment: PWM is Maine, not PDX
)

# Two-letter / short forms that must not match inside other words.
_SHORT_ALIAS: dict[str, str] = {
    "la": "LAX",
}

_ANAPHORA = re.compile(
    r"\b(those two|those airports|the two|both of them|\bthem\b)\b",
    re.IGNORECASE,
)
_NEW_ENGLAND = re.compile(r"\bnew england\b", re.IGNORECASE)
_IATA_TOKEN = re.compile(r"\b([A-Za-z]{3})\b")
_STOP = frozenset(
    {
        "AND", "THE", "FOR", "OUT", "ARE", "WAS", "NOT", "HOW", "WHY", "WHO",
        "ANY", "ALL", "NEW", "ADD", "CAN", "HAS", "HAD", "BUT", "PER", "VIA",
        "OFF", "OUR", "ITS", "USA", "FAA", "BTS", "TAF", "AIP", "OTP", "GDP",
        "VS", "ALSO", "RANK", "TWO", "ONE",
    }
)
_KNOWN = set(DEEP_SLICE_IATA) | {pair[1] for pair in _ALIAS_PAIRS} | {"SAT"}


def is_new_england(text: str) -> bool:
    return bool(_NEW_ENGLAND.search(text))


def resolve_alias(token: str) -> str | None:
    key = re.sub(r"\s+", " ", token.strip().lower())
    if key in _SHORT_ALIAS:
        return _SHORT_ALIAS[key]
    for alias, iata in _ALIAS_PAIRS:
        if key == alias:
            return iata
    return None


def extract_airports(
    text: str,
    *,
    session: SessionMemory | None = None,
    catalog: MetricsCatalog | None = None,
) -> list[str]:
    """Ordered unique IATA codes mentioned in ``text`` (aliases, codes, session)."""

    found: list[str] = []

    def add(code: str | None) -> None:
        if not code:
            return
        iata = code.strip().upper()
        if iata and iata not in found:
            found.append(iata)

    # Position-ordered so "LA and Santa Ana" → LAX, SNA (Santa Ana never SAT).
    spans: list[tuple[int, int, str]] = []
    for alias, iata in sorted(_ALIAS_PAIRS, key=lambda item: -len(item[0])):
        for match in re.finditer(rf"\b{re.escape(alias)}\b", text, re.IGNORECASE):
            spans.append((match.start(), match.end(), iata))
    for match in re.finditer(r"\bLA\b", text, re.IGNORECASE):
        spans.append((match.start(), match.end(), "LAX"))
    spans.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    used_ranges: list[tuple[int, int]] = []
    masked_chars = list(text)
    for start, end, iata in spans:
        if any(start < used_end and end > used_start for used_start, used_end in used_ranges):
            continue
        used_ranges.append((start, end))
        add(iata)
        for i in range(start, end):
            masked_chars[i] = " "
    masked = "".join(masked_chars)

    known = set(_KNOWN)
    if catalog is not None:
        try:
            known |= catalog.known_iata()
        except Exception:
            pass

    for match in _IATA_TOKEN.finditer(masked):
        token = match.group(1).upper()
        if token in _STOP:
            continue
        if token in known:
            add(token)

    if catalog is not None:
        leftover = masked.strip()
        if leftover and not found:
            for hit in catalog.lookup_name(leftover, limit=3):
                add(hit["iata"])

    if _ANAPHORA.search(text) and session is not None:
        for code in session.last_entities or session.last_peer_set:
            add(code)

    if is_new_england(text) and not found:
        region = None
        if catalog is not None:
            try:
                region = catalog.iata_in_region("New England")
            except Exception:
                region = None
        for code in region or NEW_ENGLAND_IATA:
            add(code)

    return found


def resolve_one(
    query: str,
    *,
    session: SessionMemory | None = None,
    catalog: MetricsCatalog | None = None,
) -> dict[str, Any]:
    """Resolve a single mention. LA→LAX (not metro); Santa Ana→SNA (not SAT)."""

    raw = query.strip()
    if not raw:
        return {"query": query, "iata": None, "matches": [], "notes": "empty query"}

    if _ANAPHORA.search(raw) and session is not None:
        codes = list(session.last_entities or session.last_peer_set)
        return {
            "query": query,
            "iata": codes[0] if len(codes) == 1 else None,
            "matches": codes,
            "notes": "resolved from session anaphora",
        }

    if is_new_england(raw):
        codes = list(NEW_ENGLAND_IATA)
        if catalog is not None:
            try:
                codes = catalog.iata_in_region("New England") or codes
            except Exception:
                pass
        return {
            "query": query,
            "iata": None,
            "matches": codes,
            "region": "New England",
            "notes": "New England = CT, ME, MA, NH, RI, VT",
        }

    alias = resolve_alias(raw)
    if alias:
        notes = "alias"
        if raw.strip().upper() == "LA" or raw.strip().lower() == "la":
            notes = "LA resolves to LAX, not the Los Angeles metro"
        if "santa ana" in raw.lower():
            notes = "Santa Ana resolves to SNA (John Wayne), not SAT (San Antonio)"
        if "anchorage" in raw.lower():
            notes = "Anchorage resolves to ANC"
        return {"query": query, "iata": alias, "matches": [alias], "notes": notes}

    codes = extract_airports(raw, session=session, catalog=catalog)
    if codes:
        return {
            "query": query,
            "iata": codes[0] if len(codes) == 1 else None,
            "matches": codes,
            "notes": "extracted IATA",
        }

    if catalog is not None:
        hits = catalog.lookup_name(raw, limit=5)
        # Guard: never prefer SAT for Santa Ana (alias already handled).
        if "santa ana" in raw.lower():
            hits = [h for h in hits if h["iata"] == "SNA"] or hits
        if hits:
            return {
                "query": query,
                "iata": hits[0]["iata"],
                "matches": [h["iata"] for h in hits],
                "notes": "warehouse name/municipality match",
            }

    return {"query": query, "iata": None, "matches": [], "notes": "unresolved"}
