"""Airport-keyed corpus search via DuckDB FTS (BM25) and/or ``WHERE airport = ?``.

RAG returns text chunks and sources. It never returns a rank or a TEOI.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import duckdb

from navaid.rag.db import DbLike, ensure_doc_chunks, ensure_fts_index, open_db
from navaid.rag.types import RetrievedChunk

_IATA = re.compile(r"^[A-Za-z]{3}$")
_NON_TERM = re.compile(r"[^\w\s-]+", re.UNICODE)
_TERM = re.compile(r"[A-Za-z0-9]{3,}")


def search_corpus(
    query: str,
    airport: str | None = None,
    *,
    db: DbLike = None,
    limit: int = 10,
) -> list[RetrievedChunk]:
    """Retrieve note chunks for ``query``, optionally restricted to one IATA.

    * ``airport`` set, ``query`` empty → all chunks for that airport.
    * ``query`` set, ``airport`` empty → DuckDB FTS over the whole corpus.
    * both set → FTS inside ``WHERE airport = ?``; if FTS misses, airport
      chunks are still returned (keyword + IATA filter is an and/or).
    * neither set → empty list.

    ``db`` is a DuckDB connection, a path, ``':memory:'``, or None (warehouse file).
    """

    if limit < 1:
        return []
    airport_iata = _normalize_airport(airport)
    fts_query = _fts_query(query)
    if not fts_query and not airport_iata:
        return []

    with open_db(db) as con:
        ensure_doc_chunks(con)
        hits: list[RetrievedChunk] = []
        if fts_query:
            if ensure_fts_index(con, overwrite=False):
                hits = _search_fts(con, fts_query, airport_iata, limit)
            if not hits:
                hits = _search_like(con, fts_query, airport_iata, limit)
        if not hits and airport_iata:
            hits = _airport_only(con, airport_iata, limit)
        return hits


def _normalize_airport(airport: str | None) -> str | None:
    if airport is None:
        return None
    code = airport.strip().upper()
    if not code:
        return None
    if not _IATA.match(code):
        return code
    return code


def _fts_query(query: str | None) -> str:
    if not query:
        return ""
    cleaned = _NON_TERM.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _search_fts(
    con: duckdb.DuckDBPyConnection,
    query: str,
    airport: str | None,
    limit: int,
) -> list[RetrievedChunk]:
    if airport:
        sql = """
            SELECT chunk_id, airport, doc_type, as_of, url, title, body, fts_score
            FROM (
                SELECT
                    chunk_id, airport, doc_type, as_of, url, title, body,
                    fts_main_doc_chunks.match_bm25(chunk_id, ?) AS fts_score
                FROM doc_chunks
                WHERE airport = ?
            ) t
            WHERE fts_score IS NOT NULL
            ORDER BY fts_score DESC, chunk_id
            LIMIT ?
        """
        rows = con.execute(sql, [query, airport, limit]).fetchall()
    else:
        sql = """
            SELECT chunk_id, airport, doc_type, as_of, url, title, body, fts_score
            FROM (
                SELECT
                    chunk_id, airport, doc_type, as_of, url, title, body,
                    fts_main_doc_chunks.match_bm25(chunk_id, ?) AS fts_score
                FROM doc_chunks
            ) t
            WHERE fts_score IS NOT NULL
            ORDER BY fts_score DESC, chunk_id
            LIMIT ?
        """
        rows = con.execute(sql, [query, limit]).fetchall()
    return [_row_to_chunk(row) for row in rows]


def _search_like(
    con: duckdb.DuckDBPyConnection,
    query: str,
    airport: str | None,
    limit: int,
) -> list[RetrievedChunk]:
    """ILIKE fallback when the FTS extension is missing or BM25 misses."""

    terms = _TERM.findall(query.lower())
    if not terms:
        return []
    clauses = ["(lower(coalesce(body, '')) LIKE ? OR lower(coalesce(title, '')) LIKE ?)"] * len(
        terms
    )
    # Any-term match (OR), same spirit as BM25 bag-of-words.
    where = " OR ".join(clauses)
    params: list[object] = []
    for term in terms:
        like = f"%{term}%"
        params.extend([like, like])
    if airport:
        sql = f"""
            SELECT chunk_id, airport, doc_type, as_of, url, title, body, NULL AS fts_score
            FROM doc_chunks
            WHERE airport = ? AND ({where})
            ORDER BY title, chunk_id
            LIMIT ?
        """
        params = [airport, *params, limit]
    else:
        sql = f"""
            SELECT chunk_id, airport, doc_type, as_of, url, title, body, NULL AS fts_score
            FROM doc_chunks
            WHERE {where}
            ORDER BY title, chunk_id
            LIMIT ?
        """
        params = [*params, limit]
    rows = con.execute(sql, params).fetchall()
    return [_row_to_chunk(row) for row in rows]


def _airport_only(
    con: duckdb.DuckDBPyConnection,
    airport: str,
    limit: int,
) -> list[RetrievedChunk]:
    rows = con.execute(
        """
        SELECT chunk_id, airport, doc_type, as_of, url, title, body, NULL AS fts_score
        FROM doc_chunks
        WHERE airport = ?
        ORDER BY title, chunk_id
        LIMIT ?
        """,
        [airport, limit],
    ).fetchall()
    return [_row_to_chunk(row) for row in rows]


def _row_to_chunk(row: tuple) -> RetrievedChunk:
    chunk_id, airport, doc_type, as_of, url, title, body, fts_score = row
    return RetrievedChunk(
        chunk_id=str(chunk_id),
        body=body or "",
        airport=(str(airport).upper() if airport else None),
        doc_type=doc_type or "qualitative_note",
        as_of=_as_date(as_of),
        url=url,
        title=title or "",
        fts_score=float(fts_score) if fts_score is not None else None,
    )


def _as_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


__all__ = ["search_corpus"]
