"""Pydantic v2 contracts for every `/ask` response.

Gemini may quote these fields. It may not invent a different TEOI formula.
Gradio and the analyst site render a waterfall from the same JSON.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from navaid.config import CONSTRAINT_EXPLANATIONS, CONSTRAINT_MULTIPLIERS, TEOI_WEIGHTS


class LockedModel(BaseModel):
    """Shared config: extra fields are a contract break, not a silent drop."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Confidence(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ConstraintType(StrEnum):
    LANDSIDE = "landside"
    MIXED = "mixed"
    AIRSIDE = "airside"
    DEMAND_BOUND = "demand-bound"


class Intent(StrEnum):
    EXPANSION_RANK = "EXPANSION_RANK"
    CONGESTION_COMPARE = "CONGESTION_COMPARE"
    LONGHAUL_SHARE = "LONGHAUL_SHARE"
    UNMET_DEMAND = "UNMET_DEMAND"
    AIRPORT_BRIEF = "AIRPORT_BRIEF"
    EXPLAIN_TEOI = "EXPLAIN_TEOI"
    EXPLAIN_CONSTRAINT = "EXPLAIN_CONSTRAINT"
    FOLLOW_UP = "FOLLOW_UP"
    CHITCHAT = "CHITCHAT"
    CAPABILITIES = "CAPABILITIES"
    UNSUPPORTED = "UNSUPPORTED"


class SubgoalStatus(StrEnum):
    PENDING = "pending"
    ANSWERED = "answered"
    UNSUPPORTED = "unsupported"
    FAILED = "failed"


class Envelope(LockedModel):
    """Assumptions, uncertainty, and scoping attached to every engine result and Answer."""

    assumptions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)
    confidence: Confidence
    sources: list[str] = Field(default_factory=list)
    as_of: date | None = None


class ScoringTrace(LockedModel):
    """Full TEOI working for one airport inside a peer set.

    Waterfall: raw → min-max in peer_set → weight → contribution → constraint
    multiplier → teoi → rank. Missing features are listed in weights_dropped
    and the remainder is renormalized into weights_used.
    """

    airport: str = Field(..., description="IATA code, e.g. BDL")
    peer_set: list[str] = Field(..., min_length=1)
    raw: dict[str, float | None] = Field(default_factory=dict)
    scaled_0_1: dict[str, float | None] = Field(default_factory=dict)
    weights_original: dict[str, float] = Field(
        default_factory=lambda: dict(TEOI_WEIGHTS)
    )
    weights_dropped: list[str] = Field(default_factory=list)
    weights_used: dict[str, float] = Field(default_factory=dict)
    contributions: dict[str, float] = Field(
        default_factory=dict,
        description="100 * weight_used * scaled_0_1 per feature",
    )
    weighted_sum: float
    constraint_type: ConstraintType
    constraint_multiplier: float
    teoi: float
    rank: int = Field(..., ge=1)
    formula_text: str

    @field_validator("airport")
    @classmethod
    def _iata_upper(cls, value: str) -> str:
        return value.strip().upper()

    @field_validator("peer_set")
    @classmethod
    def _peer_upper(cls, value: list[str]) -> list[str]:
        return [code.strip().upper() for code in value]

    @field_validator("weights_original")
    @classmethod
    def _original_sums_to_one(cls, value: dict[str, float]) -> dict[str, float]:
        total = sum(value.values())
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"weights_original must sum to 1.0, got {total}")
        return value

    @field_validator("weights_used")
    @classmethod
    def _used_sums_to_one_if_present(cls, value: dict[str, float]) -> dict[str, float]:
        if value and abs(sum(value.values()) - 1.0) > 1e-9:
            raise ValueError("weights_used must sum to 1.0 after renormalization")
        return value

    @model_validator(mode="after")
    def _lock_constraint_multiplier(self) -> Self:
        expected = CONSTRAINT_MULTIPLIERS[str(self.constraint_type)]
        if abs(self.constraint_multiplier - expected) > 1e-9:
            raise ValueError(
                f"constraint_multiplier {self.constraint_multiplier} does not match "
                f"{self.constraint_type} ({expected})"
            )
        return self


