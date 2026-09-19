from __future__ import annotations

from navaid.agent.reconstruct import reconstruct
from navaid.agent.sessions import SessionMemory


def _session_after_congestion() -> SessionMemory:
    memory = SessionMemory(session_id="t1")
    memory.remember(
        question="Compare LA and Santa Ana congestion",
        reconstructed_query="Compare LA and Santa Ana congestion",
        entities=["LAX", "SNA"],
        peer_set=["LAX", "SNA"],
        payloads={"compare_congestion": {"airports": ["LAX", "SNA"]}},
        intent="CONGESTION_COMPARE",
    )
    return memory


def _session_after_rank() -> SessionMemory:
    memory = SessionMemory(session_id="t2")
    memory.remember(
        question="Which New England airports are strong expansion candidates?",
        reconstructed_query="Which New England airports are strong expansion candidates?",
        entities=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"],
        peer_set=["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"],
        traces=[
            {"airport": "BOS", "rank": 1, "teoi": 69.77, "constraint_type": "mixed", "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
            {"airport": "BDL", "rank": 2, "teoi": 61.2, "constraint_type": "landside", "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
            {"airport": "PVD", "rank": 3, "teoi": 55.0, "constraint_type": "landside", "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
        ],
        intent="EXPANSION_RANK",
    )
    return memory


def _session_after_capabilities() -> SessionMemory:
    memory = SessionMemory(session_id="t-caps")
    memory.remember(
        question="what can you do?",
        reconstructed_query="what can you do?",
        entities=[],
        intent="CAPABILITIES",
    )
    return memory


def _session_after_unmet_sfo() -> SessionMemory:
    memory = SessionMemory(session_id="t-unmet")
    memory.remember(
        question="What is the unmet flight demand in SFO airport and why?",
        reconstructed_query="What is the unmet flight demand in SFO airport and why?",
        entities=["SFO"],
        payloads={"unmet_demand": {"airport": "SFO"}},
        intent="UNMET_DEMAND",
    )
    return memory


def test_first_turn_is_noop() -> None:
    rec = reconstruct("Compare LA and Santa Ana congestion", SessionMemory(session_id="empty"))
    assert rec.independent
    assert rec.reconstructed_query.startswith("Compare LA")
    assert rec.notes == ""


def test_those_two_from_session() -> None:
    rec = reconstruct("which of those two is more curfew-constrained?", _session_after_congestion())
    assert rec.independent is False
    assert "LAX" in rec.reconstructed_query and "SNA" in rec.reconstructed_query
    assert rec.filled_airports == ["LAX", "SNA"]


def test_why_rank_reuses_traces() -> None:
    rec = reconstruct("why is #2 above #3?", _session_after_rank())
    assert rec.reuse_traces is True
    assert rec.rerun_ranker is False
    assert "rank 2" in rec.reconstructed_query
    assert "rank 3" in rec.reconstructed_query
    assert "BOS" in rec.reconstructed_query
    assert "reuse last TEOI traces" in rec.notes


def test_why_bos_score_reuses_traces() -> None:
    rec = reconstruct(
        "why does BOS has this score? **BOS** (Boston Logan International Airport) "
        "with a TEOI score of 69.77436297811967",
        _session_after_rank(),
    )
    assert rec.independent is False
    assert rec.reuse_traces is True
    assert rec.rerun_ranker is False
    assert "BOS" in rec.reconstructed_query
    assert "do not re-rank" in rec.reconstructed_query
    assert "reuse last TEOI traces" in rec.notes


def test_add_pwm_reruns_ranker() -> None:
    rec = reconstruct("add PWM", _session_after_rank())
    assert rec.rerun_ranker is True
    assert rec.reuse_traces is False
    assert "PWM" in rec.reconstructed_query
    assert rec.added_airports == ["PWM"]
    assert rec.filled_airports[-1] == "PWM" or "PWM" in rec.filled_airports


def test_buy_aal_does_not_inherit_last_airports() -> None:
    rec = reconstruct("Should I buy AAL?", _session_after_rank())
    assert rec.independent
    assert rec.filled_airports == []
    assert "BOS" not in rec.reconstructed_query
    assert rec.notes == ""


def test_named_airport_question_is_independent() -> None:
    rec = reconstruct("What is the unmet flight demand in SFO airport and why?", _session_after_rank())
    assert rec.independent
    assert rec.filled_airports == []
    assert rec.reconstructed_query.startswith("What is the unmet")


def test_hello_does_not_inherit_last_airports() -> None:
    rec = reconstruct("hello", _session_after_rank())
    assert rec.independent
    assert rec.filled_airports == []
    assert "BOS" not in rec.reconstructed_query
    assert rec.notes == ""


def test_capabilities_does_not_inherit_last_airports() -> None:
    rec = reconstruct("what can you do", _session_after_rank())
    assert rec.independent
    assert rec.filled_airports == []
    assert "BOS" not in rec.reconstructed_query


def test_capabilities_after_congestion_does_not_copy_airports() -> None:
    for question in ("what can you do?", "what do you do", "help", "who are you"):
        rec = reconstruct(question, _session_after_congestion())
        assert rec.independent, question
        assert rec.filled_airports == []
        assert "LAX" not in rec.reconstructed_query
        assert "SNA" not in rec.reconstructed_query
        assert "airports:" not in rec.reconstructed_query.lower()


def test_hello_after_congestion_does_not_copy_airports() -> None:
    rec = reconstruct("hello", _session_after_congestion())
    assert rec.independent
    assert rec.filled_airports == []
    assert "LAX" not in rec.reconstructed_query


def test_why_bos_mixed_is_constraint_not_teoi() -> None:
    for question in (
        "can you explain why and how you gave BOS the mixed constraint type?",
        "why is BOS mixed?",
        "explain why BOS is mixed",
        "why mixed at BOS",
    ):
        rec = reconstruct(question, _session_after_rank())
        assert rec.explain_constraint is True, question
        assert rec.reuse_traces is False, question
        assert rec.rerun_ranker is False, question
        assert "BOS" in rec.reconstructed_query
        assert "mixed" in rec.reconstructed_query.lower()
        assert "Explain TEOI traces" not in rec.reconstructed_query
        assert "do not re-rank a singleton" not in rec.reconstructed_query.lower()
        assert rec.filled_airports == ["BOS"]
        peer = ["BDL", "BGR", "BTV", "MHT", "ORH", "PVD", "PWM"]
        blob = rec.reconstructed_query
        assert not all(code in blob for code in peer), question


def test_last_option_after_capabilities_is_sfo_unmet() -> None:
    memory = _session_after_capabilities()
    for question in (
        'do the last option on the list you showed me "Estimate unmet passenger demand"',
        "do the last option",
        "the last one",
        "that last one",
        "the unmet one",
        "estimate unmet passenger demand",
        "estimate",
    ):
        rec = reconstruct(question, memory)
        assert rec.show_map is False, question
        assert rec.independent is False, question
        assert rec.filled_airports == ["SFO"], question
        assert "SFO" in rec.reconstructed_query, question
        assert "unmet" in rec.reconstructed_query.lower(), question
        assert "BOS" not in rec.reconstructed_query
        assert "(airports:" not in rec.reconstructed_query.lower()


def test_last_option_after_hello_is_sfo_unmet() -> None:
    memory = SessionMemory(session_id="t-hello")
    memory.remember(
        question="hey",
        reconstructed_query="hey",
        entities=[],
        intent="CHITCHAT",
    )
    rec = reconstruct("do the last option", memory)
    assert rec.filled_airports == ["SFO"]
    assert "unmet" in rec.reconstructed_query.lower()
    assert "SFO" in rec.reconstructed_query


def test_last_option_does_not_copy_prior_rank_airports() -> None:
    memory = _session_after_rank()
    memory.remember(
        question="what can you do?",
        reconstructed_query="what can you do?",
        entities=[],
        intent="CAPABILITIES",
    )
    rec = reconstruct("do the last option", memory)
    assert rec.filled_airports == ["SFO"]
    assert "BOS" not in rec.reconstructed_query
    assert "BDL" not in rec.reconstructed_query


def test_show_on_map_reuses_last_airport() -> None:
    for question in (
        "can you show me this airport on the map?",
        "show it on the map",
        "show this on the map",
        "show me this airport on the map",
    ):
        rec = reconstruct(question, _session_after_unmet_sfo())
        assert rec.show_map is True, question
        assert rec.filled_airports == ["SFO"], question
        assert "SFO" in rec.reconstructed_query
        assert "on the map" in rec.reconstructed_query.lower()
        assert "warehouse" not in rec.reconstructed_query.lower()
        assert rec.explain_constraint is False
        assert rec.reuse_traces is False
