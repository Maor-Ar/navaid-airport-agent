"""Runtime configuration for Navaid.

Source of truth for public-data URLs, TEOI weights (must sum to 1.0),
constraint multipliers, long-haul threshold, Gemini model, and offline mode.
Scoring engines (later phase) import these constants; they do not invent weights.
"""

from __future__ import annotations

import os
from pathlib import Path
from types import MappingProxyType

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WAREHOUSE_DIR = PROJECT_ROOT / "data" / "warehouse"
WAREHOUSE_PATH = WAREHOUSE_DIR / "navaid.duckdb"

# --- Gemini / runtime -------------------------------------------------------

DEFAULT_MODEL = "gemini-2.5-flash"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "") or os.getenv("GOOGLE_API_KEY", "")
NAVAID_MODEL = os.getenv("NAVAID_MODEL", DEFAULT_MODEL) or DEFAULT_MODEL
GOOGLE_CLOUD_PROJECT = (
    os.getenv("GOOGLE_CLOUD_PROJECT", "")
    or os.getenv("GCLOUD_PROJECT", "")
    or os.getenv("GOOGLE_CLOUD_PROJECT_ID", "")
)
GOOGLE_CLOUD_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "") or os.getenv(
    "GOOGLE_CLOUD_REGION", ""
) or "us-central1"


def _env_flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


# NAVAID_OFFLINE=1: no government HTTP; local DuckDB only.
NAVAID_OFFLINE = _env_flag("NAVAID_OFFLINE")

# Browser origins allowed to call Cloud Run from GitHub Pages (plus localhost).
LOCAL_CORS_ORIGINS: tuple[str, ...] = (
    "http://localhost",
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:7860",
    "http://localhost:8000",
    "http://127.0.0.1",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:7860",
    "http://127.0.0.1:8000",
)

# Extra exact origins, comma-separated. Regex covers https://*.github.io by default.
CORS_ORIGIN_REGEX = os.getenv(
    "NAVAID_CORS_ORIGIN_REGEX",
    r"https://([a-z0-9-]+\.)?github\.io",
)


def cors_allow_origins() -> list[str]:
    origins = list(LOCAL_CORS_ORIGINS)
    extra = os.getenv("NAVAID_CORS_ORIGINS", "")
    for part in extra.split(","):
        item = part.strip().rstrip("/")
        if item:
            origins.append(item)
    return origins

# Snapshot older than this is always an Envelope uncertainty.
STALE_SNAPSHOT_DAYS = 90

# --- Scoring constants (frozen in Phase 1 contracts) ------------------------

LONGHAUL_KM = 4000
LONGHAUL_HOURS = 6.0
UNMET_LOAD_FACTOR_THRESHOLD = 0.85

# Peer-relative TEOI feature weights. Missing features are dropped and the
# remainder is renormalized to 1.0 at score time (see ScoringTrace).
TEOI_WEIGHTS: MappingProxyType[str, float] = MappingProxyType(
    {
        "demand_pressure": 0.22,
        "congestion": 0.18,
        "landside_saturation": 0.18,
        "unmet_demand": 0.15,
        "yield_mix": 0.12,
        "growth_outlook": 0.10,
        "capital_feasibility": 0.05,
    }
)

CONSTRAINT_MULTIPLIERS: MappingProxyType[str, float] = MappingProxyType(
    {
        "landside": 1.00,
        "mixed": 0.75,
        "airside": 0.40,
        "demand-bound": 0.30,
    }
)

if abs(sum(TEOI_WEIGHTS.values()) - 1.0) > 1e-12:
    raise RuntimeError("TEOI_WEIGHTS must sum to 1.0")

# --- Geography --------------------------------------------------------------

# Assignment: New England = CT, ME, MA, NH, RI, VT
NEW_ENGLAND_STATES: tuple[str, ...] = ("CT", "ME", "MA", "NH", "RI", "VT")

NEW_ENGLAND_IATA: tuple[str, ...] = (
    "BOS",
    "BDL",
    "PVD",
    "PWM",
    "MHT",
    "BTV",
    "BGR",
    "ORH",
)

# Extra curated depth beyond US primary commercials.
DEEP_SLICE_IATA: tuple[str, ...] = NEW_ENGLAND_IATA + (
    "LAX",
    "SNA",
    "SFO",
    "OAK",
    "SJC",
    "ANC",
)

# --- Public data URLs (ingest later; listed so engines/docs share one place) -

OURAIRPORTS_AIRPORTS_URL = (
    "https://davidmegginson.github.io/ourairports-data/airports.csv"
)
OURAIRPORTS_RUNWAYS_URL = (
    "https://davidmegginson.github.io/ourairports-data/runways.csv"
)
FAA_ENPLANEMENTS_PAGE_URL = (
    "https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger"
)
FAA_TAF_URL = "https://taf.faa.gov/"
BTS_PREZIP_URL = "https://transtats.bts.gov/PREZIP/"
FAA_NAS_STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
FAA_ASWS_STATUS_TEMPLATE = (
    "https://external-api.faa.gov/asws/api/api/airport/status/{airportCode}"
)
