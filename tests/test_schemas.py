from __future__ import annotations

from datetime import date

from navaid.config import CONSTRAINT_EXPLANATIONS, CONSTRAINT_MULTIPLIERS, TEOI_WEIGHTS
from navaid.schemas import (
    Answer,
    Citation,
    Confidence,
    ConstraintType,
    Envelope,
    Intent,
    ScoringTrace,
    Section,
    Step,
    Subgoal,
    SubgoalStatus,
    UnsupportedPart,
    constraint_explanation_for,
)


def _renormalized_weights(dropped: list[str]) -> dict[str, float]:
    remaining = {k: v for k, v in TEOI_WEIGHTS.items() if k not in dropped}
    total = sum(remaining.values())
    return {k: v / total for k, v in remaining.items()}


def test_teoi_weights_sum_to_one() -> None:
    assert abs(sum(TEOI_WEIGHTS.values()) - 1.0) < 1e-12


def test_constraint_multipliers() -> None:
    assert CONSTRAINT_MULTIPLIERS["landside"] == 1.00
    assert CONSTRAINT_MULTIPLIERS["mixed"] == 0.75
    assert CONSTRAINT_MULTIPLIERS["airside"] == 0.40
    assert CONSTRAINT_MULTIPLIERS["demand-bound"] == 0.30
    assert set(CONSTRAINT_EXPLANATIONS) == set(CONSTRAINT_MULTIPLIERS)
    assert constraint_explanation_for("MIXED") == CONSTRAINT_EXPLANATIONS["mixed"]
    assert constraint_explanation_for("Demand-bound") == CONSTRAINT_EXPLANATIONS["demand-bound"]
    assert constraint_explanation_for("demand_bound") == CONSTRAINT_EXPLANATIONS["demand-bound"]
    assert constraint_explanation_for(None) == ""


def test_scoring_trace_and_answer_roundtrip() -> None:
    dropped = ["capital_feasibility"]
    used = _renormalized_weights(dropped)
    scaled = {
        "demand_pressure": 0.41,
        "congestion": 0.55,
        "landside_saturation": 0.50,
        "unmet_demand": 0.62,
        "yield_mix": 0.40,
        "growth_outlook": 0.48,
    }
    contributions = {k: 100.0 * used[k] * scaled[k] for k in used}
    weighted_sum = sum(contributions.values())
    multiplier = CONSTRAINT_MULTIPLIERS["landside"]

    trace = ScoringTrace(
        airport="bdl",
        peer_set=["bos", "bdl", "pvd", "pwm", "mht", "btv"],
        raw={
            "enplanements": 3_285_194,
            "yoy": 0.052,
            "pax_per_gate": 82_000,
            "delay_pct": 0.21,
            "lf": 0.87,
        },
        scaled_0_1=scaled,
        weights_original=dict(TEOI_WEIGHTS),
        weights_dropped=dropped,
        weights_used=used,
        contributions=contributions,
        weighted_sum=weighted_sum,
        constraint_type=ConstraintType.LANDSIDE,
        constraint_multiplier=multiplier,
        teoi=weighted_sum * multiplier,
        rank=2,
        formula_text=(
            "TEOI = 100 * ("
            + " + ".join(f"{used[k]:.3f}*{k}" for k in used)
            + f") * {multiplier:.2f}"
        ),
    )

    assert trace.airport == "BDL"
    assert trace.peer_set[0] == "BOS"
    assert abs(sum(trace.weights_used.values()) - 1.0) < 1e-9

    answer = Answer(
        reconstructed_query=(
            "Which airports in New England are strong candidates for terminal expansion?"
        ),
        reconstruction_notes="First turn; reconstruction is a no-op.",
        subgoals=[
            Subgoal(
                intent=Intent.EXPANSION_RANK,
                entities=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"],
                status=SubgoalStatus.ANSWERED,
                query="Rank New England airports by TEOI for terminal expansion.",
            )
        ],
        steps=[
            Step(index=1, name="reconstruct", detail="n/a (first turn)"),
            Step(
                index=2,
                name="decompose",
                detail="one subgoal EXPANSION_RANK region=New England",
            ),
            Step(index=3, name="rank_expansion", detail="engines ran; traces attached"),
        ],
        sections=[
            Section(
                heading="New England expansion rank",
                body="BDL ranks 2 in the peer set on a landside-constrained TEOI.",
                subgoal_index=0,
            )
        ],
        teoi_traces=[trace],
        tables={
            "ranking": [
                {"rank": 2, "airport": "BDL", "teoi": trace.teoi},
            ]
        },
        envelope=Envelope(
            assumptions=[
                "US commercial primary airports; New England = CT, ME, MA, NH, RI, VT"
            ],
            uncertainties=["capital_feasibility dropped (missing NPIAS)"],
            out_of_scope=["PFC / NPV / airline equity"],
            confidence=Confidence.MEDIUM,
            sources=["FAA enplanements", "BTS delay-cause", "OurAirports"],
            as_of=date(2024, 12, 31),
        ),
        citations=[
            Citation(
                label="FAA CY passenger boardings",
                url="https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger",
                source="FAA",
                as_of=date(2024, 12, 31),
            )
        ],
        unsupported_parts=[
            UnsupportedPart(text="buy AAL", reason="equity tickers are out of scope")
        ],
    )

    dumped = answer.model_dump(mode="json")
    restored = Answer.model_validate(dumped)
    assert restored.teoi_traces[0].airport == "BDL"
    assert restored.envelope.confidence == Confidence.MEDIUM
    assert restored.subgoals[0].intent == Intent.EXPANSION_RANK
    assert restored.unsupported_parts[0].text == "buy AAL"


def test_empty_packages_importable() -> None:
    import navaid.agent
    import navaid.api
    import navaid.ingest
    import navaid.net
    import navaid.rag
    import navaid.scoring
    import navaid.ui
    import navaid.warehouse

    sql = navaid.warehouse.schema_sql()
    assert "CREATE TABLE IF NOT EXISTS sessions" in sql
    assert "CREATE TABLE IF NOT EXISTS doc_chunks" in sql
    assert "CREATE TABLE IF NOT EXISTS embeddings" not in sql


def test_cli_ask_json(capsys) -> None:
    from navaid.cli import main

    assert main(["ask", "--json"]) == 2
    assert "requires a question" in capsys.readouterr().err
