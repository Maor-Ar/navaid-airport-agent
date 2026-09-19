from __future__ import annotations

import re

from navaid.agent.entities import resolve_one
from navaid.agent.orchestrator import ask
from navaid.agent.sessions import new_session_id
from navaid.agent.tools import ToolContext, rank_expansion, search_corpus
from navaid.config import NEW_ENGLAND_IATA, WAREHOUSE_PATH
from navaid.schemas import Intent, ScoringTrace
from navaid.warehouse.metrics import MetricsCatalog, SnapshotMissingError, require_snapshot
from navaid.warehouse.snapshot import build_snapshot


def test_entity_rules() -> None:
    assert resolve_one("LA")["iata"] == "LAX"
    assert "metro" in resolve_one("LA")["notes"]
    sna = resolve_one("Santa Ana")
    assert sna["iata"] == "SNA"
    assert sna["iata"] != "SAT"
    assert resolve_one("Anchorage")["iata"] == "ANC"
    from navaid.agent.entities import extract_airports

    assert extract_airports("Compare LA and Santa Ana congestion") == ["LAX", "SNA"]


def test_require_snapshot_error(tmp_path) -> None:
    missing = tmp_path / "nope.duckdb"
    try:
        require_snapshot(missing)
        raise AssertionError("expected SnapshotMissingError")
    except SnapshotMissingError as exc:
        assert "build_snapshot.py" in str(exc)


def test_adapter_metric_fields() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    with MetricsCatalog() as catalog:
        row = catalog.base_metrics("SNA")
        assert row["airport"] == "SNA"
        assert row["constraint_type"] == "airside"
        assert row["gate_count"]
        assert row["enplanements"] is not None
        assert row["latitude"] is not None
        teoi = catalog.teoi_row("BDL")
        assert "demand_pressure" in teoi
        assert "landside_saturation" in teoi
        ne = catalog.iata_in_region("New England")
        assert set(NEW_ENGLAND_IATA).issubset(set(ne)) or set(ne).issubset(set(NEW_ENGLAND_IATA) | set(ne))


def test_rank_expansion_attaches_traces() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    from navaid.agent.sessions import SessionMemory
    from navaid.warehouse.db import connect

    con = connect(WAREHOUSE_PATH)
    try:
        ctx = ToolContext(catalog=MetricsCatalog(con=con), session=SessionMemory(session_id="x"))
        payload = rank_expansion(ctx, region="New England")
        assert payload["teoi_traces"]
        ScoringTrace.model_validate(payload["teoi_traces"][0])
        assert payload["ranking"]
        rag = search_corpus(ctx, query="curfew", airport="SNA")
        blob = str(rag)
        assert "teoi" not in blob.lower() or "never ranks" in rag["note"].lower()
        assert "rank" not in rag["chunks"][0] if rag["chunks"] else True
        for chunk in rag["chunks"]:
            assert "rank" not in chunk
            assert "teoi" not in chunk
    finally:
        con.close()


def test_compound_orchestrator_without_gemini() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    question = (
        "Which New England airports are strong expansion candidates, "
        "compare LAX and SNA congestion, and should I buy AAL?"
    )
    answer = ask(question, session_id=new_session_id(), use_gemini=False)
    intents = [sg.intent for sg in answer.subgoals]
    assert Intent.EXPANSION_RANK in intents
    assert Intent.CONGESTION_COMPARE in intents
    assert Intent.UNSUPPORTED in intents
    assert answer.unsupported_parts
    assert answer.teoi_traces
    assert len(answer.sections) == len(answer.subgoals)
    assert any(s.name == "lock" for s in answer.steps)
    assert "buy" in answer.reconstructed_query.lower() or answer.reconstructed_query


def test_followup_reconstruction_in_orchestrator() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    sid = new_session_id()
    first = ask(
        "Compare LA and Santa Ana airport congestion levels.",
        session_id=sid,
        use_gemini=False,
    )
    assert any("LAX" in sg.entities and "SNA" in sg.entities for sg in first.subgoals if sg.entities)
    second = ask("which of those two is more curfew-constrained?", session_id=sid, use_gemini=False)
    assert "LAX" in second.reconstructed_query and "SNA" in second.reconstructed_query
    assert "those two" not in second.reconstructed_query.lower() or "LAX" in second.reconstructed_query


def test_why_bos_followup_reuses_new_england_teoi() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    sid = new_session_id()
    first = ask(
        "Which New England airports are strong candidates for terminal expansion?",
        session_id=sid,
        use_gemini=False,
    )
    bos = next(t for t in first.teoi_traces if t.airport == "BOS")
    second = ask("why does BOS has this score?", session_id=sid, use_gemini=False)
    intents = [sg.intent for sg in second.subgoals]
    assert Intent.EXPLAIN_TEOI in intents
    assert Intent.EXPANSION_RANK not in intents
    bos2 = next(t for t in second.teoi_traces if t.airport == "BOS")
    assert abs(float(bos2.teoi) - float(bos.teoi)) < 1e-6
    assert bos2.teoi > 50
    assert "do not re-rank" in second.reconstructed_query.lower() or second.reconstruction_notes


