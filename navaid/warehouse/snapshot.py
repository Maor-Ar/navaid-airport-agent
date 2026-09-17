"""Build the local DuckDB snapshot from public files + fixtures + curated CSVs."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd

from navaid.config import DEEP_SLICE_IATA, NAVAID_OFFLINE, WAREHOUSE_PATH
from navaid.ingest.bts import airport_ops_from_t100, parse_delay_cause, parse_t100_segments
from navaid.ingest.curated import load_catchment, load_constraints, load_gates, load_notes_as_chunks
from navaid.ingest.faa import parse_enplanements, parse_npias, parse_taf
from navaid.ingest.fetch import fetch_source
from navaid.ingest.ourairports import parse_airports, parse_runways
from navaid.ingest.sources import (
    BTS_DELAY_CAUSE,
    BTS_T100_SEGMENT,
    FAA_ENPLANEMENTS,
    FAA_ENPLANEMENTS_FULL,
    FAA_TAF,
    NPIAS_APPENDIX_A,
    OURAIRPORTS_AIRPORTS,
    OURAIRPORTS_RUNWAYS,
)
from navaid.ingest.util import CURATED_DIR, FIXTURES_DIR, ensure_dirs
from navaid.net.client import CachedHttpClient
from navaid.net.errors import NavaidNetworkError
from navaid.warehouse.db import (
    connect,
    content_hash_for,
    init_schema,
    replace_table,
    row_counts,
    write_ingest_sources,
    write_snapshot_meta,
)
from navaid.warehouse.types import IngestSourceRecord, SnapshotBuildResult

PRIMARY_MIN_ENPLANEMENTS = 10_000


def build_snapshot(
    *,
    warehouse_path: Path | str | None = None,
    offline: bool | None = None,
    force_fixtures: bool = False,
    refresh: bool = False,
    as_of: date | None = None,
) -> SnapshotBuildResult:
    """Download/parse sources, write `data/warehouse/navaid.duckdb`."""

    ensure_dirs()
    as_of = as_of or date(2024, 12, 31)
    offline_flag = NAVAID_OFFLINE if offline is None else offline
    force = force_fixtures or offline_flag
    client = CachedHttpClient(offline=offline_flag)
    target = Path(warehouse_path or WAREHOUSE_PATH)
    records: list[IngestSourceRecord] = []

    airports, rec = _load_airports(client, force=force, refresh=refresh, as_of=as_of)
    records.append(rec)
    runways, rec = _load_runways(
        client, force=force, refresh=refresh, icaos=set(airports["icao"].dropna().astype(str))
    )
    records.append(rec)

    enplanements, recs = _load_enplanements(client, force=force, refresh=refresh, as_of=as_of)
    records.extend(recs)

    iata_to_icao = _iata_icao_map(airports)
    enplanements = _fill_icao(enplanements, iata_to_icao)

    universe = _universe_iata(enplanements)
    airports = _filter_airports_to_universe(airports, universe)
    runways = runways[runways["icao"].isin(set(airports["icao"]))] if not runways.empty else runways
    enplanements = enplanements[enplanements["iata"].isin(universe)].reset_index(drop=True)

    t100, rec = _load_t100(
        client, force=force, refresh=refresh, as_of=as_of, universe=universe
    )
    records.append(rec)
    delay, rec = _load_delay(client, force=force, refresh=refresh, as_of=as_of, universe=universe)
    records.append(rec)
    delay = _fill_icao(delay, iata_to_icao)

    taf, rec = _load_taf(client, force=force, refresh=refresh, as_of=as_of)
    records.append(rec)
    taf = _fill_icao(taf, iata_to_icao)
    if not taf.empty:
        taf = taf[taf["iata"].isin(universe)].reset_index(drop=True)

    npias, rec = _load_npias(client, force=force, refresh=refresh, as_of=as_of)
    records.append(rec)
    npias = _fill_icao(npias, iata_to_icao)
    if not npias.empty:
        npias = npias[npias["iata"].isin(universe)].reset_index(drop=True)

    gates = _fill_icao(load_gates(), iata_to_icao)
    catchment = _fill_icao(load_catchment(), iata_to_icao)
    constraints = _fill_icao(load_constraints(), iata_to_icao)
    chunks = load_notes_as_chunks()
    records.append(
        IngestSourceRecord(
            source_id="curated_gates_catchment_constraints",
            url=None,
            local_path=str(CURATED_DIR),
            as_of=as_of,
            confidence="high",
            used_fixture=False,
            notes="Hand-authored gates, SFO-OAK-SJC / LAX-SNA catchments, constraint types.",
        )
    )

    ops = _airport_ops(delay, t100, as_of=as_of)
    ops = _fill_icao(ops, iata_to_icao)

    aip = pd.DataFrame(columns=["iata", "icao", "year", "amount_usd", "description", "as_of"])

    tables = {
        "airports": airports,
        "runways": runways,
        "enplanements": enplanements,
        "taf_forecasts": taf,
        "t100_segments": t100,
        "delay_cause": delay,
        "airport_ops": ops,
        "npias": npias,
        "aip_grants": aip,
        "gates": gates,
        "catchment_cbsa": catchment,
        "constraints": constraints,
        "doc_chunks": chunks,
    }
    digest = content_hash_for(tables)
    used_fixtures = [r.source_id for r in records if r.used_fixture]
    notes = {
        "used_fixtures": used_fixtures,
        "offline": offline_flag,
        "force_fixtures": force,
        "universe_size": len(universe),
        "deep_slice": list(DEEP_SLICE_IATA),
        "live_faa_status": "not a snapshot input; circuit-broken overlay at tool time",
    }

    con = connect(target)
    try:
        init_schema(con)
        for name, df in tables.items():
            replace_table(con, name, df)
        write_ingest_sources(con, records)
        write_snapshot_meta(con, as_of=as_of, content_hash=digest, notes=json.dumps(notes))
        counts = row_counts(con)
    finally:
        con.close()

    _write_demo_extract(t100, target.parent)

    return SnapshotBuildResult(
        warehouse_path=str(target),
        as_of=as_of,
        content_hash=digest,
        used_fixtures=used_fixtures,
        sources=records,
        row_counts=counts,
        notes=json.dumps(notes),
    )


def _load_airports(client, *, force: bool, refresh: bool, as_of: date):
    fetched = fetch_source(OURAIRPORTS_AIRPORTS, client, refresh=refresh, force_fixture=force)
    df = parse_airports(fetched.path, as_of=fetched.record.as_of or as_of)
    return df, fetched.record


def _load_runways(client, *, force: bool, refresh: bool, icaos: set[str]):
    fetched = fetch_source(OURAIRPORTS_RUNWAYS, client, refresh=refresh, force_fixture=force)
    df = parse_runways(fetched.path, airport_icaos=icaos or None)
    return df, fetched.record


def _load_enplanements(client, *, force: bool, refresh: bool, as_of: date):
    records: list[IngestSourceRecord] = []
    try:
        fetched = fetch_source(FAA_ENPLANEMENTS, client, refresh=refresh, force_fixture=force)
        try:
            df = parse_enplanements(fetched.path, as_of=fetched.record.as_of)
        except (ValueError, OSError, Exception):
            df = pd.DataFrame()
            fetched.record.used_fixture = True
            fetched.record.confidence = "medium"
            fetched.record.notes = (fetched.record.notes or "") + " Live parse failed; using CY2024 extract."
        records.append(fetched.record)
        # Tiny parser fixture has only a handful of rows; prefer the full CY extract for the warehouse.
        full_path = FAA_ENPLANEMENTS_FULL.fixture_path
        if full_path is not None and full_path.is_file() and (fetched.record.used_fixture or len(df) < 50):
            full = parse_enplanements(full_path, as_of=FAA_ENPLANEMENTS_FULL.as_of)
            if len(full) > len(df):
                df = full
                records.append(
                    IngestSourceRecord(
                        source_id=FAA_ENPLANEMENTS_FULL.source_id,
                        url="https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger/arp-cy2024-commercial-service-enplanements.pdf",
                        local_path=str(full_path),
                        as_of=FAA_ENPLANEMENTS_FULL.as_of,
                        confidence="medium",
                        used_fixture=True,
                        notes=FAA_ENPLANEMENTS_FULL.notes,
                    )
                )
        return df, records
    except (FileNotFoundError, ValueError, NavaidNetworkError):
        full_path = FAA_ENPLANEMENTS_FULL.fixture_path
        if full_path is not None and full_path.is_file():
            df = parse_enplanements(full_path, as_of=FAA_ENPLANEMENTS_FULL.as_of)
            records.append(
                IngestSourceRecord(
                    source_id=FAA_ENPLANEMENTS_FULL.source_id,
                    url=None,
                    local_path=str(full_path),
                    as_of=FAA_ENPLANEMENTS_FULL.as_of,
                    confidence="medium",
                    used_fixture=True,
                    notes=FAA_ENPLANEMENTS_FULL.notes,
                )
            )
            return df, records
        raise


def _load_t100(client, *, force: bool, refresh: bool, as_of: date, universe: set[str]):
    fetched = fetch_source(BTS_T100_SEGMENT, client, refresh=refresh, force_fixture=force)
    try:
        df = parse_t100_segments(fetched.path, as_of=fetched.record.as_of, universe_iata=universe)
    except (ValueError, OSError, Exception):
        df = pd.DataFrame()
    if df.empty:
        fallback = fetch_source(BTS_T100_SEGMENT, client, force_fixture=True)
        df = parse_t100_segments(fallback.path, as_of=fallback.record.as_of, universe_iata=universe)
        fallback.record.notes = (
            (fallback.record.notes or "")
            + " Live T-100 missing, unreadable, or empty after universe filter; using fixture extract."
        )
        fallback.record.used_fixture = True
        fallback.record.confidence = "medium"
        return df, fallback.record
    return df, fetched.record


def _load_delay(client, *, force: bool, refresh: bool, as_of: date, universe: set[str]):
    fetched = fetch_source(BTS_DELAY_CAUSE, client, refresh=refresh, force_fixture=force)
    df = parse_delay_cause(fetched.path, as_of=fetched.record.as_of, universe_iata=universe)
    return df, fetched.record


def _load_taf(client, *, force: bool, refresh: bool, as_of: date):
    df = pd.DataFrame(columns=["iata", "icao", "forecast_year", "passengers", "operations", "as_of"])
    rec: IngestSourceRecord | None = None
    try:
        fetched = fetch_source(FAA_TAF, client, refresh=refresh, force_fixture=force)
        parsed = parse_taf(fetched.path, as_of=fetched.record.as_of)
        if not parsed.empty:
            df = parsed
            rec = fetched.record
    except (FileNotFoundError, ValueError, NavaidNetworkError, OSError, Exception):
        rec = None

    curated = CURATED_DIR / "taf_deep_slice.csv"
    if curated.is_file():
        extra = parse_taf(curated, as_of=date(2025, 3, 1))
        if df.empty:
            df = extra
        else:
            df = pd.concat([df, extra], ignore_index=True).drop_duplicates(
                subset=["iata", "forecast_year"], keep="first"
            )
        if rec is None or rec.used_fixture:
            rec = IngestSourceRecord(
                source_id="faa_taf",
                url="https://taf.faa.gov/",
                local_path=str(curated),
                as_of=date(2025, 3, 1),
                confidence="low",
                used_fixture=True,
                notes="FAA TAF bulk file not obtained; curated deep-slice 2025/2035 forecasts, disclosed.",
            )
    if rec is None:
        rec = IngestSourceRecord(
            source_id="faa_taf",
            url="https://taf.faa.gov/",
            local_path=None,
            as_of=date(2025, 3, 1),
            confidence="low",
            used_fixture=True,
            notes="FAA TAF bulk file not obtained.",
        )
    return df, rec


def _load_npias(client, *, force: bool, refresh: bool, as_of: date):
    try:
        fetched = fetch_source(NPIAS_APPENDIX_A, client, refresh=refresh, force_fixture=force)
        df = parse_npias(fetched.path, as_of=fetched.record.as_of)
        if not df.empty:
            return df, fetched.record
    except (FileNotFoundError, ValueError, NavaidNetworkError, OSError, Exception):
        pass
    path = FIXTURES_DIR / "npias.csv"
    df = parse_npias(path, as_of=date(2024, 10, 28)) if path.is_file() else pd.DataFrame(
        columns=["iata", "icao", "development_need", "as_of"]
    )
    rec = IngestSourceRecord(
        source_id="npias_appendix_a",
        url="https://www.faa.gov/airports/planning_capacity/npias/current",
        local_path=str(path) if path.is_file() else None,
        as_of=date(2024, 10, 28),
        confidence="low",
        used_fixture=True,
        notes="NPIAS Appendix A workbook not obtained; fixture/qualitative development need, disclosed.",
    )
    return df, rec


def _universe_iata(enplanements: pd.DataFrame) -> set[str]:
    primary = set()
    if not enplanements.empty:
        mask = enplanements["enplanements"].fillna(0) >= PRIMARY_MIN_ENPLANEMENTS
        primary = set(enplanements.loc[mask, "iata"].astype(str).str.upper())
        if "hub_size" in enplanements.columns:
            hubs = enplanements["hub_size"].astype(str).str.lower()
            primary |= set(
                enplanements.loc[hubs.isin({"large", "medium", "small", "non-hub"}), "iata"]
                .astype(str)
                .str.upper()
            )
    primary |= set(DEEP_SLICE_IATA)
    return {c for c in primary if len(c) == 3}


def _filter_airports_to_universe(airports: pd.DataFrame, universe: set[str]) -> pd.DataFrame:
    if airports.empty:
        return airports
    keep = airports["iata"].isin(universe)
    # Keep ICAO rows that map to universe even if iata join missed.
    return airports.loc[keep].drop_duplicates(subset=["icao"]).reset_index(drop=True)


def _iata_icao_map(airports: pd.DataFrame) -> dict[str, str]:
    if airports.empty:
        return {}
    sub = airports.dropna(subset=["iata", "icao"])
    return dict(zip(sub["iata"].astype(str).str.upper(), sub["icao"].astype(str).str.upper()))


def _fill_icao(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    if df is None or df.empty or "iata" not in df.columns:
        return df
    out = df.copy()
    if "icao" not in out.columns:
        out["icao"] = pd.NA
    missing = out["icao"].isna() | (out["icao"].astype(str).str.strip().isin({"", "NAN", "<NA>"}))
    out.loc[missing, "icao"] = out.loc[missing, "iata"].astype(str).str.upper().map(mapping)
    return out


def _airport_ops(delay: pd.DataFrame, t100: pd.DataFrame, *, as_of: date) -> pd.DataFrame:
    if delay is not None and not delay.empty:
        yearly = (
            delay.groupby(["iata", "year"], dropna=False)["operations"]
            .sum()
            .reset_index()
        )
        yearly["icao"] = pd.NA
        yearly["as_of"] = as_of
        yearly["operations"] = yearly["operations"].astype("Int64")
        return yearly[["iata", "icao", "year", "operations", "as_of"]]
    return airport_ops_from_t100(t100, as_of=as_of)


def _write_demo_extract(t100: pd.DataFrame, dest_dir: Path) -> None:
    """If the filtered T-100 is small, keep a CSV extract next to the DuckDB file."""

    if t100 is None or t100.empty:
        return
    deep = set(DEEP_SLICE_IATA)
    slice_df = t100[t100["origin"].isin(deep) | t100["dest"].isin(deep)]
    if slice_df.empty or len(slice_df) > 5000:
        return
    dest_dir.mkdir(parents=True, exist_ok=True)
    slice_df.to_csv(dest_dir / "t100_deep_slice.csv", index=False)
