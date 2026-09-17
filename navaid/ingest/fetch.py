"""Fetch a source: live HTTP, then cache, then checked-in fixture."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from navaid.ingest.sources import SourceSpec
from navaid.net.client import CachedHttpClient
from navaid.net.errors import NavaidNetworkError, OfflineNetworkError
from navaid.warehouse.types import IngestSourceRecord


@dataclass
class FetchedFile:
    path: Path
    record: IngestSourceRecord
    body: bytes | None = None


def fetch_source(
    spec: SourceSpec,
    client: CachedHttpClient,
    *,
    refresh: bool = False,
    force_fixture: bool = False,
) -> FetchedFile:
    """Try each live URL; on failure (or force_fixture) use the checked-in fixture."""

    errors: list[str] = []
    if not force_fixture:
        for url in spec.urls:
            if url.lower().endswith(".asp") or "DL_SelectFields" in url or url.rstrip("/").endswith("passenger"):
                # HTML index pages are not the data file; skip raw GET of the portal.
                continue
            try:
                body, path = client.get_bytes(url, refresh=refresh)
                if _looks_like_html(body) or not _plausible_payload(url, body):
                    errors.append(f"{url}: HTML or invalid payload instead of data file")
                    continue
                if len(body) < 64:
                    errors.append(f"{url}: too small ({len(body)} bytes)")
                    continue
                return FetchedFile(
                    path=path,
                    body=body,
                    record=IngestSourceRecord(
                        source_id=spec.source_id,
                        url=url,
                        local_path=str(path),
                        as_of=spec.as_of,
                        confidence="high",
                        used_fixture=False,
                        notes=spec.notes,
                    ),
                )
            except (NavaidNetworkError, OSError, Exception) as exc:
                errors.append(f"{url}: {exc}")
                continue

    fixture = spec.fixture_path
    if fixture is not None and fixture.is_file():
        notes = spec.notes
        if errors:
            notes = f"{notes} Fell back to fixture. Live errors: {'; '.join(errors[:4])}"
        confidence = "medium" if errors or force_fixture else "high"
        # Offline with no attempt is still a disclosed fixture.
        if force_fixture or any("NAVAID_OFFLINE" in e for e in errors):
            confidence = "medium"
        return FetchedFile(
            path=fixture,
            body=fixture.read_bytes(),
            record=IngestSourceRecord(
                source_id=spec.source_id,
                url=spec.urls[0] if spec.urls else None,
                local_path=str(fixture),
                as_of=spec.as_of,
                confidence=confidence,
                used_fixture=True,
                notes=notes,
            ),
        )

    detail = "; ".join(errors) if errors else "no URLs and no fixture"
    raise FileNotFoundError(f"could not fetch {spec.source_id}: {detail}")


def _looks_like_html(body: bytes) -> bool:
    head = body[:400].lstrip().lower()
    return (
        head.startswith(b"<!doctype html")
        or head.startswith(b"<html")
        or head.startswith(b"<head")
        or b"<html" in head[:80]
    )


def _plausible_payload(url: str, body: bytes) -> bool:
    lower = url.lower()
    if lower.endswith(".xlsx") or lower.endswith(".zip"):
        return body[:2] == b"PK"
    if lower.endswith(".xls"):
        return body[:4] == b"\xd0\xcf\x11\xe0" or body[:2] == b"PK"
    return len(body) >= 64
