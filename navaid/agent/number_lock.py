"""Every numeric token in prose must already appear in tool JSON / traces."""

from __future__ import annotations

import math
import re
from typing import Any

from navaid.agent.jsonutil import jsonable

# Integers with optional thousands separators, decimals, optional trailing %.
NUMBER_RE = re.compile(
    r"(?<![A-Za-z_])[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?"
)


def _canonical_forms(value: float) -> set[str]:
    forms: set[str] = set()
    if math.isnan(value) or math.isinf(value):
        return forms
    abs_value = abs(value)
    # Integer-looking
    if abs(value - round(value)) < 1e-9 and abs_value < 1e15:
        as_int = int(round(value))
        forms.add(str(as_int))
        forms.add(f"{as_int:,}")
        forms.add(str(abs(as_int)))
    # Compact and fixed decimals
    text = format(value, ".12g")
    forms.add(text)
    forms.add(text.replace("-", ""))
    if "." in text:
        forms.add(text.rstrip("0").rstrip("."))
    for decimals in (1, 2, 3, 4):
        forms.add(f"{value:.{decimals}f}")
        forms.add(f"{value:.{decimals}f}".rstrip("0").rstrip("."))
    # Rates in (0, 1) often narrated as percents.
    if 0 < abs_value < 1:
        pct = abs_value * 100.0
        forms.add(format(pct, ".12g"))
        forms.add(f"{pct:.1f}")
        forms.add(f"{pct:.2f}")
        forms.add(f"{pct:.0f}")
    # Percents stored as 12.5 (already 0–100) — also allow the decimal rate.
    if 1 <= abs_value <= 100:
        forms.add(format(abs_value / 100.0, ".12g"))
    return {f for f in forms if f and f not in {"-", "+", "."}}


def _forms_from_token(token: str) -> set[str]:
    raw = token.strip()
    pct = raw.endswith("%")
    body = raw[:-1] if pct else raw
    body = body.replace(",", "")
    try:
        number = float(body)
    except ValueError:
        return {raw}
    forms = _canonical_forms(number)
    forms.add(raw)
    forms.add(body)
    if pct:
        forms.update(_canonical_forms(number / 100.0))
    return forms


# Ordinary English quantities that are not engine inventions (10-year TAF, 100-point TEOI).
_PROSE_INTEGERS = {"10", "100", "90", "4000", "5420", "3370"}


def collect_allowed_numbers(payloads: Any) -> set[str]:
    allowed: set[str] = set(_PROSE_INTEGERS)

    def walk(node: Any) -> None:
        if isinstance(node, bool):
            return
        if isinstance(node, int):
            allowed.update(_canonical_forms(float(node)))
            return
        if isinstance(node, float):
            allowed.update(_canonical_forms(node))
            return
        if isinstance(node, str):
            for match in NUMBER_RE.finditer(node):
                allowed.update(_forms_from_token(match.group(0)))
            return
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
            return
        if isinstance(node, (list, tuple)):
            for value in node:
                walk(value)

    walk(jsonable(payloads))
    walk(jsonable(payloads, round_floats=True))
    return allowed


def number_allowed(token: str, allowed: set[str]) -> bool:
    forms = _forms_from_token(token)
    return bool(forms.intersection(allowed))


def lock_prose(prose: str, payloads: Any) -> tuple[str, list[str]]:
    """Strip numeric tokens that do not appear in ``payloads``. Returns (text, stripped)."""

    allowed = collect_allowed_numbers(payloads)
    stripped: list[str] = []

    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        if number_allowed(token, allowed):
            return token
        stripped.append(token)
        return ""

    locked = NUMBER_RE.sub(repl, prose)
    locked = re.sub(r"[ \t]{2,}", " ", locked)
    locked = re.sub(r" +([,.;:])", r"\1", locked)
    locked = re.sub(r"\n{3,}", "\n\n", locked)
    return locked.strip(), stripped


__all__ = [
    "NUMBER_RE",
    "collect_allowed_numbers",
    "lock_prose",
    "number_allowed",
]
