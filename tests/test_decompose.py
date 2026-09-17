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
