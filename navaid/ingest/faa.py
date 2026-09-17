"""FAA CY enplanements, optional TAF, optional NPIAS Appendix A."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from navaid.ingest.util import (
    as_iata,
    first_present,
    map_hub_size,
    normalize_columns,
    parse_float,
    parse_int,
    require_column,
)


def parse_enplanements(path: Path | str, *, as_of: date, year: int = 2024) -> pd.DataFrame:
    """Parse FAA commercial-service enplanements Excel or CSV into warehouse rows."""

    df = _read_table(path)
    df = _promote_header(df)
    df = normalize_columns(df)

    locid = require_column(df, "locid", "iata", "airport", "loc id", "airport code", "code")
    hub = first_present(df, "hub", "hub size", "hub_size", "cy 24 hub", "cy 2024 hub")
    current = _enplanement_column(df, prefer_year=year)
    if current is None:
        raise ValueError(f"no enplanement column; have {list(df.columns)}")
    prior = _enplanement_column(df, prefer_year=year - 1, exclude=current)
    yoy_col = first_present(df, "% change", "pct change", "percent change", "yoy", "%chg")
    icao_col = first_present(df, "icao")

    iata = as_iata(df[locid])
    # Some sheets put city then locid; drop rows that are not 3-char codes.
    mask = iata.str.len() == 3
    iata = iata[mask]
    df = df.loc[mask].copy()

    enp = parse_int(df[current])
    if prior is not None:
        prior_enp = parse_int(df[prior])
        yoy = (enp.astype("Float64") - prior_enp.astype("Float64")) / prior_enp.astype("Float64")
    elif yoy_col is not None:
        yoy = parse_float(df[yoy_col])
        # Sheets often store 3.06 meaning 3.06%, not 0.0306.
        yoy = yoy.where(yoy.abs() <= 2.0, yoy / 100.0)
        prior_enp = pd.Series([pd.NA] * len(df), dtype="Int64")
    else:
        yoy = pd.Series([pd.NA] * len(df), dtype="Float64")
        prior_enp = pd.Series([pd.NA] * len(df), dtype="Int64")

    if yoy_col is not None and prior is not None:
        # Prefer computed YoY; keep sheet as fallback where prior is missing.
        sheet_yoy = parse_float(df[yoy_col])
        sheet_yoy = sheet_yoy.where(sheet_yoy.abs() <= 2.0, sheet_yoy / 100.0)
        yoy = yoy.fillna(sheet_yoy)

    hub_size = df[hub].map(map_hub_size) if hub else pd.Series([pd.NA] * len(df))

    out = pd.DataFrame(
        {
            "iata": iata.values,
            "icao": as_iata(df[icao_col]).values if icao_col else pd.NA,
            "year": year,
            "enplanements": enp.astype("Int64"),
            "hub_size": hub_size.values if hub else pd.NA,
            "yoy": yoy.astype("Float64"),
            "as_of": as_of,
        }
    )
    out = out[out["enplanements"].notna() & (out["iata"].str.len() == 3)]
    return out.drop_duplicates(subset=["iata", "year"]).reset_index(drop=True)


def parse_taf(path: Path | str, *, as_of: date) -> pd.DataFrame:
    """Parse a TAF extract (CSV/Excel, wide or long) into warehouse rows."""

    df = _read_table(path)
    df = _promote_header(df)
    df = normalize_columns(df)

    iata_col = require_column(df, "iata", "locid", "airport", "code")
    icao_col = first_present(df, "icao")
    year_col = first_present(df, "forecast_year", "year", "fy")
    pax_col = first_present(df, "passengers", "enplanements", "pax", "total enplanements")
    ops_col = first_present(df, "operations", "ops", "total operations")

    if year_col is None:
        # Wide format: year-like columns.
        year_cols = [c for c in df.columns if str(c).replace("fy", "").strip().isdigit()]
        if not year_cols:
            raise ValueError(f"TAF file has no year columns: {list(df.columns)}")
        frames = []
        for col in year_cols:
            year = int("".join(ch for ch in str(col) if ch.isdigit())[:4])
            chunk = pd.DataFrame(
                {
                    "iata": as_iata(df[iata_col]),
                    "icao": as_iata(df[icao_col]) if icao_col else pd.NA,
                    "forecast_year": year,
                    "passengers": parse_int(df[col]) if pax_col is None else parse_int(df[pax_col]),
                    "operations": parse_int(df[ops_col]) if ops_col else pd.NA,
                    "as_of": as_of,
                }
            )
            frames.append(chunk)
        out = pd.concat(frames, ignore_index=True)
    else:
        out = pd.DataFrame(
            {
                "iata": as_iata(df[iata_col]),
                "icao": as_iata(df[icao_col]) if icao_col else pd.NA,
                "forecast_year": parse_int(df[year_col]),
                "passengers": parse_int(df[pax_col]) if pax_col else pd.NA,
                "operations": parse_int(df[ops_col]) if ops_col else pd.NA,
                "as_of": as_of,
            }
        )
    out = out[out["iata"].str.len() == 3]
    return out.reset_index(drop=True)


def parse_npias(path: Path | str, *, as_of: date) -> pd.DataFrame:
    """Parse NPIAS Appendix A (Excel/CSV) into warehouse `npias` rows."""

    df = _read_table(path)
    df = _promote_header(df)
    df = normalize_columns(df)
    iata_col = require_column(df, "iata", "locid", "loc id", "airport id", "code")
    icao_col = first_present(df, "icao")
    need_col = first_present(
        df,
        "development_need",
        "development",
        "development estimate",
        "five-year development",
        "5-year development",
        "need",
        "role",
        "hub",
    )
    iata = as_iata(df[iata_col])
    mask = iata.str.len() == 3
    need = df[need_col].astype(str).str.strip() if need_col else pd.Series(["NPIAS listed"] * len(df))
    out = pd.DataFrame(
        {
            "iata": iata[mask].values,
            "icao": (as_iata(df[icao_col])[mask].values if icao_col else pd.NA),
            "development_need": need[mask].values,
            "as_of": as_of,
        }
    )
    return out.drop_duplicates(subset=["iata"]).reset_index(drop=True)


def _enplanement_column(df: pd.DataFrame, prefer_year: int, exclude: str | None = None) -> str | None:
    candidates = []
    for col in df.columns:
        if exclude and col == exclude:
            continue
        if "enplane" in col or "boarding" in col:
            candidates.append(col)
        if str(prefer_year) in col and ("cy" in col or "enplane" in col or "pax" in col):
            candidates.append(col)
    # Prefer the column that mentions the year.
    for col in candidates:
        if str(prefer_year) in col:
            return col
    if candidates:
        return candidates[0]
    # Generic "enplanements" / "cy enplanements"
    return first_present(df, "enplanements", "cy enplanements", "passenger boardings")


def _read_table(path: Path | str) -> pd.DataFrame:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        # FAA sheets often have title rows before the header.
        df = pd.read_excel(path, header=None, dtype=str, engine="openpyxl")
        return df
    return pd.read_csv(path, dtype=str, header=None)


def _promote_header(df: pd.DataFrame) -> pd.DataFrame:
    """Find the header row that looks like an FAA/BTS table."""

    if df.empty:
        return df
    # Already named columns (normal CSV with header=0 would not go through header=None
    # for curated long TAF — handle both).
    if not all(str(c).isdigit() or str(c).startswith("Unnamed") or isinstance(c, int) for c in df.columns):
        return df

    best_idx = 0
    best_score = -1
    for i, row in df.iterrows():
        values = [str(v).strip().lower() for v in row.tolist() if str(v).strip() not in {"", "nan"}]
        blob = " ".join(values)
        score = 0
        for token in ("locid", "iata", "enplane", "hub", "airport", "passengers", "year", "development"):
            if token in blob:
                score += 1
        if score > best_score:
            best_score = score
            best_idx = int(i)
        if score >= 3:
            break
    header = [str(v).strip() if str(v) != "nan" else f"col_{j}" for j, v in enumerate(df.iloc[best_idx].tolist())]
    body = df.iloc[best_idx + 1 :].copy()
    body.columns = header
    body = body.dropna(how="all")
    return body.reset_index(drop=True)
