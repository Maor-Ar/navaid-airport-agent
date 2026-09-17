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
            {"airport": "BOS", "rank": 1, "teoi": 69.77, "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
            {"airport": "BDL", "rank": 2, "teoi": 61.2, "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
            {"airport": "PVD", "rank": 3, "teoi": 55.0, "peer_set": ["BOS", "BDL", "PVD", "PWM", "MHT", "BTV"]},
        ],
        intent="EXPANSION_RANK",
    )
    return memory


def test_first_turn_is_noop() -> None:
    rec = reconstruct("Compare LA and Santa Ana congestion", SessionMemory(session_id="empty"))
    assert rec.independent
    assert rec.reconstructed_query.startswith("Compare LA")
    assert "no-op" in rec.notes


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
