"""Shared ingest paths and dataframe helpers."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from navaid.config import PROJECT_ROOT, WAREHOUSE_DIR

DATA_DIR = PROJECT_ROOT / "data"
FIXTURES_DIR = DATA_DIR / "fixtures"
CURATED_DIR = DATA_DIR / "curated"
CACHE_DIR = DATA_DIR / "cache"

MILES_TO_KM = 1.609344

HUB_MAP = {
    "l": "Large",
    "p l": "Large",
    "pl": "Large",
    "large": "Large",
    "m": "Medium",
    "p m": "Medium",
    "pm": "Medium",
    "medium": "Medium",
    "s": "Small",
    "p s": "Small",
    "ps": "Small",
    "small": "Small",
    "n": "Non-hub",
    "p n": "Non-hub",
    "pn": "Non-hub",
    "nonhub": "Non-hub",
    "non-hub": "Non-hub",
    "non hub": "Non-hub",
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lower-case, strip, and collapse whitespace in column names."""

    out = df.copy()
    out.columns = [
        " ".join(str(c).strip().lower().replace("\n", " ").split()) for c in out.columns
    ]
    return out


def first_present(df: pd.DataFrame, *names: str) -> str | None:
    cols = {c: c for c in df.columns}
    for name in names:
        key = " ".join(name.strip().lower().split())
        if key in cols:
            return key
    return None


def require_column(df: pd.DataFrame, *names: str) -> str:
    found = first_present(df, *names)
    if found is None:
        raise ValueError(f"missing column; tried {names}; have {list(df.columns)}")
    return found


def as_iata(series: pd.Series) -> pd.Series:
    return (
        series.astype(str)
        .str.strip()
        .str.upper()
        .str.replace(r"[^A-Z0-9]", "", regex=True)
    )


def parse_int(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce").astype("Int64")


def parse_float(series: pd.Series) -> pd.Series:
    cleaned = (
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
    )
    return pd.to_numeric(cleaned, errors="coerce")


def map_hub_size(value: object) -> str | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = " ".join(str(value).strip().lower().split())
    if not text:
        return None
    if text in HUB_MAP:
        return HUB_MAP[text]
    # "P L", "Primary Large", etc.
    if "large" in text or text.endswith(" l"):
        return "Large"
    if "medium" in text or text.endswith(" m"):
        return "Medium"
    if "small" in text or text.endswith(" s"):
        return "Small"
    if "non" in text or text.endswith(" n"):
        return "Non-hub"
    return str(value).strip()


def coerce_date(value: object, default: date) -> date:
    try:
        if value is None or pd.isna(value):
            return default
    except (ValueError, TypeError):
        pass
    if isinstance(value, date):
        return date(value.year, value.month, value.day)
    text = str(value).strip()
    if not text or text.lower() in {"nan", "nat", "none", "<na>"}:
        return default
    return date.fromisoformat(text[:10])


def ensure_dirs() -> None:
    for path in (FIXTURES_DIR, CURATED_DIR, CACHE_DIR, WAREHOUSE_DIR):
        path.mkdir(parents=True, exist_ok=True)
