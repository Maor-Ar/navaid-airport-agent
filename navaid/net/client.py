"""httpx client: timeout, 429/5xx backoff, on-disk cache, offline fail-loud.

Cache hits do not touch the network (including when NAVAID_OFFLINE=1).
A cache miss in offline mode raises OfflineNetworkError — never silent skip.
"""

from __future__ import annotations

import hashlib
import random
import re
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from navaid.config import NAVAID_OFFLINE, PROJECT_ROOT
from navaid.net.errors import HttpRetryError, OfflineNetworkError

CACHE_DIR = PROJECT_ROOT / "data" / "cache"

DEFAULT_TIMEOUT = httpx.Timeout(connect=20.0, read=180.0, write=60.0, pool=20.0)
DEFAULT_USER_AGENT = (
    "Navaid/0.1 (airport-investment-agent; +https://github.com/navaid) "
    "Mozilla/5.0 (compatible; NavaidBot/0.1)"
)
RETRY_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def cache_path_for(url: str, cache_dir: Path | None = None) -> Path:
    """Stable on-disk path for a URL (hash prefix + sanitized basename)."""

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    parsed = urlparse(url)
    base = Path(parsed.path).name or "download"
    base = _SAFE_NAME.sub("_", base)[:80]
    return (cache_dir or CACHE_DIR) / f"{digest}_{base}"


class CachedHttpClient:
    """Synchronous HTTP GET with disk cache and exponential backoff."""

    def __init__(
        self,
        *,
        cache_dir: Path | None = None,
        timeout: httpx.Timeout | None = None,
        offline: bool | None = None,
        max_retries: int = 5,
        user_agent: str = DEFAULT_USER_AGENT,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or CACHE_DIR)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout or DEFAULT_TIMEOUT
        self.offline = NAVAID_OFFLINE if offline is None else offline
        self.max_retries = max_retries
        self.headers = {"User-Agent": user_agent, "Accept": "*/*"}
        self.transport = transport

    def get_bytes(
        self,
        url: str,
        *,
        refresh: bool = False,
        allow_cache: bool = True,
    ) -> tuple[bytes, Path]:
        """Return (body, cache_path). Uses cache unless refresh=True."""

        path = cache_path_for(url, self.cache_dir)
        if allow_cache and not refresh and path.is_file() and path.stat().st_size > 0:
            return path.read_bytes(), path

        if self.offline:
            raise OfflineNetworkError(
                f"NAVAID_OFFLINE=1; refusing network GET {url}. "
                "Use a cache hit or a checked-in fixture."
            )

        body = self._get_with_retry(url)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)
        return body, path

    def _client(self) -> httpx.Client:
        kwargs: dict = {
            "timeout": self.timeout,
            "follow_redirects": True,
            "headers": self.headers,
        }
        if self.transport is not None:
            kwargs["transport"] = self.transport
        return httpx.Client(**kwargs)

    def download_file(
        self,
        url: str,
        *,
        refresh: bool = False,
        dest: Path | None = None,
    ) -> Path:
        """Stream a (possibly large) URL to disk; return the cache/dest path."""

        path = dest or cache_path_for(url, self.cache_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not refresh and path.is_file() and path.stat().st_size > 0:
            return path

        if self.offline:
            raise OfflineNetworkError(
                f"NAVAID_OFFLINE=1; refusing network download {url}."
            )

        tmp = path.with_suffix(path.suffix + ".tmp")
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._client() as client:
                    with client.stream("GET", url) as response:
                        if response.status_code in RETRY_STATUSES:
                            retry_after = _retry_after_seconds(response, attempt)
                            response.read()
                            time.sleep(retry_after)
                            continue
                        response.raise_for_status()
                        with tmp.open("wb") as handle:
                            for chunk in response.iter_bytes(1024 * 256):
                                handle.write(chunk)
                tmp.replace(path)
                return path
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                time.sleep(_backoff_seconds(attempt))
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in RETRY_STATUSES:
                    time.sleep(_retry_after_seconds(exc.response, attempt))
                    continue
                raise
        raise HttpRetryError(f"download failed after retries: {url}") from last_exc

    def _get_with_retry(self, url: str) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with self._client() as client:
                    response = client.get(url)
                    if response.status_code in RETRY_STATUSES:
                        time.sleep(_retry_after_seconds(response, attempt))
                        last_exc = HttpRetryError(
                            f"HTTP {response.status_code} for {url}"
                        )
                        continue
                    response.raise_for_status()
                    return response.content
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                time.sleep(_backoff_seconds(attempt))
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in RETRY_STATUSES:
                    time.sleep(_retry_after_seconds(exc.response, attempt))
                    continue
                raise
        raise HttpRetryError(f"GET failed after retries: {url}") from last_exc


def _backoff_seconds(attempt: int) -> float:
    return min(32.0, (2**attempt)) + random.uniform(0, 0.25)


def _retry_after_seconds(response: httpx.Response, attempt: int) -> float:
    header = response.headers.get("Retry-After")
    if header:
        try:
            return max(0.5, float(header))
        except ValueError:
            pass
    return _backoff_seconds(attempt)


__all__ = ["CACHE_DIR", "CachedHttpClient", "cache_path_for"]
