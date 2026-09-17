"""BTS T-100 segment (stream/filter) and airport-month delay-cause."""

from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pandas as pd

from navaid.ingest.util import (
    MILES_TO_KM,
    as_iata,
    first_present,
    normalize_columns,
    parse_float,
    parse_int,
    require_column,
)

PASSENGER_CLASSES = frozenset({"F", "A", "C", "E"})  # scheduled / passenger service classes


def parse_t100_segments(
    path: Path | str,
    *,
    as_of: date,
    universe_iata: set[str] | None = None,
    chunksize: int = 100_000,
) -> pd.DataFrame:
    """Parse T-100 Segment CSV or ZIP. Filter to universe while streaming.

    Aggregates carriers/aircraft/class to origin-dest-year-month.
    Distance is converted miles → km. International = origin country ≠ dest country.
    """

    path = Path(path)
    frames: list[pd.DataFrame] = []
    for chunk in _iter_t100_chunks(path, chunksize=chunksize):
        frames.append(_normalize_t100_chunk(chunk, as_of=as_of, universe_iata=universe_iata))
    if not frames:
        return _empty_t100()
    out = pd.concat(frames, ignore_index=True)
    grouped = (
        out.groupby(["origin", "dest", "year", "month", "international", "as_of"], dropna=False)
        .agg(
            passengers=("passengers", "sum"),
            seats=("seats", "sum"),
            distance_km=("distance_km", "median"),
        )
        .reset_index()
    )
    grouped["passengers"] = grouped["passengers"].astype("Int64")
    grouped["seats"] = grouped["seats"].astype("Int64")
    grouped["international"] = grouped["international"].astype(bool)
    return grouped


def parse_delay_cause(
    path: Path | str,
    *,
    as_of: date,
    universe_iata: set[str] | None = None,
) -> pd.DataFrame:
    """Parse BTS airline delay-cause (airport × month, possibly × carrier) CSV."""

    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = normalize_columns(df)
    airport = require_column(df, "airport", "iata", "airport_code", "locid")
    icao_col = first_present(df, "icao")
    year_col = require_column(df, "year", "yy")
    month_col = require_column(df, "month", "mm")

    flights = first_present(df, "arr_flights", "arrivals", "operations", "flights")
    delayed = first_present(df, "arr_del15", "delayed_flights", "arr_delay_count")
    cancelled = first_present(df, "arr_cancelled", "cancelled", "cancels")
    delay_min = first_present(df, "arr_delay", "arr_delay_min", "delay_minutes", "total_delay")
    delay_pct_col = first_present(df, "delay_pct", "pct_delayed")
    cancel_pct_col = first_present(df, "cancel_pct", "pct_cancelled")
    avg_col = first_present(df, "avg_arrival_delay_min", "avg_delay", "avg_arr_delay")

    raw = pd.DataFrame(
        {
            "iata": as_iata(df[airport]),
            "icao": as_iata(df[icao_col]) if icao_col else pd.NA,
            "year": parse_int(df[year_col]),
            "month": parse_int(df[month_col]),
            "arr_flights": parse_float(df[flights]) if flights else pd.NA,
            "arr_del15": parse_float(df[delayed]) if delayed else pd.NA,
            "arr_cancelled": parse_float(df[cancelled]) if cancelled else pd.NA,
            "arr_delay": parse_float(df[delay_min]) if delay_min else pd.NA,
            "delay_pct": parse_float(df[delay_pct_col]) if delay_pct_col else pd.NA,
            "cancel_pct": parse_float(df[cancel_pct_col]) if cancel_pct_col else pd.NA,
            "avg_arrival_delay_min": parse_float(df[avg_col]) if avg_col else pd.NA,
        }
    )
    raw = raw[raw["iata"].str.len() == 3]
    if universe_iata is not None:
        raw = raw[raw["iata"].isin(universe_iata)]

    grouped = (
        raw.groupby(["iata", "year", "month"], dropna=False)
        .agg(
            icao=("icao", "first"),
            arr_flights=("arr_flights", "sum"),
            arr_del15=("arr_del15", "sum"),
            arr_cancelled=("arr_cancelled", "sum"),
            arr_delay=("arr_delay", "sum"),
            delay_pct=("delay_pct", "mean"),
            cancel_pct=("cancel_pct", "mean"),
            avg_arrival_delay_min=("avg_arrival_delay_min", "mean"),
        )
        .reset_index()
    )

    flights_safe = grouped["arr_flights"].astype("Float64").mask(grouped["arr_flights"].fillna(0) == 0)
    delay_from_counts = grouped["arr_del15"].astype("Float64") / flights_safe
    cancel_from_counts = grouped["arr_cancelled"].astype("Float64") / flights_safe
    avg_from_counts = grouped["arr_delay"].astype("Float64") / flights_safe
    grouped["delay_pct"] = grouped["delay_pct"].astype("Float64").fillna(delay_from_counts)
    grouped["cancel_pct"] = grouped["cancel_pct"].astype("Float64").fillna(cancel_from_counts)
    grouped["avg_arrival_delay_min"] = grouped["avg_arrival_delay_min"].astype("Float64").fillna(
        avg_from_counts
    )
    # If sheet stored percents as 12.3 meaning 12.3%, scale down.
    grouped["delay_pct"] = grouped["delay_pct"].where(grouped["delay_pct"].abs() <= 1.5, grouped["delay_pct"] / 100.0)
    grouped["cancel_pct"] = grouped["cancel_pct"].where(grouped["cancel_pct"].abs() <= 1.5, grouped["cancel_pct"] / 100.0)

    out = pd.DataFrame(
        {
            "iata": grouped["iata"],
            "icao": grouped["icao"],
            "year": grouped["year"].astype("Int64"),
            "month": grouped["month"].astype("Int64"),
            "delay_pct": grouped["delay_pct"].astype("Float64"),
            "avg_arrival_delay_min": grouped["avg_arrival_delay_min"].astype("Float64"),
            "cancel_pct": grouped["cancel_pct"].astype("Float64"),
            "operations": grouped["arr_flights"].round().astype("Int64"),
            "as_of": as_of,
        }
    )
    return out.reset_index(drop=True)


