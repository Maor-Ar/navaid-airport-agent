from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi.testclient import TestClient

from navaid.api.app import create_app, load_eval_summary
from navaid.config import PROJECT_ROOT, WAREHOUSE_PATH
from navaid.warehouse.snapshot import build_snapshot

RUN_EVAL_PATH = PROJECT_ROOT / "eval" / "run_eval.py"
GOLD_PATH = PROJECT_ROOT / "eval" / "gold" / "questions.jsonl"


def _runner():
    spec = importlib.util.spec_from_file_location("navaid_run_eval", RUN_EVAL_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gold_set_covers_required_families() -> None:
    runner = _runner()
    items = runner.load_gold(GOLD_PATH)
    assert len(items) >= 40
    ids = {item["id"] for item in items}
    families = {item.get("family") for item in items}
    assert {"assignment", "compound", "followup", "adversarial", "envelope"} <= families
    required = {
        "assign_ne_expansion",
        "assign_lax_sna_congestion",
        "assign_anc_longhaul",
        "assign_sfo_unmet",
        "compound_ne_lax_buy_aal",
        "fu_those_two",
        "fu_why_rank_2",
        "fu_add_pwm",
        "adv_buy_aal",
        "adv_restaurant_lax",
        "adv_empty_icao",
        "adv_santa_ana_vs_san_antonio",
        "adv_la_is_lax",
        "env_missing_gates_sat",
        "env_live_congestion",
    }
    assert required <= ids
    ne = next(item for item in items if item["id"] == "assign_ne_expansion")
    core = {"BOS", "BDL", "PVD", "PWM", "MHT"}
    listed = set(ne.get("entity_min") or []) | set(ne.get("expected_entities") or [])
    assert core <= listed
    assert ne.get("require_teoi_traces") is True


def test_kendall_tau_helper() -> None:
    runner = _runner()
    order = ["BDL", "PVD", "PWM"]
    assert runner.kendall_tau(order, order) == 1.0
    assert runner.kendall_tau(order, ["PWM", "PVD", "BDL"]) == -1.0
    assert runner.kendall_tau(["A"], ["A"]) is None


def test_run_eval_offline_and_summary(tmp_path: Path) -> None:
    if not WAREHOUSE_PATH.is_file():
        build_snapshot(offline=True, force_fixtures=True)
    runner = _runner()
    payload = runner.run_eval(
        gold_path=GOLD_PATH,
        use_gemini=False,
        runs_dir=tmp_path,
    )
    assert payload["item_count"] == len(runner.load_gold())
    kpis = payload["kpis"]
    assert kpis["n_items"] >= 40
    assert kpis["subgoal_coverage"] is not None and kpis["subgoal_coverage"] >= 0.9
    assert kpis["hallucination_rate"] is not None and kpis["hallucination_rate"] <= 0.25
    assert kpis["envelope_completeness"] is not None and kpis["envelope_completeness"] >= 0.9
    assert kpis["pass_rate"] >= 0.85
    summary = load_eval_summary(tmp_path)
    assert summary["status"] == "ok"
    assert summary["item_count"] == payload["item_count"]
    client = TestClient(create_app())
    live = client.get("/eval/summary")
    assert live.status_code == 200
    assert live.json()["status"] in {"ok", "no_runs"}
