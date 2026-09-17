from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from navaid.net.client import CachedHttpClient
from navaid.net.errors import CircuitOpenError, OfflineNetworkError
from navaid.net.faa_live import CircuitBreaker, _parse_nas_xml


def test_offline_fails_loud_on_cache_miss(tmp_path: Path) -> None:
    client = CachedHttpClient(cache_dir=tmp_path, offline=True)
    with pytest.raises(OfflineNetworkError, match="NAVAID_OFFLINE"):
        client.get_bytes("https://example.test/airports.csv")


def test_offline_uses_cache_without_network(tmp_path: Path) -> None:
    client = CachedHttpClient(cache_dir=tmp_path, offline=False, transport=_transport(b"abc"))
    body, path = client.get_bytes("https://example.test/file.csv")
    assert body == b"abc"
    assert path.is_file()

    offline = CachedHttpClient(cache_dir=tmp_path, offline=True)
    cached, _ = offline.get_bytes("https://example.test/file.csv")
    assert cached == b"abc"


def test_retries_429_then_succeeds(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("navaid.net.client.time.sleep", lambda *_a, **_k: None)
    hits = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        hits["n"] += 1
        if hits["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, content=b"ok")

    client = CachedHttpClient(
        cache_dir=tmp_path,
        offline=False,
        transport=httpx.MockTransport(handler),
        max_retries=4,
    )
    body, _ = client.get_bytes("https://example.test/retry.csv")
    assert body == b"ok"
    assert hits["n"] == 3


def test_circuit_breaker_opens() -> None:
    breaker = CircuitBreaker(failure_threshold=2, reset_seconds=60)
    breaker.record_failure()
    breaker.allow()
    breaker.record_failure()
    with pytest.raises(CircuitOpenError):
        breaker.allow()


def test_nas_xml_parse_extracts_airports() -> None:
    xml = """
    <AIRPORT_STATUS_INFORMATION>
      <Delay_type>
        <Ground_Delay>
          <Airport>SFO</Airport>
          <Reason>Weather</Reason>
        </Ground_Delay>
      </Delay_type>
    </AIRPORT_STATUS_INFORMATION>
    """
    parsed = _parse_nas_xml(xml)
    assert "SFO" in parsed["airports"]
    assert parsed["airports"]["SFO"]["reason"] == "Weather"


def _transport(body: bytes) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    return httpx.MockTransport(handler)