def airport_ops_from_t100(t100: pd.DataFrame, *, as_of: date) -> pd.DataFrame:
    """Departures approximated as rows of T-100; engines can also use delay-cause ops."""

    if t100.empty:
        return pd.DataFrame(columns=["iata", "icao", "year", "operations", "as_of"])
    orig = t100.groupby(["origin", "year"], dropna=False)["passengers"].size().reset_index(name="segment_rows")
    # Prefer delay-cause operations when present; this is a coarse fallback:
    # use passenger-weighted segment count is wrong. Sum seats as a proxy is worse.
    # Leave airport_ops to delay-cause / TAF. Here: unique origin-year with 0 ops
    # only if we later join. Instead, skip inventing ops from T-100 without
    # DEPARTURES_PERFORMED. Return empty unless a departures column was kept.
    if "departures" in t100.columns:
        ops = (
            t100.groupby(["origin", "year"], dropna=False)["departures"]
            .sum()
            .reset_index()
            .rename(columns={"origin": "iata", "departures": "operations"})
        )
        ops["icao"] = pd.NA
        ops["as_of"] = as_of
        ops["operations"] = ops["operations"].round().astype("Int64")
        return ops[["iata", "icao", "year", "operations", "as_of"]]
    return pd.DataFrame(columns=["iata", "icao", "year", "operations", "as_of"])


def _iter_t100_chunks(path: Path, chunksize: int):
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".csv") and not n.startswith("__")]
            if not names:
                return
            with zf.open(names[0]) as handle:
                # latin-1: BTS files often include airline names with high bytes.
                text = io.TextIOWrapper(handle, encoding="latin-1")
                yield from pd.read_csv(text, dtype=str, chunksize=chunksize, low_memory=False)
        return
    yield from pd.read_csv(path, dtype=str, chunksize=chunksize, low_memory=False)


def _normalize_t100_chunk(
    df: pd.DataFrame,
    *,
    as_of: date,
    universe_iata: set[str] | None,
) -> pd.DataFrame:
    df = normalize_columns(df)
    origin = require_column(df, "origin", "origin_iata", "orig")
    dest = require_column(df, "dest", "destination", "dest_iata")
    year_col = first_present(df, "year", "yy")
    month_col = first_present(df, "month", "mm")
    pax = first_present(df, "passengers", "pax")
    seats = first_present(df, "seats", "available_seats")
    dist = first_present(df, "distance", "distance_miles", "distance_km")
    class_col = first_present(df, "class", "service_class")
    orig_cc = first_present(df, "origin_country", "origin_country_name", "og_country")
    dest_cc = first_present(df, "dest_country", "destination_country", "dest_country_name")
    intl_col = first_present(df, "international")
    deps = first_present(df, "departures_performed", "departures")

    if class_col is not None:
        klass = df[class_col].astype(str).str.strip().str.upper()
        keep = klass.isin(PASSENGER_CLASSES) | klass.isin({"", "NAN"})
        # If the fixture has no class variety, keep all rows with passengers.
        if keep.any() and not keep.all():
            df = df.loc[keep]

    out = pd.DataFrame(
        {
            "origin": as_iata(df[origin]),
            "dest": as_iata(df[dest]),
            "year": parse_int(df[year_col]) if year_col else pd.NA,
            "month": parse_int(df[month_col]) if month_col else 0,
            "passengers": parse_int(df[pax]) if pax else 0,
            "seats": parse_int(df[seats]) if seats else 0,
        }
    )
    miles = parse_float(df[dist]) if dist else pd.Series([pd.NA] * len(df), dtype="Float64")
    # If the column is already km (fixture), values for ANC-JFK ~5420; miles ~3370.
    # Treat values > 4500 as already-km only when labelled distance_km.
    if dist == "distance_km":
        out["distance_km"] = miles
    else:
        out["distance_km"] = miles * MILES_TO_KM

    if intl_col is not None:
        out["international"] = (
            df[intl_col]
            .astype(str)
            .str.strip()
            .str.lower()
            .isin({"1", "true", "yes", "y", "international"})
        )
    elif orig_cc is not None and dest_cc is not None:
        o = df[orig_cc].astype(str).str.strip().str.upper()
        d = df[dest_cc].astype(str).str.strip().str.upper()
        out["international"] = o.ne(d)
    else:
        out["international"] = False

    if deps:
        out["departures"] = parse_float(df[deps]).fillna(0)

    out["as_of"] = as_of
    out = out[(out["origin"].str.len() == 3) & (out["dest"].str.len() == 3)]
    if universe_iata is not None:
        out = out[out["origin"].isin(universe_iata) | out["dest"].isin(universe_iata)]
    # Drop pure cargo zeros.
    out = out[(out["passengers"].fillna(0) > 0) | (out["seats"].fillna(0) > 0)]
    return out.reset_index(drop=True)


def _empty_t100() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "origin",
            "dest",
            "year",
            "month",
            "passengers",
            "seats",
            "distance_km",
            "international",
            "as_of",
        ]
    )
