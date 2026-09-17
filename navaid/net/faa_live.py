"""Live FAA NAS / ASWS status. Overlay only — never a TEOI / scoring input.

Circuit-breaks after repeated failures so a down feed cannot stall the agent.
"""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import httpx

from navaid.config import FAA_ASWS_STATUS_TEMPLATE, FAA_NAS_STATUS_URL, NAVAID_OFFLINE
from navaid.net.client import DEFAULT_TIMEOUT, DEFAULT_USER_AGENT
from navaid.net.errors import CircuitOpenError, OfflineNetworkError

# Alternate ASWS hosts; the config template 404s on some environments.
_ASWS_TEMPLATES = (
    FAA_ASWS_STATUS_TEMPLATE,
    "https://soa.smext.faa.gov/asws/api/airport/status/{airportCode}",
    "https://external-api.faa.gov/asws/api/airport/status/{airportCode}",
)


@dataclass
class CircuitBreaker:
    failure_threshold: int = 3
    reset_seconds: float = 300.0
    failures: int = 0
    opened_at: float | None = None

    def allow(self) -> None:
        if self.opened_at is None:
            return
        if time.monotonic() - self.opened_at >= self.reset_seconds:
            self.failures = 0
            self.opened_at = None
            return
        raise CircuitOpenError(
            "FAA live status circuit is open; skipping network call "
            f"(reset in {self.reset_seconds:.0f}s)."
        )

    def record_success(self) -> None:
        self.failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_threshold:
            self.opened_at = time.monotonic()


_NAS_BREAKER = CircuitBreaker()
_ASWS_BREAKER = CircuitBreaker()


@dataclass
class AirportLiveStatus:
    """Parsed live delay overlay. Not a warehouse metric and not a score input."""

    airport: str
    source: str
    fetched_at: str
    delay: bool | None = None
    status: str | None = None
    reason: str | None = None
    programs: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


def fetch_nas_status(
    *,
    offline: bool | None = None,
    breaker: CircuitBreaker | None = None,
    timeout: httpx.Timeout | None = None,
) -> dict[str, Any]:
    """GET NAS Status XML and return a JSON-able dict. Circuit-breaks on failure."""

    if (NAVAID_OFFLINE if offline is None else offline):
        raise OfflineNetworkError("NAVAID_OFFLINE=1; NAS status is a live call.")
    cb = breaker or _NAS_BREAKER
    cb.allow()
    try:
        with httpx.Client(
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/xml"},
        ) as client:
            response = client.get(FAA_NAS_STATUS_URL)
            response.raise_for_status()
        parsed = _parse_nas_xml(response.text)
        cb.record_success()
        return parsed
    except CircuitOpenError:
        raise
    except Exception:
        cb.record_failure()
        raise


def fetch_asws_status(
    airport_code: str,
    *,
    offline: bool | None = None,
    breaker: CircuitBreaker | None = None,
    timeout: httpx.Timeout | None = None,
) -> AirportLiveStatus:
    """GET ASWS JSON for one airport. Circuit-breaks; tries known URL templates."""

    if (NAVAID_OFFLINE if offline is None else offline):
        raise OfflineNetworkError("NAVAID_OFFLINE=1; ASWS status is a live call.")
    code = airport_code.strip().upper()
    cb = breaker or _ASWS_BREAKER
    cb.allow()
    last_exc: Exception | None = None
    try:
        with httpx.Client(
            timeout=timeout or DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"},
        ) as client:
            for template in _ASWS_TEMPLATES:
                url = template.format(airportCode=code)
                try:
                    response = client.get(url)
                    if response.status_code == 404:
                        last_exc = httpx.HTTPStatusError(
                            "404", request=response.request, response=response
                        )
                        continue
                    response.raise_for_status()
                    payload = response.json()
                    cb.record_success()
                    return _asws_to_status(code, payload)
                except CircuitOpenError:
                    raise
                except Exception as exc:
                    last_exc = exc
                    continue
        raise last_exc or RuntimeError(f"ASWS failed for {code}")
    except CircuitOpenError:
        raise
    except Exception:
        cb.record_failure()
        raise


def live_status_for(airport_code: str, **kwargs: Any) -> AirportLiveStatus:
    """Convenience overlay: ASWS first, NAS XML as a coarse fallback."""

    try:
        return fetch_asws_status(airport_code, **kwargs)
    except CircuitOpenError:
        raise
    except Exception:
        nas = fetch_nas_status(**kwargs)
        code = airport_code.strip().upper()
        hit = nas.get("airports", {}).get(code, {})
        return AirportLiveStatus(
            airport=code,
            source="faa_nas",
            fetched_at=datetime.now(timezone.utc).isoformat(),
            delay=bool(hit.get("programs")),
            status=hit.get("status") or nas.get("status"),
            reason=hit.get("reason"),
            programs=list(hit.get("programs") or []),
            raw={"nas": hit},
        )


def _parse_nas_xml(xml_text: str) -> dict[str, Any]:
    root = ET.fromstring(xml_text)
    airports: dict[str, dict[str, Any]] = {}
    for delay in root.iter():
        tag = delay.tag.split("}")[-1].lower()
        if "delay" in tag or tag in {"ground_stop", "ground_delay", "gdp", "gs"}:
            program = delay.tag.split("}")[-1]
            codes = [
                (el.text or "").strip().upper()
                for el in delay.iter()
                if el.tag.split("}")[-1].lower() in {"airport", "arpt", "airportcode", "airport_code"}
                and (el.text or "").strip()
            ]
            reason_el = next(
                (
                    el
                    for el in delay.iter()
                    if el.tag.split("}")[-1].lower() in {"reason", "end_time", "avg"}
                ),
                None,
            )
            for code in codes:
                bucket = airports.setdefault(
                    code, {"programs": [], "status": program, "reason": None}
                )
                if program not in bucket["programs"]:
                    bucket["programs"].append(program)
                if reason_el is not None and reason_el.text:
                    bucket["reason"] = (reason_el.text or "").strip()
    return {
        "source": "faa_nas",
        "url": FAA_NAS_STATUS_URL,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "airports": airports,
        "status": "ok",
    }


def _asws_to_status(code: str, payload: dict[str, Any]) -> AirportLiveStatus:
    delay = payload.get("delay")
    if isinstance(delay, str):
        delay_flag = delay.strip().lower() in {"true", "yes", "1"}
    else:
        delay_flag = bool(delay)
    status = payload.get("status") or payload.get("Name")
    if isinstance(status, dict):
        status = status.get("reason") or status.get("closureBegin") or str(status)
    weather = payload.get("weather") or {}
    reason = None
    if isinstance(weather, dict):
        reason = weather.get("weather") or weather.get("meta")
        if isinstance(reason, dict):
            reason = reason.get("weather") or str(reason)
    return AirportLiveStatus(
        airport=code,
        source="faa_asws",
        fetched_at=datetime.now(timezone.utc).isoformat(),
        delay=delay_flag,
        status=str(status) if status is not None else None,
        reason=str(reason) if reason is not None else None,
        programs=[],
        raw=payload,
    )


__all__ = [
    "AirportLiveStatus",
    "CircuitBreaker",
    "fetch_asws_status",
    "fetch_nas_status",
    "live_status_for",
]
