"""Warehouse-specific types (not the /ask Answer contract)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class WarehouseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class IngestSourceRecord(WarehouseModel):
    """Provenance for one ingested file (live download vs checked-in fixture)."""

    source_id: str
    url: str | None = None
    local_path: str | None = None
    as_of: date
    confidence: str = Field(description="high | medium | low")
    used_fixture: bool = False
    notes: str = ""


class SnapshotBuildResult(WarehouseModel):
    warehouse_path: str
    as_of: date
    content_hash: str
    used_fixtures: list[str] = Field(default_factory=list)
    sources: list[IngestSourceRecord] = Field(default_factory=list)
    row_counts: dict[str, int] = Field(default_factory=dict)
    notes: str = ""
