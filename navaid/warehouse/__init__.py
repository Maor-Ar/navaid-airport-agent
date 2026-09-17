"""DuckDB warehouse: schema, connection helpers, snapshot builder."""

from pathlib import Path

from navaid.warehouse.db import connect, init_schema
from navaid.warehouse.metrics import MetricsCatalog, SnapshotMissingError, require_snapshot
from navaid.warehouse.snapshot import build_snapshot
from navaid.warehouse.types import IngestSourceRecord, SnapshotBuildResult

SCHEMA_SQL_PATH = Path(__file__).resolve().parent / "schema.sql"


def schema_sql() -> str:
    """Return the warehouse DDL (metrics, sessions, doc_chunks; no embeddings)."""

    return SCHEMA_SQL_PATH.read_text(encoding="utf-8")


__all__ = [
    "SCHEMA_SQL_PATH",
    "IngestSourceRecord",
    "MetricsCatalog",
    "SnapshotBuildResult",
    "SnapshotMissingError",
    "build_snapshot",
    "connect",
    "init_schema",
    "require_snapshot",
    "schema_sql",
]
