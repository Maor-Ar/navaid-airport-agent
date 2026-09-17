from __future__ import annotations

from pathlib import Path

from navaid.config import DEEP_SLICE_IATA
from navaid.warehouse.snapshot import build_snapshot
from navaid.warehouse import schema_sql


def test_schema_has_ingest_sources_and_no_embeddings() -> None:
    sql = schema_sql()
    assert "CREATE TABLE IF NOT EXISTS ingest_sources" in sql
    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS embeddings" not in sql


def test_build_snapshot_from_fixtures(tmp_path: Path) -> None:
    dest = tmp_path / "navaid.duckdb"
    result = build_snapshot(
        warehouse_path=dest,
        offline=True,
        force_fixtures=True,
    )
    assert dest.is_file()
    assert result.used_fixtures
    counts = result.row_counts
    assert counts["airports"] >= len(DEEP_SLICE_IATA)
    assert counts["enplanements"] >= len(DEEP_SLICE_IATA)
    assert counts["t100_segments"] > 0
    assert counts["delay_cause"] > 0
    assert counts["gates"] >= len(DEEP_SLICE_IATA)
    assert counts["constraints"] >= len(DEEP_SLICE_IATA)
    assert counts["catchment_cbsa"] >= 5
    assert counts["snapshot_meta"] == 1

    import duckdb

    con = duckdb.connect(str(dest), read_only=True)
    iatas = {r[0] for r in con.execute("SELECT iata FROM airports").fetchall()}
    assert set(DEEP_SLICE_IATA).issubset(iatas)
    sna_curfew = con.execute(
        "SELECT curfew FROM constraints WHERE iata = 'SNA'"
    ).fetchone()[0]
    assert sna_curfew and "22:00" in sna_curfew
    anc_jfk = con.execute(
        "SELECT distance_km, passengers FROM t100_segments WHERE origin='ANC' AND dest='JFK'"
    ).fetchone()
    assert anc_jfk is not None
    assert anc_jfk[0] > 5000  # km
    sources = con.execute(
        "SELECT source_id, used_fixture, confidence FROM ingest_sources"
    ).fetchall()
    assert sources
    con.close()