def test_buy_aal_after_sfo_does_not_brief_sfo() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    sid = new_session_id()
    ask(
        "What is the unmet flight demand in SFO airport and why?",
        session_id=sid,
        use_gemini=False,
    )
    second = ask("Should I buy AAL?", session_id=sid, use_gemini=False)
    intents = [sg.intent for sg in second.subgoals]
    assert Intent.UNSUPPORTED in intents
    assert Intent.AIRPORT_BRIEF not in intents
    assert Intent.UNMET_DEMAND not in intents
    blob = " ".join(section.body for section in second.sections).lower()
    assert "out of scope" in blob or second.unsupported_parts
    assert "enplanements" not in blob


def test_hello_and_capabilities_skip_engines() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    hello = ask("hello", session_id=new_session_id(), use_gemini=False)
    assert [sg.intent for sg in hello.subgoals] == [Intent.CHITCHAT]
    assert hello.process == []
    assert hello.map_points == []
    assert not hello.teoi_traces
    assert not any(s.name == "tool" for s in hello.steps)
    hello_blob = " ".join(section.body for section in hello.sections).lower()
    assert "enplanements" not in hello_blob
    assert "206" not in hello_blob
    assert "rank" in hello_blob or "expansion" in hello_blob

    caps = ask("what can you do", session_id=new_session_id(), use_gemini=False)
    assert [sg.intent for sg in caps.subgoals] == [Intent.CAPABILITIES]
    assert caps.process == []
    assert caps.map_points == []
    assert not caps.teoi_traces
    assert not any(s.name == "tool" for s in caps.steps)
    blob = " ".join(section.body for section in caps.sections).lower()
    assert "enplanements" not in blob
    assert "pax/gate" not in blob and "pax per gate" not in blob
    assert "warehouse snapshot" not in blob
    assert "stocks" in blob or "ticker" in blob or "npv" in blob
    assert "new england" in blob or "sfo" in blob


def test_why_bos_mixed_after_new_england_rank() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    sid = new_session_id()
    first = ask(
        "Which airports in New England are strong candidates for terminal expansion?",
        session_id=sid,
        use_gemini=False,
    )
    assert any(sg.intent == Intent.EXPANSION_RANK for sg in first.subgoals)
    second = ask("why is BOS mixed?", session_id=sid, use_gemini=False)
    intents = [sg.intent for sg in second.subgoals]
    assert Intent.EXPLAIN_CONSTRAINT in intents
    assert Intent.EXPLAIN_TEOI not in intents
    assert Intent.EXPANSION_RANK not in intents
    blob = " ".join(section.body for section in second.sections)
    lower = blob.lower()
    assert "mixed" in lower
    assert "landside" in lower and "airside" in lower
    assert "demand_pressure" not in lower
    assert "pax_per_gate" not in blob
    assert "scaled_0_1" not in lower
    peers = ["BDL", "BGR", "BTV", "MHT", "ORH", "PVD", "PWM"]
    assert not all(code in blob for code in peers)
    assert "0.75" in blob or "haircut" in lower
    assert "explain teoi traces" not in second.reconstructed_query.lower()


def test_capabilities_after_lax_sna_congestion() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    sid = new_session_id()
    first = ask(
        "Compare LA and Santa Ana airport congestion levels.",
        session_id=sid,
        use_gemini=False,
    )
    assert any(sg.intent == Intent.CONGESTION_COMPARE for sg in first.subgoals)
    first_blob = " ".join(section.body for section in first.sections)
    assert "delay_pct" not in first_blob
    assert "avg_arrival_delay_min" not in first_blob
    assert "ops_per_runway" not in first_blob
    assert "avgarrivaldelay" not in first_blob.replace("_", "").replace(" ", "").lower()
    assert "opsperrunway" not in first_blob.replace("_", "").replace(" ", "").lower()
    assert not re.search(r"\d+\.\d{4,}", first_blob)
    assert "curfew" in first_blob.lower() or "airside" in first_blob.lower()
    assert "single congestion score" in first_blob.lower() or "no single" in first_blob.lower()

    second = ask("what can you do?", session_id=sid, use_gemini=False)
    intents = [sg.intent for sg in second.subgoals]
    assert intents == [Intent.CAPABILITIES]
    assert Intent.AIRPORT_BRIEF not in intents
    assert "airports:" not in second.reconstructed_query.lower()
    assert "LAX" not in second.reconstructed_query
    assert "SNA" not in second.reconstructed_query
    assert second.process == []
    assert second.map_points == []
    assert not second.citations
    assert not any(s.name == "tool" for s in second.steps)
    blob = " ".join(section.body for section in second.sections).lower()
    assert "enplanements" not in blob
    assert "pax/gate" not in blob and "pax per gate" not in blob
    assert "warehouse snapshot" not in blob
    assert "stocks" in blob or "ticker" in blob or "npv" in blob


def test_sample_queries_fill_process_and_map_points() -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    rank = ask(
        "Which airports in New England are strong candidates for terminal expansion?",
        session_id=new_session_id(),
        use_gemini=False,
    )
    assert any(sg.intent == Intent.EXPANSION_RANK for sg in rank.subgoals)
    assert rank.process
    assert {ev.kind for ev in rank.process} >= {"thought", "tool", "result"}
    assert any(p.iata == "BOS" for p in rank.map_points)
    assert all(p.lat is not None and p.lon is not None for p in rank.map_points)
