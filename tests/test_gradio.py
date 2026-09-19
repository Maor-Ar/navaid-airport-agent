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
)
from navaid.ui.gradio_app import TABS, default_tools_only, fetch_eval_summary
from navaid.ui.render import (
    WATERFALL_STAGES,
    chat_reply,
    citations_markdown,
    compare_markdown,
    envelope_html,
    envelope_markdown,
    ranking_badges_html,
    ranking_frame,
    steps_markdown,
    waterfall_html,
    waterfall_markdown,
)
from navaid.ui.voice import STT_FALLBACK, transcribe


def _renormalized_weights(dropped: list[str]) -> dict[str, float]:
    remaining = {k: v for k, v in TEOI_WEIGHTS.items() if k not in dropped}
    total = sum(remaining.values())
    return {k: v / total for k, v in remaining.items()}


def _trace() -> ScoringTrace:
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
    return ScoringTrace(
        airport="BDL",
        peer_set=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"],
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
        formula_text="TEOI = 100 * (weights) * 1.00",
    )


def _answer() -> Answer:
    trace = _trace()
    return Answer(
        reconstructed_query="Which airports in New England are strong candidates for terminal expansion?",
        reconstruction_notes="First turn; reconstruction is a no-op.",
        subgoals=[
            Subgoal(
                intent=Intent.EXPANSION_RANK,
                entities=["BOS", "BDL"],
                status=SubgoalStatus.ANSWERED,
            )
        ],
        steps=[
            Step(index=1, name="reconstruct", detail="n/a (first turn)"),
            Step(index=2, name="tool", detail="rank_expansion(region=New England)"),
            Step(index=3, name="lock", detail="all numeric tokens present in tool JSON / traces"),
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
                {
                    "rank": 2,
                    "airport": "BDL",
                    "icao": "KBDL",
                    "teoi": trace.teoi,
                    "constraint_type": "landside",
                }
            ],
            "congestion": {
                "airports": ["LAX", "SNA"],
                "metrics": {
                    "LAX": {
                        "delay_pct": 0.22,
                        "avg_arrival_delay_min": 14.0,
                        "cancel_pct": 0.03,
                        "ops_per_runway": 120.0,
                        "live_faa_status": "normal",
                        "constraint_type": "mixed",
                    },
                    "SNA": {
                        "delay_pct": 0.18,
                        "avg_arrival_delay_min": 11.0,
                        "cancel_pct": 0.02,
                        "ops_per_runway": 210.0,
                        "live_faa_status": "normal",
                        "constraint_type": "airside",
                    },
                },
                "winner_on_each_axis": {
                    "delay_pct": "LAX",
                    "constraint_type": "SNA",
                },
            },
        },
        envelope=Envelope(
            assumptions=["US commercial primary airports"],
            uncertainties=["capital_feasibility dropped (missing NPIAS)"],
            out_of_scope=["PFC / NPV / airline equity"],
            confidence=Confidence.MEDIUM,
            sources=["FAA enplanements", "BTS delay-cause"],
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


def test_tabs_and_cli_ui_parser() -> None:
    from navaid.cli import _build_parser

    assert TABS == (
        "Chat",
        "Steps",
        "Rankings",
        "TEOI waterfall",
        "Compare",
        "Citations",
        "Eval",
    )
    ns = _build_parser().parse_args(["ui", "--port", "7861"])
    assert ns.command == "ui"
    assert ns.port == 7861
    assert ns.host == "127.0.0.1"


def test_render_envelope_steps_ranking_waterfall_compare_citations() -> None:
    answer = _answer()
    env = envelope_html(answer.envelope)
    for token in ("assumptions", "uncertainties", "Out of scope", "medium", "2024-12-31", "FAA enplanements"):
        assert token.lower() in env.lower() or token in env
    md = envelope_markdown(answer.envelope)
    assert "Assumptions" in md and "Uncertainties" in md and "Out of scope" in md

    steps = steps_markdown(answer)
    assert "reconstruct" in steps
    assert "lock" in steps
    assert "rank_expansion" in steps

    headers, rows = ranking_frame(answer)
    assert "constraint" in headers
    assert rows[0][1] == "BDL"
    badges = ranking_badges_html(answer)
    assert "landside" in badges.lower()
    assert "BDL" in badges
    assert CONSTRAINT_EXPLANATIONS["landside"] in badges
    assert "navaid-constraint-why" in badges

    water = waterfall_markdown(answer.teoi_traces, "BDL")
    for stage in WATERFALL_STAGES:
        assert stage.split()[0].lower() in water.lower()
    assert "raw" in water.lower()
    assert "scaled" in water.lower()
    assert "weight" in water.lower()
    assert "contribution" in water.lower()
    assert "multiplier" in water.lower()
    assert "rank" in water.lower()
    assert "BDL" in water
    assert str(answer.teoi_traces[0].rank) in water
    assert CONSTRAINT_EXPLANATIONS["landside"] in water

    html_water = waterfall_html(answer.teoi_traces, "BDL")
    assert CONSTRAINT_EXPLANATIONS["landside"] in html_water
    assert "navaid-constraint-why" in html_water

    compare = compare_markdown(answer)
    assert "LAX" in compare and "SNA" in compare
    assert "constraint" in compare.lower()
    assert "no composite" in compare.lower() or "no composite congestion" in compare.lower() or "No composite" in compare
    assert CONSTRAINT_EXPLANATIONS["mixed"] in compare
    assert CONSTRAINT_EXPLANATIONS["airside"] in compare

    cites = citations_markdown(answer)
    assert "FAA CY passenger boardings" in cites

    reply = chat_reply(answer)
    assert "buy AAL" in reply
    assert "landside" in reply.lower() or "BDL" in reply
    assert "Reconstructed" not in reply
    assert "EXPANSION_RANK" not in reply


def test_eval_summary_stub_and_voice_fallback(monkeypatch) -> None:
    payload = fetch_eval_summary()
    assert payload.get("status") in {"stub", "error"} or "status" in payload
    monkeypatch.setattr("navaid.ui.voice.gemini_configured", lambda: False)
    text, note = transcribe(None)
    assert text == ""
    assert "GEMINI_API_KEY" in STT_FALLBACK
    text2, note2 = transcribe("unused")
    assert text2 == ""
    from navaid.ui.voice import synthesize_wav_bytes

    data, note = synthesize_wav_bytes("")
    assert data is None
    assert "Nothing" in note or "speak" in note.lower()


def test_tools_only_default_tracks_key(monkeypatch) -> None:
    monkeypatch.setattr("navaid.ui.gradio_app.gemini_configured", lambda: False)
    assert default_tools_only() is True
    monkeypatch.setattr("navaid.ui.gradio_app.gemini_configured", lambda: True)
    assert default_tools_only() is False


def test_build_app_constructs() -> None:
    from navaid.ui.gradio_app import build_app

    demo = build_app()
    assert demo is not None
    title = getattr(demo, "title", "") or ""
    assert "Navaid" in str(title)
