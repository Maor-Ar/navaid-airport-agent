"""DuckDB → in-memory metric dicts for the scoring engines.

If the snapshot file is missing, fail with a clear command to build it.
Engines stay warehouse-agnostic; this adapter is the only SQL they need.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

import duckdb

from navaid.config import LONGHAUL_KM, NEW_ENGLAND_IATA, NEW_ENGLAND_STATES, WAREHOUSE_PATH
from navaid.scoring._util import optional_float
from navaid.scoring.longhaul import longhaul_share as engine_longhaul
from navaid.scoring.unmet import unmet_demand as engine_unmet
from navaid.warehouse.db import connect, init_schema

SNAPSHOT_BUILD_HINT = (
    "Run `python scripts/build_snapshot.py` "
    "(use `--offline` if you cannot download public files)."
)


class SnapshotMissingError(FileNotFoundError):
    """Raised when `data/warehouse/navaid.duckdb` has not been built."""


def require_snapshot(path: Path | str | None = None) -> Path:
    target = Path(path or WAREHOUSE_PATH)
    if not target.is_file():
        raise SnapshotMissingError(
            f"Warehouse snapshot not found at {target}. {SNAPSHOT_BUILD_HINT}"
        )
    return target


def _scalar(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:  # NaN
            return None
    except Exception:
        pass
    if hasattr(value, "item") and not isinstance(value, (bytes, str)):
        try:
            value = value.item()
        except Exception:
            pass
    if isinstance(value, date) and not isinstance(value, type(date.min)):
        # datetime is a date subclass; keep date/datetime as-is
        pass
    return value


def _float(value: Any, ndigits: int | None = 6) -> float | None:
    number = optional_float(_scalar(value))
    if number is None:
        return None
    if ndigits is None:
        return number
    return round(number, ndigits)


def _str(value: Any) -> str | None:
    value = _scalar(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class MetricsCatalog:
    """Read-only view of warehouse tables as scoring-engine metric dicts."""

    def __init__(
        self,
        path: Path | str | None = None,
        *,
        con: duckdb.DuckDBPyConnection | None = None,
    ) -> None:
        if con is not None:
            self._con = con
            self._owns = False
            self.path = Path(path or WAREHOUSE_PATH)
        else:
            self.path = require_snapshot(path)
            self._con = connect(self.path, read_only=True)
            self._owns = True
        self._base_cache: dict[str, dict[str, Any]] = {}
        self._as_of: date | None = None
        self._iata_index: set[str] | None = None

    def close(self) -> None:
        if self._owns:
            self._con.close()
            self._owns = False

    def __enter__(self) -> MetricsCatalog:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def connection(self) -> duckdb.DuckDBPyConnection:
        return self._con

    def as_of(self) -> date | None:
        if self._as_of is not None:
            return self._as_of
        try:
            row = self._con.execute(
                "SELECT as_of FROM snapshot_meta LIMIT 1"
            ).fetchone()
        except duckdb.Error:
            row = None
        if row and row[0] is not None:
            value = row[0]
            self._as_of = value if isinstance(value, date) else date.fromisoformat(str(value)[:10])
        return self._as_of

    def known_iata(self) -> set[str]:
        if self._iata_index is None:
            rows = self._con.execute(
                "SELECT DISTINCT iata FROM airports WHERE iata IS NOT NULL AND iata <> ''"
            ).fetchall()
            self._iata_index = {str(r[0]).strip().upper() for r in rows if r[0]}
        return self._iata_index

    def lookup_name(self, query: str, *, limit: int = 8) -> list[dict[str, Any]]:
        """Match IATA, ICAO, name, or municipality. Does not score or rank."""

        needle = query.strip()
        if not needle:
            return []
        upper = needle.upper()
        like = f"%{needle.lower()}%"
        rows = self._con.execute(
            """
            SELECT iata, icao, name, municipality, iso_region
            FROM airports
            WHERE iata IS NOT NULL AND iata <> ''
              AND (
                upper(iata) = ?
                OR upper(icao) = ?
                OR lower(coalesce(name, '')) LIKE ?
                OR lower(coalesce(municipality, '')) LIKE ?
              )
            ORDER BY
              CASE WHEN upper(iata) = ? THEN 0
                   WHEN upper(icao) = ? THEN 1
                   ELSE 2 END,
              iata
            LIMIT ?
            """,
            [upper, upper, like, like, upper, upper, limit],
        ).fetchall()
        return [
            {
                "iata": str(r[0]).upper(),
                "icao": _str(r[1]),
                "name": _str(r[2]),
                "municipality": _str(r[3]),
                "iso_region": _str(r[4]),
            }
            for r in rows
        ]

    def iata_in_region(self, region: str) -> list[str]:
        key = region.strip().lower().replace("_", " ")
        if key in {"new england", "newengland", "ne"}:
            states = tuple(f"US-{s}" for s in NEW_ENGLAND_STATES)
            placeholders = ",".join("?" * len(states))
            rows = self._con.execute(
                f"""
                SELECT DISTINCT iata FROM airports
                WHERE iata IS NOT NULL AND iata <> ''
                  AND upper(iso_region) IN ({placeholders})
                ORDER BY iata
                """,
                list(states),
            ).fetchall()
            found = [str(r[0]).upper() for r in rows if r[0]]
            return found or list(NEW_ENGLAND_IATA)
        # Unknown region name: treat as empty so the caller can error clearly.
        return []

    def segments(self, origin: str) -> list[dict[str, Any]]:
        code = origin.strip().upper()
        rows = self._con.execute(
            """
            SELECT origin, dest, year, month, passengers, seats, distance_km, international
            FROM t100_segments
            WHERE upper(origin) = ?
            """,
            [code],
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "origin": _str(row[0]),
                    "dest": _str(row[1]),
                    "year": int(row[2]) if row[2] is not None else None,
                    "month": int(row[3]) if row[3] is not None else None,
                    "passengers": _float(row[4]),
                    "seats": _float(row[5]),
                    "distance_km": _float(row[6]),
                    "international": bool(row[7]) if row[7] is not None else False,
                }
            )
        return out

    def airport_coords(self) -> dict[str, dict[str, Any]]:
        rows = self._con.execute(
            "SELECT iata, latitude, longitude FROM airports WHERE iata IS NOT NULL"
        ).fetchall()
        return {
            str(r[0]).upper(): {"latitude": _float(r[1]), "longitude": _float(r[2])}
            for r in rows
            if r[0]
        }

    def cbsa_peers(self, iata: str) -> list[dict[str, Any]]:
        code = iata.strip().upper()
        row = self._con.execute(
            "SELECT cbsa_code FROM catchment_cbsa WHERE upper(iata) = ? LIMIT 1",
            [code],
        ).fetchone()
        if not row or not row[0]:
            return []
        cbsa = str(row[0])
        peers = self._con.execute(
            "SELECT iata FROM catchment_cbsa WHERE cbsa_code = ? AND upper(iata) <> ?",
            [cbsa, code],
        ).fetchall()
        out: list[dict[str, Any]] = []
        for peer in peers:
            if not peer[0]:
                continue
            base = self.base_metrics(str(peer[0]))
            if base:
                out.append(base)
        return out

    def base_metrics(self, iata: str) -> dict[str, Any]:
        """Warehouse fields (enplanements, YoY, gates, delay, LF, TAF, CBSA, constraint, lat/lon)."""

        code = iata.strip().upper()
        if code in self._base_cache:
            return dict(self._base_cache[code])

        ident = self._con.execute(
            """
            SELECT iata, icao, name, municipality, iso_region, latitude, longitude
            FROM airports WHERE upper(iata) = ? LIMIT 1
            """,
            [code],
        ).fetchone()
        if ident is None:
            raise KeyError(f"airport {code} is not in the warehouse snapshot")

        enp = self._con.execute(
            """
            SELECT enplanements, yoy, hub_size, year
            FROM enplanements WHERE upper(iata) = ?
            ORDER BY year DESC NULLS LAST LIMIT 1
            """,
            [code],
        ).fetchone()
        gates = self._con.execute(
            "SELECT gate_count FROM gates WHERE upper(iata) = ? LIMIT 1",
            [code],
        ).fetchone()
        delay = self._con.execute(
            """
            SELECT
              avg(delay_pct),
              avg(avg_arrival_delay_min),
              avg(cancel_pct),
              sum(operations),
              max(year)
            FROM delay_cause
            WHERE upper(iata) = ?
              AND year = (SELECT max(year) FROM delay_cause WHERE upper(iata) = ?)
            """,
            [code, code],
        ).fetchone()
        ops = self._con.execute(
            """
            SELECT operations, year FROM airport_ops
            WHERE upper(iata) = ? ORDER BY year DESC NULLS LAST LIMIT 1
            """,
            [code],
        ).fetchone()
        t100 = self._con.execute(
            """
            SELECT sum(passengers), sum(seats)
            FROM t100_segments WHERE upper(origin) = ?
            """,
            [code],
        ).fetchone()
        taf_hi = self._con.execute(
            """
            SELECT passengers, forecast_year FROM taf_forecasts
            WHERE upper(iata) = ? ORDER BY forecast_year DESC NULLS LAST LIMIT 1
            """,
            [code],
        ).fetchone()
        taf_lo = self._con.execute(
            """
            SELECT passengers, forecast_year FROM taf_forecasts
            WHERE upper(iata) = ? ORDER BY forecast_year ASC NULLS LAST LIMIT 1
            """,
            [code],
        ).fetchone()
        cbsa = self._con.execute(
            """
            SELECT cbsa_code, cbsa_name FROM catchment_cbsa
            WHERE upper(iata) = ? LIMIT 1
            """,
            [code],
        ).fetchone()
        constraint = self._con.execute(
            """
            SELECT constraint_type, curfew, notes FROM constraints
            WHERE upper(iata) = ? LIMIT 1
            """,
            [code],
        ).fetchone()
        npias = self._con.execute(
            "SELECT development_need FROM npias WHERE upper(iata) = ? LIMIT 1",
            [code],
        ).fetchone()
        aip = self._con.execute(
            """
            SELECT sum(amount_usd) FROM aip_grants WHERE upper(iata) = ?
            """,
            [code],
        ).fetchone()
        runways = self._con.execute(
            """
            SELECT count(*) FROM runways
            WHERE upper(icao) = ? AND coalesce(closed, false) = false
            """,
            [str(ident[1]).upper() if ident[1] else ""],
        ).fetchone()

        enplanements = _float(enp[0]) if enp else None
        yoy = _float(enp[1]) if enp else None
        gate_count = _float(gates[0]) if gates else None
        pax_per_gate = None
        if enplanements is not None and gate_count and gate_count > 0:
            pax_per_gate = enplanements / gate_count

        pax = _float(t100[0]) if t100 else None
        seats = _float(t100[1]) if t100 else None
        lf = (pax / seats) if pax is not None and seats and seats > 0 else None

        operations = _float(ops[0]) if ops and ops[0] is not None else (
            _float(delay[3]) if delay else None
        )
        runway_count = _float(runways[0]) if runways else None
        ops_per_runway = None
        if operations is not None and runway_count and runway_count > 0:
            ops_per_runway = operations / runway_count

        constraint_type = _str(constraint[0]) if constraint else None
        if constraint_type:
            constraint_type = constraint_type.strip().lower()

        row: dict[str, Any] = {
            "airport": code,
            "iata": code,
            "icao": _str(ident[1]) or code,
            "name": _str(ident[2]),
            "municipality": _str(ident[3]),
            "iso_region": _str(ident[4]),
            "latitude": _float(ident[5]),
            "longitude": _float(ident[6]),
            "enplanements": enplanements,
            "served": enplanements,
            "yoy": yoy,
            "hub_size": _str(enp[2]) if enp else None,
            "gate_count": gate_count,
            "pax_per_gate": pax_per_gate,
            "delay_pct": _float(delay[0]) if delay else None,
            "avg_arrival_delay_min": _float(delay[1]) if delay else None,
            "cancel_pct": _float(delay[2]) if delay else None,
            "operations": operations,
            "runway_count": runway_count,
            "ops_per_runway": ops_per_runway,
            "lf": lf,
            "load_factor": lf,
            "taf_10y": _float(taf_hi[0]) if taf_hi else None,
            "taf_10y_year": int(taf_hi[1]) if taf_hi and taf_hi[1] is not None else None,
            "implied_current_capacity": _float(taf_lo[0]) if taf_lo else enplanements,
            "cbsa": _str(cbsa[0]) if cbsa else None,
            "cbsa_code": _str(cbsa[0]) if cbsa else None,
            "cbsa_name": _str(cbsa[1]) if cbsa else None,
            "constraint_type": constraint_type or "mixed",
            "constraint_type_missing": constraint_type is None,
            "curfew": _str(constraint[1]) if constraint else None,
            "constraint_notes": _str(constraint[2]) if constraint else None,
            "development_need": _str(npias[0]) if npias else None,
            "aip_amount_usd": _float(aip[0]) if aip else None,
            "as_of": self.as_of(),
        }
        self._base_cache[code] = row
        return dict(row)

    def teoi_row(self, iata: str, *, peers: Sequence[dict[str, Any]] | None = None) -> dict[str, Any]:
        """Base warehouse row plus TEOI feature keys the scorer min-maxes in S."""

        row = self.base_metrics(iata)
        peer_rows = list(peers) if peers is not None else self.cbsa_peers(iata)
        try:
            unmet = engine_unmet(
                row,
                peers=peer_rows,
                as_of=self.as_of(),
            )
            row["unmet_demand"] = unmet.unmet
            row["unmet_detail"] = {
                "unmet": unmet.unmet,
                "lf_gap": unmet.lf_gap,
                "taf_gap": unmet.taf_gap,
                "leakage": unmet.leakage,
                "leakage_peers": unmet.leakage_peers,
            }
        except ValueError:
            row["unmet_demand"] = None
            row["unmet_detail"] = None

        try:
            lh = engine_longhaul(
                row,
                segments=self.segments(iata),
                airports=self.airport_coords(),
                threshold_km=LONGHAUL_KM,
                as_of=self.as_of(),
            )
            # 0–1 yield proxy: long-haul share (international is a second signal).
            row["yield_mix"] = (lh.pct_longhaul + lh.pct_international) / 200.0
            row["pct_longhaul"] = lh.pct_longhaul
            row["pct_international"] = lh.pct_international
        except ValueError:
            row["yield_mix"] = None

        enplanements = _float(row.get("enplanements"))
        yoy = _float(row.get("yoy"))
        if enplanements is not None:
            row["demand_pressure"] = enplanements * (1.0 + (yoy or 0.0))
        else:
            row["demand_pressure"] = None

        delay = _float(row.get("delay_pct"))
        cancel = _float(row.get("cancel_pct"))
        if delay is not None and cancel is not None:
            row["congestion"] = delay + cancel
        else:
            row["congestion"] = delay if delay is not None else cancel

        row["landside_saturation"] = _float(row.get("pax_per_gate"))

        taf = _float(row.get("taf_10y"))
        current = _float(row.get("implied_current_capacity")) or enplanements
        if taf is not None and current and current > 0:
            row["growth_outlook"] = (taf / current) ** 0.1 - 1.0
        else:
            row["growth_outlook"] = yoy

        row["capital_feasibility"] = _capital_feasibility(
            row.get("development_need"),
            _float(row.get("aip_amount_usd")),
        )
        return row

    def teoi_rows(self, airports: Sequence[str]) -> list[dict[str, Any]]:
        bases = [self.base_metrics(code) for code in airports]
        by_cbsa: dict[str, list[dict[str, Any]]] = {}
        for row in bases:
            key = str(row.get("cbsa") or "")
            by_cbsa.setdefault(key, []).append(row)
        out: list[dict[str, Any]] = []
        for row in bases:
            key = str(row.get("cbsa") or "")
            peers = [p for p in by_cbsa.get(key, []) if p["airport"] != row["airport"]]
            out.append(self.teoi_row(row["airport"], peers=peers))
        return out


def _capital_feasibility(need: str | None, aip_amount: float | None) -> float | None:
    if not need:
        return None
    text = need.lower()
    if "limited" in text or "constrained airside" in text:
        score = 0.30
    elif "landside" in text:
        score = 0.90
    elif "modest" in text:
        score = 0.45
    elif "high" in text or "significant" in text:
        score = 0.55
    else:
        score = 0.50
    if aip_amount is not None and aip_amount > 0:
        score *= 0.85
    return score


__all__ = [
    "SNAPSHOT_BUILD_HINT",
    "MetricsCatalog",
    "SnapshotMissingError",
    "require_snapshot",
]
