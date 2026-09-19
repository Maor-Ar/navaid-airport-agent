"""Gemini orchestrator: reconstruct, decompose, manual tools, number lock.

Not LangChain. Automatic function calling is disabled.

Orchestrator and session imports stay lazy so importing this package does not
require DuckDB (the warehouse is pulled in by ``sessions``).
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "SessionMemory",
    "ask",
    "decompose",
    "lock_prose",
    "new_session_id",
    "reconstruct",
]

_EXPORTS = {
    "SessionMemory": "navaid.agent.sessions",
    "ask": "navaid.agent.orchestrator",
    "decompose": "navaid.agent.decompose",
    "lock_prose": "navaid.agent.number_lock",
    "new_session_id": "navaid.agent.sessions",
    "reconstruct": "navaid.agent.reconstruct",
}


def __getattr__(name: str) -> Any:
    if name in _EXPORTS:
        value = getattr(import_module(_EXPORTS[name]), name)
        globals()[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
