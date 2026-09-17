"""HTTP client for public APIs (httpx + on-disk cache) and live FAA overlay."""

from navaid.net.client import CACHE_DIR, CachedHttpClient, cache_path_for
from navaid.net.errors import (
    CircuitOpenError,
    HttpRetryError,
    NavaidNetworkError,
    OfflineNetworkError,
)
from navaid.net.faa_live import (
    AirportLiveStatus,
    CircuitBreaker,
    fetch_asws_status,
    fetch_nas_status,
    live_status_for,
)

__all__ = [
    "CACHE_DIR",
    "AirportLiveStatus",
    "CachedHttpClient",
    "CircuitBreaker",
    "CircuitOpenError",
    "HttpRetryError",
    "NavaidNetworkError",
    "OfflineNetworkError",
    "cache_path_for",
    "fetch_asws_status",
    "fetch_nas_status",
    "live_status_for",
]
