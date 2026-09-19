from __future__ import annotations

from navaid.agent.decompose import decompose
from navaid.agent.reconstruct import reconstruct
from navaid.schemas import Intent


COMPOUND = (
    "Which New England airports are strong expansion candidates, "
    "compare LAX and SNA congestion, and should I buy AAL?"
)


def test_compound_question_keeps_all_parts() -> None:
    subgoals = decompose(COMPOUND)
    intents = [sg.intent for sg in subgoals]
    assert Intent.EXPANSION_RANK in intents
    assert Intent.CONGESTION_COMPARE in intents
    assert Intent.UNSUPPORTED in intents
    rank = next(sg for sg in subgoals if sg.intent == Intent.EXPANSION_RANK)
    congest = next(sg for sg in subgoals if sg.intent == Intent.CONGESTION_COMPARE)
    refused = next(sg for sg in subgoals if sg.intent == Intent.UNSUPPORTED)
    assert "BOS" in rank.entities or "BDL" in rank.entities
    assert set(congest.entities) >= {"LAX", "SNA"}
    assert "AAL" in refused.query or "buy" in refused.query.lower()
    assert intents.count(Intent.UNSUPPORTED) == 1


def test_single_longhaul_anchorage() -> None:
    subgoals = decompose("What is the percentage of long haul flights out of Anchorage airport?")
    assert len([s for s in subgoals if s.intent == Intent.LONGHAUL_SHARE]) == 1
    lh = subgoals[0]
    assert lh.intent == Intent.LONGHAUL_SHARE
    assert lh.entities == ["ANC"]


def test_unmet_sfo() -> None:
    subgoals = decompose("What is the unmet flight demand in SFO airport and why?")
    assert any(sg.intent == Intent.UNMET_DEMAND for sg in subgoals)
    unmet = next(sg for sg in subgoals if sg.intent == Intent.UNMET_DEMAND)
    assert unmet.entities == ["SFO"]


def test_why_bos_score_is_explain_not_rank() -> None:
    from navaid.agent.sessions import SessionMemory

    memory = SessionMemory(session_id="t-explain")
    memory.remember(
        question="Which New England airports are strong expansion candidates?",
        reconstructed_query="Which New England airports are strong expansion candidates?",
        entities=["BOS", "BDL"],
        peer_set=["BOS", "BDL", "PVD"],
        traces=[{"airport": "BOS", "rank": 1, "teoi": 69.77, "peer_set": ["BOS", "BDL", "PVD"]}],
        intent="EXPANSION_RANK",
    )
    rec = reconstruct(
        "why does BOS has this score? **BOS** with a TEOI score of 69.77",
        memory,
    )
    subgoals = decompose(rec.reconstructed_query, session=memory, reuse_traces=rec.reuse_traces)
    intents = [sg.intent for sg in subgoals]
    assert Intent.EXPLAIN_TEOI in intents
    assert Intent.EXPANSION_RANK not in intents


def test_hello_is_chitchat_not_brief() -> None:
    subgoals = decompose("hello")
    assert [sg.intent for sg in subgoals] == [Intent.CHITCHAT]


def test_what_can_you_do_is_capabilities_not_bos_brief() -> None:
    for question in ("what can you do", "Tell me what can you do", "who are you"):
        subgoals = decompose(question)
        assert [sg.intent for sg in subgoals] == [Intent.CAPABILITIES], question
        assert not subgoals[0].entities


def test_capabilities_ignores_copied_airport_suffix() -> None:
    subgoals = decompose("what can you do? (airports: LAX, SNA)")
    assert [sg.intent for sg in subgoals] == [Intent.CAPABILITIES]
    assert not subgoals[0].entities


def test_why_bos_mixed_is_constraint_not_teoi() -> None:
    from navaid.agent.sessions import SessionMemory

    memory = SessionMemory(session_id="t-constraint")
    memory.remember(
        question="Which New England airports are strong expansion candidates?",
        reconstructed_query="Which New England airports are strong expansion candidates?",
        entities=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV", "BGR", "ORH"],
        peer_set=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV", "BGR", "ORH"],
        traces=[
            {"airport": "BOS", "rank": 1, "teoi": 69.77, "constraint_type": "mixed"},
            {"airport": "BDL", "rank": 2, "teoi": 61.2, "constraint_type": "landside"},
        ],
        intent="EXPANSION_RANK",
    )
    rec = reconstruct("why is BOS mixed?", memory)
    subgoals = decompose(
        rec.reconstructed_query,
        session=memory,
        reuse_traces=rec.reuse_traces,
        explain_constraint=rec.explain_constraint,
    )
    intents = [sg.intent for sg in subgoals]
    assert Intent.EXPLAIN_CONSTRAINT in intents
    assert Intent.EXPLAIN_TEOI not in intents
    assert Intent.EXPANSION_RANK not in intents
    constraint = next(sg for sg in subgoals if sg.intent == Intent.EXPLAIN_CONSTRAINT)
    assert constraint.entities == ["BOS"]


def test_explain_why_bos_mixed_first_turn() -> None:
    subgoals = decompose("explain why BOS is mixed")
    assert any(sg.intent == Intent.EXPLAIN_CONSTRAINT for sg in subgoals)
    assert not any(sg.intent == Intent.EXPLAIN_TEOI for sg in subgoals)
    assert next(sg for sg in subgoals if sg.intent == Intent.EXPLAIN_CONSTRAINT).entities == ["BOS"]


def test_last_option_after_capabilities_decomposes_to_sfo_unmet() -> None:
    from navaid.agent.sessions import SessionMemory

    memory = SessionMemory(session_id="t-last-option")
    memory.remember(
        question="what can you do?",
        reconstructed_query="what can you do?",
        entities=[],
        intent="CAPABILITIES",
    )
    rec = reconstruct("do the last option", memory)
    subgoals = decompose(rec.reconstructed_query, session=memory)
    intents = [sg.intent for sg in subgoals]
    assert Intent.UNMET_DEMAND in intents
    assert Intent.AIRPORT_BRIEF not in intents
    unmet = next(sg for sg in subgoals if sg.intent == Intent.UNMET_DEMAND)
    assert unmet.entities == ["SFO"]


def test_show_on_map_is_follow_up_not_brief() -> None:
    from navaid.agent.sessions import SessionMemory

    memory = SessionMemory(session_id="t-map")
    memory.remember(
        question="What is the unmet flight demand in SFO airport and why?",
        reconstructed_query="What is the unmet flight demand in SFO airport and why?",
        entities=["SFO"],
        intent="UNMET_DEMAND",
    )
    rec = reconstruct("show me this airport on the map", memory)
    subgoals = decompose(
        rec.reconstructed_query,
        session=memory,
        show_map=rec.show_map,
    )
    assert [sg.intent for sg in subgoals] == [Intent.FOLLOW_UP]
    assert subgoals[0].entities == ["SFO"]
