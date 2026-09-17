"""Curated gates, CBSA catchments, constraints, and optional notes → doc_chunks."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from navaid.ingest.util import CURATED_DIR, as_iata, coerce_date, normalize_columns, parse_int, require_column


def load_gates(path: Path | str | None = None, *, as_of: date | None = None) -> pd.DataFrame:
    path = Path(path or CURATED_DIR / "gates.csv")
    df = normalize_columns(pd.read_csv(path, dtype=str))
    iata = as_iata(df[require_column(df, "iata")])
    icao_col = "icao" if "icao" in df.columns else None
    default_as_of = as_of or date(2024, 12, 31)
    as_of_series = (
        df["as_of"].map(lambda v: coerce_date(v, default_as_of)) if "as_of" in df.columns else default_as_of
    )
    return pd.DataFrame(
        {
            "iata": iata,
            "icao": as_iata(df[icao_col]) if icao_col else pd.NA,
            "gate_count": parse_int(df[require_column(df, "gate_count", "gates")]),
            "as_of": as_of_series,
            "source": df["source"] if "source" in df.columns else "curated",
        }
    )


def load_catchment(path: Path | str | None = None, *, as_of: date | None = None) -> pd.DataFrame:
    path = Path(path or CURATED_DIR / "catchment_cbsa.csv")
    df = normalize_columns(pd.read_csv(path, dtype=str))
    default_as_of = as_of or date(2024, 12, 31)
    as_of_series = (
        df["as_of"].map(lambda v: coerce_date(v, default_as_of)) if "as_of" in df.columns else default_as_of
    )
    return pd.DataFrame(
        {
            "iata": as_iata(df[require_column(df, "iata")]),
            "icao": as_iata(df["icao"]) if "icao" in df.columns else pd.NA,
            "cbsa_code": df[require_column(df, "cbsa_code", "cbsa")].astype(str).str.strip(),
            "cbsa_name": df[require_column(df, "cbsa_name", "cbsa name")].astype(str).str.strip(),
            "as_of": as_of_series,
        }
    )


def load_constraints(path: Path | str | None = None, *, as_of: date | None = None) -> pd.DataFrame:
    path = Path(path or CURATED_DIR / "constraints.csv")
    df = normalize_columns(pd.read_csv(path, dtype=str))
    default_as_of = as_of or date(2024, 12, 31)
    as_of_series = (
        df["as_of"].map(lambda v: coerce_date(v, default_as_of)) if "as_of" in df.columns else default_as_of
    )
    return pd.DataFrame(
        {
            "iata": as_iata(df[require_column(df, "iata")]),
            "icao": as_iata(df["icao"]) if "icao" in df.columns else pd.NA,
            "constraint_type": df[require_column(df, "constraint_type", "constraint")]
            .astype(str)
            .str.strip()
            .str.lower(),
            "curfew": df["curfew"] if "curfew" in df.columns else pd.NA,
            "notes": df["notes"] if "notes" in df.columns else pd.NA,
            "as_of": as_of_series,
        }
    )


def load_notes_as_chunks(path: Path | str | None = None) -> pd.DataFrame:
    """Optional curated notes.csv → doc_chunks (RAG later; we only load)."""

    path = Path(path or CURATED_DIR / "notes.csv")
    if not path.is_file():
        return pd.DataFrame(columns=["chunk_id", "airport", "doc_type", "as_of", "url", "title", "body"])
    df = normalize_columns(pd.read_csv(path, dtype=str))
    airport = as_iata(df[require_column(df, "airport", "iata")])
    body = df[require_column(df, "body", "text", "notes")]
    title = df["title"] if "title" in df.columns else airport
    doc_type = df["doc_type"] if "doc_type" in df.columns else "note"
    url = df["url"] if "url" in df.columns else pd.NA
    as_of = df["as_of"] if "as_of" in df.columns else pd.NA
    chunk_id = [
        f"{a}-{i:03d}" for i, a in enumerate(airport.tolist())
    ]
    return pd.DataFrame(
        {
            "chunk_id": chunk_id,
            "airport": airport,
            "doc_type": doc_type,
            "as_of": as_of,
            "url": url,
            "title": title,
            "body": body,
        }
    )
