"""FastAPI `/ask` — OpenAPI contract over the Pydantic ``Answer``.

Heavy app imports (orchestrator → DuckDB) stay lazy so ``navaid.api.site``
can be imported by the GitHub Pages static export without warehouse deps.
"""

from __future__ import annotations

from typing import Any

__all__ = ["app", "create_app"]


def __getattr__(name: str) -> Any:
    if name in __all__:
        from navaid.api.app import app, create_app

        exports = {"app": app, "create_app": create_app}
        globals().update(exports)
        return exports[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
