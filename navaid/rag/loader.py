"""Parse curated markdown notes and load them into ``doc_chunks``."""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from datetime import date, datetime
from pathlib import Path

import duckdb

from navaid.config import PROJECT_ROOT
from navaid.rag.db import DbLike, ensure_doc_chunks, ensure_fts_index, open_db

CURATED_DIR = PROJECT_ROOT / "data" / "curated"
DEFAULT_NOTES_FILE = CURATED_DIR / "qualitative_notes.md"
NOTES_SUBDIR = CURATED_DIR / "notes"

_FRONT_SPLIT = re.compile(r"(?m)^---\s*$")
_IATA = re.compile(r"^[A-Z]{3}$")
_SLUG_KEEP = re.compile(r"[^a-z0-9]+")


def default_note_paths() -> list[Path]:
    """``qualitative_notes.md`` plus every ``*.md`` under ``data/curated/notes/``."""

    paths: list[Path] = []
    if DEFAULT_NOTES_FILE.is_file():
        paths.append(DEFAULT_NOTES_FILE)
    if NOTES_SUBDIR.is_dir():
        paths.extend(sorted(p for p in NOTES_SUBDIR.glob("*.md") if p.is_file()))
    return paths


def parse_note_markdown(text: str, *, source_path: str | Path | None = None) -> list[dict]:
    """Split a notes file into chunk dicts (one per airport after expansion).

    Format: optional preamble, then repeating::

        ---
        id: sfo-leakage
        airport: SFO
        doc_type: qualitative_note
        as_of: 2026-09-01
        url: https://example.invalid/sfo
        title: SFO leakage to OAK and SJC
        ---

        Body paragraphs...
    """

    parts = _FRONT_SPLIT.split(text)
    if len(parts) < 3:
        return []

    origin = str(source_path) if source_path else None
    chunks: list[dict] = []
    # [preamble, meta1, body1, meta2, body2, ...]
    i = 1
    while i + 1 < len(parts):
        meta = _parse_meta(parts[i])
        body = parts[i + 1].strip()
        i += 2
        if not meta or not body:
            continue
        airports = _airports_from_meta(meta)
        if not airports:
            continue
        doc_type = (meta.get("doc_type") or "qualitative_note").strip()
        as_of = _parse_as_of(meta.get("as_of"))
        url = (meta.get("url") or "").strip() or None
        title = (meta.get("title") or "").strip()
        base_id = (meta.get("id") or "").strip() or _slug(title) or _slug(body[:48])
        if not base_id:
            continue
        multi = len(airports) > 1
        for code in airports:
            chunk_id = f"{base_id}::{code}" if multi else base_id
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "airport": code,
                    "doc_type": doc_type,
                    "as_of": as_of,
                    "url": url,
                    "title": title,
                    "body": body,
                    "source_path": origin,
                }
            )
    return chunks


def load_notes(
    db: DbLike = None,
    *,
    paths: Sequence[str | Path] | None = None,
    recreate_fts: bool = True,
    replace: bool = True,
) -> int:
    """Ingest markdown notes into ``doc_chunks``. Returns rows upserted.

    ``db`` may be an open DuckDB connection, a file path, ``':memory:'``,
    or None (``navaid.config.WAREHOUSE_PATH``).
    """

    files = [Path(p) for p in paths] if paths is not None else default_note_paths()
    records: list[dict] = []
    for path in files:
        if not path.is_file():
            continue
        records.extend(parse_note_markdown(path.read_text(encoding="utf-8"), source_path=path))

    with open_db(db) as con:
        ensure_doc_chunks(con)
        if replace:
            con.execute("DELETE FROM doc_chunks")
        inserted = _upsert_chunks(con, records)
        if recreate_fts:
            ensure_fts_index(con, overwrite=True)
        return inserted


def _upsert_chunks(con: duckdb.DuckDBPyConnection, records: Iterable[dict]) -> int:
    rows = list(records)
    if not rows:
        return 0
    con.executemany(
        """
        INSERT OR REPLACE INTO doc_chunks
            (chunk_id, airport, doc_type, as_of, url, title, body)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                r["chunk_id"],
                r["airport"],
                r["doc_type"],
                r["as_of"],
                r["url"],
                r["title"],
                r["body"],
            )
            for r in rows
        ],
    )
    return len(rows)


def _parse_meta(block: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip().lower()] = value.strip().strip('"').strip("'")
    return meta


def _airports_from_meta(meta: dict[str, str]) -> list[str]:
    raw = meta.get("airport") or meta.get("airports") or ""
    raw = raw.replace("[", " ").replace("]", " ")
    codes: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[,\s]+", raw):
        code = token.strip().upper()
        if _IATA.match(code) and code not in seen:
            seen.add(code)
            codes.append(code)
    return codes


def _parse_as_of(value: str | None) -> date | None:
    if not value:
        return None
    text = value.strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        try:
            return datetime.fromisoformat(text).date()
        except ValueError:
            return None


def _slug(text: str) -> str:
    slug = _SLUG_KEEP.sub("-", text.strip().lower()).strip("-")
    return slug[:80]


__all__ = [
    "CURATED_DIR",
    "DEFAULT_NOTES_FILE",
    "NOTES_SUBDIR",
    "default_note_paths",
    "load_notes",
    "parse_note_markdown",
]
