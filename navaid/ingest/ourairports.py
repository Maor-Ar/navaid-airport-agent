"""OurAirports airports + runways parsers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from navaid.ingest.util import as_iata, first_present, normalize_columns, parse_float, parse_int, require_column

US_COMMERCIAL_TYPES = frozenset({"large_airport", "medium_airport", "small_airport"})


def parse_airports(
    path: Path | str,
    *,
    as_of: date,
    us_scheduled_only: bool = True,
) -> pd.DataFrame:
    """Return warehouse `airports` rows. US scheduled with IATA when filtering."""

    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = normalize_columns(df)
    ident = require_column(df, "ident", "icao", "gps_code")
    iata_col = first_present(df, "iata_code", "iata", "iata_faa")
    name_col = first_present(df, "name")
    muni = first_present(df, "municipality", "city")
    region = first_present(df, "iso_region")
    country = first_present(df, "iso_country")
    lat = first_present(df, "latitude_deg", "latitude", "lat")
    lon = first_present(df, "longitude_deg", "longitude", "lon", "lng")
    elev = first_present(df, "elevation_ft")
    typ = first_present(df, "type")
    scheduled = first_present(df, "scheduled_service")

    out = pd.DataFrame(
        {
            "icao": df[ident].astype(str).str.strip().str.upper(),
            "iata": as_iata(df[iata_col]) if iata_col else pd.Series([pd.NA] * len(df)),
            "name": df[name_col] if name_col else pd.NA,
            "municipality": df[muni] if muni else pd.NA,
            "iso_region": df[region] if region else pd.NA,
            "iso_country": df[country].astype(str).str.strip().str.upper() if country else pd.NA,
            "latitude": parse_float(df[lat]) if lat else pd.NA,
            "longitude": parse_float(df[lon]) if lon else pd.NA,
            "elevation_ft": parse_int(df[elev]) if elev else pd.NA,
            "type": df[typ] if typ else pd.NA,
        }
    )
    out["as_of"] = as_of
    out["iata"] = out["iata"].replace({"": pd.NA, "NAN": pd.NA, "NONE": pd.NA, "NA": pd.NA})
    keep = out["icao"].str.len().fillna(0) >= 3

    if us_scheduled_only:
        if scheduled:
            sched = df[scheduled].astype(str).str.strip().str.lower().isin({"yes", "y", "true", "1"})
            keep &= sched.reindex(out.index).fillna(False)
        if country:
            keep &= out["iso_country"] == "US"
        if typ:
            keep &= out["type"].isin(US_COMMERCIAL_TYPES)
        keep &= out["iata"].notna() & (out["iata"].str.len() == 3)

    return out.loc[keep].drop_duplicates(subset=["icao"]).reset_index(drop=True)


def parse_runways(
    path: Path | str,
    *,
    airport_icaos: set[str] | None = None,
) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str, low_memory=False)
    df = normalize_columns(df)
    icao_col = require_column(df, "airport_ident", "ident", "icao")
    rwy = first_present(df, "le_ident", "ident", "runway")
    length = first_present(df, "length_ft")
    width = first_present(df, "width_ft")
    surface = first_present(df, "surface")
    lighted = first_present(df, "lighted")
    closed = first_present(df, "closed")

    out = pd.DataFrame(
        {
            "icao": df[icao_col].astype(str).str.strip().str.upper(),
            "ident": df[rwy].astype(str).str.strip() if rwy else pd.NA,
            "length_ft": parse_int(df[length]) if length else pd.NA,
            "width_ft": parse_int(df[width]) if width else pd.NA,
            "surface": df[surface] if surface else pd.NA,
            "lighted": _as_bool(df[lighted]) if lighted else pd.NA,
            "closed": _as_bool(df[closed]) if closed else pd.NA,
        }
    )
    if airport_icaos is not None:
        out = out[out["icao"].isin(airport_icaos)]
    return out.reset_index(drop=True)


def _as_bool(series: pd.Series) -> pd.Series:
    mapped = (
        series.astype(str)
        .str.strip()
        .str.lower()
        .map({"1": True, "true": True, "yes": True, "y": True, "0": False, "false": False, "no": False, "n": False})
    )
    return mapped
