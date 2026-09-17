"""Build the local DuckDB warehouse snapshot.

Usage (from repo root):

    python scripts/build_snapshot.py
    python scripts/build_snapshot.py --offline
    python scripts/build_snapshot.py --force-fixtures
    python scripts/build_snapshot.py --refresh

Live downloads use httpx with timeout, 429/5xx backoff, and on-disk cache.
NAVAID_OFFLINE=1 (or --offline) never hits the network; checked-in fixtures
are used and as_of/confidence are labeled accordingly.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from navaid.warehouse.snapshot import build_snapshot  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Navaid DuckDB snapshot")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Do not use the network; fixtures + cache only (also honors NAVAID_OFFLINE=1)",
    )
    parser.add_argument(
        "--force-fixtures",
        action="store_true",
        help="Skip live files even if the network is available",
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Ignore on-disk HTTP cache and re-download",
    )
    parser.add_argument(
        "--warehouse",
        type=Path,
        default=None,
        help="Output DuckDB path (default: data/warehouse/navaid.duckdb)",
    )
    args = parser.parse_args(argv)

    result = build_snapshot(
        warehouse_path=args.warehouse,
        offline=True if args.offline else None,
        force_fixtures=args.force_fixtures,
        refresh=args.refresh,
    )
    payload = {
        "warehouse_path": result.warehouse_path,
        "as_of": result.as_of.isoformat(),
        "content_hash": result.content_hash,
        "used_fixtures": result.used_fixtures,
        "row_counts": result.row_counts,
        "sources": [s.model_dump(mode="json") for s in result.sources],
    }
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
