from __future__ import annotations

from navaid.config import CONSTRAINT_EXPLANATIONS
from navaid.agent.narrate import parse_gemini_sections, template_section
from navaid.schemas import Intent, Subgoal, SubgoalStatus


def test_parse_gemini_sections_keeps_markdown_lists() -> None:
    text = (
        "===SECTION 0===\n"
        "EXPLAIN_TEOI: BOS\n"
        "### Why the score depends on the other airports\n"
        "\n"
        "- Highest in S scales to **1**\n"
        "- Lowest scales to **0**\n"
        "\n"
        "Peer set: BOS, BDL.\n"
    )
    sections = parse_gemini_sections(text, [Subgoal(intent=Intent.EXPLAIN_TEOI, entities=["BOS"])])
    assert sections is not None
    assert "EXPLAIN_TEOI" not in sections[0].heading
    assert "BOS" in sections[0].heading
    assert "### Why the score" in sections[0].body
    assert "- Highest in S" in sections[0].body
    assert "\n" in sections[0].body


def test_explain_template_uses_markdown() -> None:
    subgoal = Subgoal(
        intent=Intent.EXPLAIN_TEOI,
        entities=["BOS"],
        status=SubgoalStatus.ANSWERED,
        query="explain",
    )
    payload = {
        "result": {
            "reused_traces": True,
            "peer_set": ["BOS", "BDL"],
            "teoi_traces": [
                {
                    "airport": "BOS",
                    "teoi": 69.77,
                    "rank": 1,
                    "constraint_type": "mixed",
                    "constraint_multiplier": 0.75,
                }
            ],
        }
    }
    section = template_section(subgoal, payload, 0)
    assert "Why these scores" in section.heading
    assert "EXPLAIN_TEOI" not in section.heading
    assert "- **BOS**" in section.body
    assert "peer-relative" in section.body.lower() or "comparison set" in section.body.lower()
    assert CONSTRAINT_EXPLANATIONS["mixed"] in section.body
    assert "partially unlocks capacity" in section.body


def test_expansion_heading_is_human() -> None:
    section = template_section(
        Subgoal(intent=Intent.EXPANSION_RANK, entities=["BOS", "BDL"], query="rank"),
        {
            "result": {
                "peer_set": ["BOS", "BDL"],
                "ranking": [
                    {"rank": 1, "airport": "BDL", "teoi": 61.2, "constraint_type": "landside"},
                    {"rank": 2, "airport": "BOS", "teoi": 37.4, "constraint_type": "mixed"},
                ],
            }
        },
        0,
    )
    assert section.heading.startswith("Terminal expansion ranking")
    assert "EXPANSION_RANK" not in section.heading
    assert "61.2" in section.body
    assert "Stronger" in section.body or "Ranking" in section.body
    assert "landside" in section.body.lower()
    assert "61.2" in section.body
    assert "61.20000" not in section.body


def test_capabilities_template_is_not_warehouse_dump() -> None:
    section = template_section(
        Subgoal(intent=Intent.CAPABILITIES, query="what can you do"),
        {"meta": True},
        0,
    )
    assert "Navaid" in section.heading
    assert "What I can do" not in section.heading
    assert "CAPABILITIES" not in section.heading
    blob = section.body.lower()
    assert "warehouse snapshot" not in blob
    assert "enplanements" not in blob
    assert "npv" in blob or "stocks" in blob
    assert "new england" in blob
    assert "teoi" not in blob
    assert "gemini" not in blob
    assert "trading desk" not in blob
    assert "i refuse" not in blob
    assert "deterministic" not in blob
    assert "axis by axis" in blob
    assert "no single congestion score" in blob
    assert "long-haul" in blob
    assert "unmet" in blob
    assert "anchorage" in blob
    assert "santa ana" in blob
    assert "sfo" in blob
    assert "web search" in blob
    bullets = [ln for ln in section.body.splitlines() if ln.strip().startswith("-")]
    assert len(bullets) >= 4
    assert "help you" in blob
    assert "lax" not in blob
    assert "sna" not in blob


def test_chitchat_template_matches_product_voice() -> None:
    section = template_section(
        Subgoal(intent=Intent.CHITCHAT, query="hello"),
        {"meta": True},
        0,
    )
    assert "Hello" in section.heading
    blob = section.body.lower()
    assert "navaid" in blob
    assert "expansion" in blob or "rank" in blob
    assert "gemini" not in blob
    assert "teoi" not in blob
    assert "trading desk" not in blob
    assert "enplanements" not in blob
    bullets = [ln for ln in section.body.splitlines() if ln.strip().startswith("-")]
    assert len(bullets) >= 3
    assert "what i can do" in blob
    assert "help you" in blob


