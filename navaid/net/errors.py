"""Network and live-API errors. Offline mode fails loud on any HTTP attempt."""

from __future__ import annotations


class NavaidNetworkError(RuntimeError):
    """Base class for HTTP / live-status failures."""


class OfflineNetworkError(NavaidNetworkError):
    """Raised when NAVAID_OFFLINE=1 and a real network fetch is required."""


class CircuitOpenError(NavaidNetworkError):
    """Live FAA client is circuit-broken after repeated failures."""


class HttpRetryError(NavaidNetworkError):
    """Exhausted retries on 429 / 5xx (or other retryable HTTP)."""
