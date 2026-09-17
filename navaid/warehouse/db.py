"""DuckDB connection, schema init, and table replace helpers."""

from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

import duckdb
import pandas as pd

from navaid.config import WAREHOUSE_DIR, WAREHOUSE_PATH
from navaid.warehouse.types import IngestSourceRecord

SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


def schema_sql() -> str:
    return SCHEMA_SQL_PATH.read_text(encoding="utf-8")

METRIC_TABLES = (
    "airports",
    "runways",
    "enplanements",
    "taf_forecasts",
    "t100_segments",
    "delay_cause",
    "airport_ops",
    "npias",
    "aip_grants",
    "gates",
    "catchment_cbsa",
    "constraints",
    "doc_chunks",
    "ingest_sources",
)


def connect(path: Path | str | None = None, *, read_only: bool = False) -> duckdb.DuckDBPyConnection:
    target = Path(path or WAREHOUSE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(target), read_only=read_only)


def init_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(schema_sql())


def replace_table(con: duckdb.DuckDBPyConnection, name: str, df: pd.DataFrame) -> int:
    """CREATE TABLE as a full replace of `name` from a pandas DataFrame."""

    con.execute(f"DROP TABLE IF EXISTS {name}")
    if df is None or df.empty:
        # Recreate empty table from DDL.
        init_schema(con)
        return 0
    con.register("_navaid_df", df)
    con.execute(f"CREATE TABLE {name} AS SELECT * FROM _navaid_df")
    con.unregister("_navaid_df")
    return int(len(df))


def write_ingest_sources(con: duckdb.DuckDBPyConnection, records: list[IngestSourceRecord]) -> None:
    rows = [r.model_dump() for r in records]
    df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["source_id", "url", "local_path", "as_of", "confidence", "used_fixture", "notes"]
    )
    replace_table(con, "ingest_sources", df)


def write_snapshot_meta(
    con: duckdb.DuckDBPyConnection,
    *,
    as_of: date,
    content_hash: str,
    notes: str,
) -> None:
    con.execute("DELETE FROM snapshot_meta")
    con.execute(
        "INSERT INTO snapshot_meta (as_of, content_hash, built_at, notes) VALUES (?, ?, ?, ?)",
        [as_of, content_hash, datetime.now(timezone.utc).replace(tzinfo=None), notes],
    )


def content_hash_for(tables: dict[str, pd.DataFrame]) -> str:
    hasher = hashlib.sha256()
    for name in sorted(tables):
        df = tables[name]
        hasher.update(name.encode("utf-8"))
        hasher.update(str(len(df)).encode("utf-8"))
        if df is None or df.empty:
            continue
        # Stable sample: sort by first few columns and hash CSV of up to 200 rows.
        cols = list(df.columns)
        sample = df.head(200).copy()
        try:
            sample = sample.sort_values(by=[c for c in cols[:3] if c in sample.columns])
        except Exception:
            pass
        hasher.update(sample.to_csv(index=False).encode("utf-8"))
    return hasher.hexdigest()


def row_counts(con: duckdb.DuckDBPyConnection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in METRIC_TABLES + ("snapshot_meta", "sessions"):
        try:
            counts[name] = int(con.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0])
        except duckdb.Error:
            continue
    return counts


def warehouse_dir() -> Path:
    WAREHOUSE_DIR.mkdir(parents=True, exist_ok=True)
    return WAREHOUSE_DIR