class Subgoal(LockedModel):
    """One closed intent from decomposition. All subgoals are executed."""

    intent: Intent
    entities: list[str] = Field(default_factory=list)
    status: SubgoalStatus = SubgoalStatus.PENDING
    query: str = ""
    notes: str = ""


class Step(LockedModel):
    """Ordered working visible to the analyst (reconstruct, tools, lock, …)."""

    index: int = Field(..., ge=1)
    name: str
    detail: str = ""


class Section(LockedModel):
    """One prose block per subgoal so compound questions cannot collapse."""

    heading: str
    body: str
    subgoal_index: int | None = Field(default=None, ge=0)


class Citation(LockedModel):
    label: str
    url: str | None = None
    source: str | None = None
    as_of: date | None = None


class UnsupportedPart(LockedModel):
    text: str
    reason: str
    subgoal_index: int | None = None


class ProcessEvent(LockedModel):
    """One live working beat shown before the final answer (thought / tool / result)."""

    kind: str = Field(..., description="thought | tool | result")
    title: str = ""
    detail: str = ""

    @field_validator("kind")
    @classmethod
    def _known_kind(cls, value: str) -> str:
        key = (value or "").strip().lower()
        if key not in {"thought", "tool", "result"}:
            raise ValueError(f"unknown process kind: {value!r}")
        return key


class MapPoint(LockedModel):
    """One airport marker for the workbench map sidebar."""

    iata: str
    name: str = ""
    lat: float
    lon: float
    role: str = ""
    enplanements: float | None = None
    constraint: str | None = None
    teoi: float | None = None
    highlight: bool = False
    load_factor: float | None = None
    delay_pct: float | None = None
    why: str = ""

    @field_validator("iata")
    @classmethod
    def _iata_upper(cls, value: str) -> str:
        return value.strip().upper()


class Answer(LockedModel):
    """Canonical `/ask` payload shared by CLI, FastAPI, Gradio, and the site."""

    reconstructed_query: str
    reconstruction_notes: str = ""
    subgoals: list[Subgoal] = Field(default_factory=list)
    steps: list[Step] = Field(default_factory=list)
    process: list[ProcessEvent] = Field(default_factory=list)
    sections: list[Section] = Field(default_factory=list)
    teoi_traces: list[ScoringTrace] = Field(default_factory=list)
    tables: dict[str, Any] = Field(default_factory=dict)
    map_points: list[MapPoint] = Field(default_factory=list)
    envelope: Envelope
    citations: list[Citation] = Field(default_factory=list)
    unsupported_parts: list[UnsupportedPart] = Field(default_factory=list)


def constraint_multiplier_for(constraint_type: ConstraintType | str) -> float:
    """Look up the frozen multiplier; engines must not invent one."""

    key = str(constraint_type)
    try:
        return CONSTRAINT_MULTIPLIERS[key]
    except KeyError as exc:
        raise KeyError(f"unknown constraint_type: {constraint_type!r}") from exc


def constraint_key(constraint_type: ConstraintType | str | None) -> str:
    """Normalize MIXED / Demand-bound / demand_bound to the canonical key."""

    return (
        str(constraint_type or "")
        .strip()
        .lower()
        .replace("_", "-")
        .replace(" ", "-")
    )


def constraint_explanation_for(constraint_type: ConstraintType | str | None) -> str:
    """Glossary why-text for a constraint class; empty if unknown or missing."""

    return CONSTRAINT_EXPLANATIONS.get(constraint_key(constraint_type), "")


__all__ = [
    "Answer",
    "Citation",
    "Confidence",
    "ConstraintType",
    "Envelope",
    "Intent",
    "MapPoint",
    "ProcessEvent",
    "ScoringTrace",
    "Section",
    "Step",
    "Subgoal",
    "SubgoalStatus",
    "UnsupportedPart",
    "constraint_explanation_for",
    "constraint_key",
    "constraint_multiplier_for",
]
