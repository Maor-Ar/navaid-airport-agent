from __future__ import annotations

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
    assert sections[0].heading == "EXPLAIN_TEOI: BOS"
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
    assert "### Why the score depends on the other airports" in section.body
    assert "- **BOS**" in section.body
    assert "peer-relative" in section.body.lower() or "Peer set S" in section.body