def test_longhaul_leads_with_flight_segment() -> None:
    section = template_section(
        Subgoal(intent=Intent.LONGHAUL_SHARE, entities=["ANC"], query="long haul"),
        {
            "result": {
                "airport": "ANC",
                "pct_longhaul": 12.34,
                "pct_longhaul_flights": 8.5,
                "pct_international": 40.0,
                "threshold_km": 4000,
                "passengers_total": 1000,
                "passengers_longhaul": 123,
                "segments_counted": 20,
                "segments_longhaul": 2,
                "cargo_excluded": True,
                "anc_jfk_km": 5420,
            }
        },
        0,
    )
    flight_at = section.body.lower().index("flight-segment")
    pax_at = section.body.lower().index("passenger share")
    assert flight_at < pax_at
    assert "5420" in section.body
    assert "sample" in section.body.lower()


def test_unmet_sfo_gates_leakage_when_lf_low() -> None:
    section = template_section(
        Subgoal(intent=Intent.UNMET_DEMAND, entities=["SFO"], query="unmet"),
        {
            "result": {
                "airport": "SFO",
                "unmet": 1000,
                "served": 20000,
                "lf_gap": 0,
                "taf_gap": 1000,
                "leakage": 0,
                "leakage_peers": ["OAK", "SJC"],
                "leakage_gated": True,
                "load_factor": 0.807,
                "lf_threshold": 0.85,
                "constraint_type": "mixed",
            }
        },
        0,
    )
    blob = section.body.lower()
    assert "qualitative" in blob
    assert "not a missing concourse" in blob or "not a concourse" in blob
    assert "80.7%" in section.body or "80.7" in section.body


def test_constraint_template_explains_classifier() -> None:
    section = template_section(
        Subgoal(intent=Intent.EXPLAIN_CONSTRAINT, entities=["BOS"], query="why mixed"),
        {
            "result": {
                "airport": "BOS",
                "constraint_type": "mixed",
                "constraint_multiplier": 0.75,
                "constraint_explanation": CONSTRAINT_EXPLANATIONS["mixed"],
                "constraint_notes": "Logan is both landside-constrained and airside-constrained.",
                "gate_count": 102,
                "pax_per_gate": 200000,
                "delay_pct": 0.24,
                "load_factor": 0.84,
            }
        },
        0,
    )
    blob = section.body.lower()
    assert "mixed" in blob
    assert "landside" in blob and "airside" in blob
    assert "0.75" in section.body
    assert "haircut" in blob or "later" in blob
    assert "demand_pressure" not in blob
    assert "teoi traces" in blob or "score math" in blob
    assert "EXPLAIN_CONSTRAINT" not in section.heading
    assert "BOS" in section.heading or "constraint" in section.heading.lower()


def test_congestion_template_is_a_story() -> None:
    section = template_section(
        Subgoal(intent=Intent.CONGESTION_COMPARE, entities=["LAX", "SNA"], query="compare"),
        {
            "result": {
                "airports": ["LAX", "SNA"],
                "winner_on_each_axis": {
                    "delay_pct": "LAX",
                    "ops_per_runway": "LAX",
                    "constraint_type": "SNA",
                },
                "metrics": {
                    "LAX": {
                        "delay_pct": 0.221234,
                        "avg_arrival_delay_min": 18.4,
                        "ops_per_runway": 120000,
                        "constraint_type": "mixed",
                    },
                    "SNA": {
                        "delay_pct": 0.18,
                        "avg_arrival_delay_min": 12.0,
                        "ops_per_runway": 80000,
                        "constraint_type": "airside",
                        "curfew": "22:00-07:00",
                    },
                },
            }
        },
        0,
    )
    blob = section.body
    lower = blob.lower()
    assert "delay_pct" not in blob
    assert "avg_arrival_delay_min" not in blob
    assert "ops_per_runway" not in blob
    assert "0.221234" not in blob
    assert "no single congestion score" in lower or "not a single" in lower
    assert "curfew" in lower
    assert "22:00" in blob or "22:00-07:00" in blob
    assert "airside" in lower
    assert "lax" in lower and "sna" in lower


def test_map_display_template_is_short_confirmation() -> None:
    section = template_section(
        Subgoal(intent=Intent.FOLLOW_UP, entities=["SFO"], query="show SFO on the map"),
        {"map": True, "airports": ["SFO"]},
        0,
    )
    assert "FOLLOW_UP" not in section.heading
    blob = section.body.lower()
    assert "sfo" in blob
    assert "map" in blob
    assert "warehouse snapshot" not in blob
    assert "66.8" not in section.body
    assert "pct_longhaul" not in blob
    assert "enplanements" not in blob
    sentences = [part for part in section.body.replace("!", ".").split(".") if part.strip()]
    assert 1 <= len(sentences) <= 3
