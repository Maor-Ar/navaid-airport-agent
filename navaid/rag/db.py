"""DuckDB connection, doc_chunks DDL, and FTS index helpers.

Warehouse may not expose a connection helper yet, so every public RAG function
accepts a DuckDB connection, a file path, or None (``config.WAREHOUSE_PATH``).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb

from navaid.config import WAREHOUSE_PATH

DOC_CHUNKS_DDL = """
CREATE TABLE IF NOT EXISTS doc_chunks (
    chunk_id TEXT PRIMARY KEY,
    airport TEXT,
    doc_type TEXT,
    as_of DATE,
    url TEXT,
    title TEXT,
    body TEXT
)
"""

DbLike = duckdb.DuckDBPyConnection | str | Path | None


@contextmanager
def open_db(db: DbLike = None) -> Iterator[duckdb.DuckDBPyConnection]:
    """Yield a DuckDB connection. Closes only connections this helper opened."""

    if isinstance(db, duckdb.DuckDBPyConnection):
        yield db
        return

    path: str | Path
    if db is None:
        path = WAREHOUSE_PATH
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    else:
        path = db
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)

    con = duckdb.connect(str(path))
    try:
        yield con
    finally:
        con.close()


def ensure_doc_chunks(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(DOC_CHUNKS_DDL)


def load_fts_extension(con: duckdb.DuckDBPyConnection) -> bool:
    """LOAD (then INSTALL) the DuckDB FTS extension. Returns False if unavailable."""

    try:
        con.execute("LOAD fts")
        return True
    except Exception:
        pass
    try:
        con.execute("INSTALL fts")
        con.execute("LOAD fts")
        return True
    except Exception:
        return False


def fts_index_ready(con: duckdb.DuckDBPyConnection) -> bool:
    try:
        con.execute("SELECT fts_main_doc_chunks.match_bm25(?, ?)", ["__probe__", "probe"])
        return True
    except Exception:
        return False


def ensure_fts_index(con: duckdb.DuckDBPyConnection, *, overwrite: bool = False) -> bool:
    """Create ``fts_main_doc_chunks`` over body + title. Returns False without FTS."""

    ensure_doc_chunks(con)
    if not load_fts_extension(con):
        return False
    if fts_index_ready(con) and not overwrite:
        return True
    try:
        con.execute(
            "PRAGMA create_fts_index("
            "'doc_chunks', 'chunk_id', 'body', 'title', "
            "stemmer='porter', stopwords='english', overwrite=1"
            ")"
        )
        return fts_index_ready(con)
    except Exception:
        return False


__all__ = [
    "DOC_CHUNKS_DDL",
    "DbLike",
    "ensure_doc_chunks",
    "ensure_fts_index",
    "fts_index_ready",
    "load_fts_extension",
    "open_db",
]
