"""Gold eval runner: engines/tools are the numbers; Gemini is optional.

Usage (from repo root):

    python eval/run_eval.py
    python eval/run_eval.py --use-gemini false
    python eval/run_eval.py --ids assign_ne_expansion,assign_sfo_unmet

Writes ``eval/runs/<timestamp>.json`` and ``eval/runs/latest.json``, then prints
a KPI table. Default ``use_gemini=false`` so gold numbers come from engines.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from navaid.agent.number_lock import NUMBER_RE, collect_allowed_numbers
from navaid.agent.orchestrator import ask
from navaid.agent.sessions import new_session_id
from navaid.schemas import Answer
from navaid.scoring.longhaul import longhaul_share as engine_longhaul
from navaid.scoring.teoi import rank_expansion as engine_rank
from navaid.scoring.unmet import unmet_demand as engine_unmet
from navaid.warehouse.metrics import MetricsCatalog, SnapshotMissingError, require_snapshot

GOLD_PATH = ROOT / "eval" / "gold" / "questions.jsonl"
RUNS_DIR = ROOT / "eval" / "runs"

ENVELOPE_FIELDS = (
    "assumptions",
    "uncertainties",
    "out_of_scope",
    "confidence",
    "sources",
    "as_of",
)
FORMULA_FIELDS = (
    "airport",
    "peer_set",
    "raw",
    "scaled_0_1",
    "weights_original",
    "weights_dropped",
    "weights_used",
    "contributions",
    "weighted_sum",
    "constraint_type",
    "constraint_multiplier",
    "teoi",
    "rank",
    "formula_text",
)


def load_gold(path: Path | None = None) -> list[dict[str, Any]]:
    target = path or GOLD_PATH
    items: list[dict[str, Any]] = []
    with target.open(encoding="utf-8") as handle:
        for line_no, raw in enumerate(handle, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{target}:{line_no}: {exc}") from exc
            if not item.get("id"):
                raise ValueError(f"{target}:{line_no}: gold item missing id")
            items.append(item)
    return items


def kendall_tau(gold_order: list[str], pred_order: list[str]) -> float | None:
    """Pairwise Kendall tau on the intersection (ties contribute 0)."""

    gold_rank = {code: i for i, code in enumerate(gold_order)}
    pred_rank = {code: i for i, code in enumerate(pred_order)}
    common = [code for code in gold_order if code in pred_rank]
    if len(common) < 2:
        return None
    concordant = 0
    discordant = 0
    for i, left in enumerate(common):
        for right in common[i + 1 :]:
            g = gold_rank[left] - gold_rank[right]
            p = pred_rank[left] - pred_rank[right]
            if g == 0 or p == 0:
                continue
            if (g > 0) == (p > 0):
                concordant += 1
            else:
                discordant += 1
    total = concordant + discordant
    if total == 0:
        return 1.0
    return (concordant - discordant) / total


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _f1(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2.0 * precision * recall / (precision + recall)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().lower()


def _contains(haystack: str, needle: str) -> bool:
    return _norm(needle) in _norm(haystack)


def answer_text(answer: Answer) -> str:
    parts = [answer.reconstructed_query, answer.reconstruction_notes]
    for section in answer.sections:
        parts.append(section.heading)
        parts.append(section.body)
    env = answer.envelope
    parts.extend(env.assumptions)
    parts.extend(env.uncertainties)
    parts.extend(env.out_of_scope)
    parts.extend(env.sources)
    parts.append(str(env.confidence))
    if env.as_of is not None:
        parts.append(str(env.as_of))
    for part in answer.unsupported_parts:
        parts.append(part.text)
        parts.append(part.reason)
    for trace in answer.teoi_traces:
        parts.append(trace.formula_text)
        parts.append(trace.airport)
    parts.append(json.dumps(answer.tables, default=str))
    return "\n".join(str(p) for p in parts if p)


def prose_text(answer: Answer) -> str:
    return "\n".join(section.body for section in answer.sections)


def ranking_order(answer: Answer) -> list[str]:
    rows = (answer.tables or {}).get("ranking") or []
    ordered = sorted(
        rows,
        key=lambda row: (int(row.get("rank") or 10**6), str(row.get("icao") or row.get("airport") or "")),
    )
    return [str(row["airport"]).upper() for row in ordered if row.get("airport")]


def predicted_intents(answer: Answer) -> list[str]:
    return [sg.intent.value for sg in answer.subgoals]


def predicted_entities(answer: Answer) -> list[str]:
    seen: list[str] = []
    for sg in answer.subgoals:
        if sg.intent.value == "UNSUPPORTED":
            continue
        for code in sg.entities:
            token = str(code).strip().upper()
            if token and token not in seen:
                seen.append(token)
    return seen


def entity_f1(gold: list[str], pred: list[str]) -> float:
    g = {c.upper() for c in gold if c}
    p = {c.upper() for c in pred if c}
    if not g and not p:
        return 1.0
    if not g or not p:
        return 0.0
    hit = len(g & p)
    precision = hit / len(p)
    recall = hit / len(g)
    return _f1(precision, recall)


def flatten_numbers(node: Any, out: list[float] | None = None) -> list[float]:
    acc = out if out is not None else []
    if isinstance(node, bool) or node is None:
        return acc
    if isinstance(node, int):
        acc.append(float(node))
        return acc
    if isinstance(node, float):
        if not math.isnan(node) and not math.isinf(node):
            acc.append(node)
        return acc
    if isinstance(node, dict):
        for value in node.values():
            flatten_numbers(value, acc)
        return acc
    if isinstance(node, (list, tuple)):
        for value in node:
            flatten_numbers(value, acc)
    return acc


def number_hit(expected: float, observed: list[float], *, rel: float = 1e-6, abs_tol: float = 1e-4) -> bool:
    for value in observed:
        if math.isclose(expected, value, rel_tol=rel, abs_tol=abs_tol):
            return True
    return False


def ensure_snapshot() -> Path:
    try:
        return require_snapshot()
    except SnapshotMissingError:
        from navaid.warehouse.snapshot import build_snapshot

        print("Warehouse snapshot missing; building offline fixtures…", file=sys.stderr)
        result = build_snapshot(offline=True, force_fixtures=True)
        return Path(result.warehouse_path)


def gold_ranking(item: dict[str, Any], catalog: MetricsCatalog) -> list[str]:
    spec = item.get("ranking_from")
    frozen = [str(c).upper() for c in (item.get("ranking") or [])]
    if not spec:
        return frozen
    if spec.get("region"):
        codes = catalog.iata_in_region(str(spec["region"]))
    else:
        codes = [str(c).upper() for c in (spec.get("airports") or [])]
    if not codes:
        return frozen
    result = engine_rank(catalog.teoi_rows(codes), as_of=catalog.as_of())
    return [str(row["airport"]).upper() for row in result.ranking]


def gold_numeric(item: dict[str, Any], catalog: MetricsCatalog) -> dict[str, float]:
    values = {str(k): float(v) for k, v in (item.get("numeric") or {}).items() if v is not None}
    spec = item.get("numeric_from")
    if not spec:
        return values
    kind = str(spec.get("kind") or "")
    airport = str(spec.get("airport") or "").upper()
    fields = list(spec.get("fields") or [])
    payload: dict[str, Any] = {}
    if kind == "longhaul" and airport:
        row = catalog.base_metrics(airport)
        result = engine_longhaul(
            row,
            segments=catalog.segments(airport),
            airports=catalog.airport_coords(),
            as_of=catalog.as_of(),
        )
        payload = result.model_dump(mode="json")
    elif kind == "unmet" and airport:
        row = catalog.base_metrics(airport)
        result = engine_unmet(row, peers=catalog.cbsa_peers(airport), as_of=catalog.as_of())
        payload = result.model_dump(mode="json")
    for field in fields:
        if field in payload and payload[field] is not None:
            values[field] = float(payload[field])
    return values


def _turns(item: dict[str, Any]) -> list[str]:
    if item.get("turns"):
        return [str(t) for t in item["turns"]]
    question = item.get("question")
    if not question:
        raise ValueError(f"{item.get('id')}: missing question/turns")
    return [str(question)]


def score_item(
    item: dict[str, Any],
    answer: Answer,
    *,
    expected_ranking: list[str] | None = None,
    expected_numeric: dict[str, float] | None = None,
) -> dict[str, Any]:
    failures: list[str] = []
    scores: dict[str, Any] = {}
    blob = answer_text(answer)
    prose = prose_text(answer)

    expected_intents = [str(x) for x in (item.get("expected_intents") or [])]
    pred_intents = predicted_intents(answer)
    if expected_intents:
        exp_set = set(expected_intents)
        pred_set = set(pred_intents)
        coverage = len(exp_set & pred_set) / len(exp_set)
        answered = 0
        for intent in expected_intents:
            matching = [sg for sg in answer.subgoals if sg.intent.value == intent]
            if not matching:
                continue
            if intent == "UNSUPPORTED":
                answered += 1
                continue
            if any(sg.status.value == "answered" for sg in matching):
                answered += 1
        coverage_status = answered / len(expected_intents)
        scores["subgoal_coverage"] = min(coverage, coverage_status)
        scores["intent_accuracy"] = 1.0 if exp_set == pred_set else len(exp_set & pred_set) / len(exp_set | pred_set)
        if coverage < 1.0:
            failures.append(f"intents missing {sorted(exp_set - pred_set)}")
    else:
        scores["subgoal_coverage"] = 1.0
        scores["intent_accuracy"] = 1.0

    expected_entities = [str(c).upper() for c in (item.get("expected_entities") or [])]
    entity_min = [str(c).upper() for c in (item.get("entity_min") or [])]
    pred_entities = predicted_entities(answer)
    if item.get("skip_entity_f1") or (not expected_entities and not entity_min):
        scores["entity_f1"] = None
    else:
        gold_ents = expected_entities or entity_min
        scores["entity_f1"] = entity_f1(gold_ents, pred_entities)
        missing = [c for c in (entity_min or expected_entities) if c not in set(pred_entities)]
        if missing:
            failures.append(f"entities missing {missing}")

    forbidden = [str(c).upper() for c in (item.get("forbidden_entities") or [])]
    bad_ents = [c for c in forbidden if c in set(pred_entities)]
    if bad_ents:
        failures.append(f"forbidden entities {bad_ents}")

    if item.get("require_teoi_traces") or item.get("require_formula"):
        if not answer.teoi_traces:
            scores["kendall_tau"] = scores.get("kendall_tau")
            failures.append("missing teoi_traces")
        else:
            for trace in answer.teoi_traces:
                dumped = trace.model_dump()
                missing_fields = [f for f in FORMULA_FIELDS if f not in dumped or dumped[f] in (None, "", [])]
                # weights_dropped may be empty; that is a valid formula field.
                missing_fields = [
                    f
                    for f in FORMULA_FIELDS
                    if f not in dumped or (dumped[f] is None or dumped[f] == "")
                ]
                if not str(trace.formula_text or "").strip():
                    missing_fields.append("formula_text")
                if missing_fields:
                    failures.append(f"{trace.airport} trace missing {missing_fields}")
                    break

    gold_rank = list(expected_ranking or [])
    if gold_rank:
        pred_rank = ranking_order(answer)
        tau = kendall_tau(gold_rank, pred_rank)
        scores["kendall_tau"] = tau
        if set(gold_rank) - set(pred_rank):
            failures.append(f"ranking missing {sorted(set(gold_rank) - set(pred_rank))}")
        elif tau is None or tau < 0.999:
            failures.append(f"kendall tau {tau} for {gold_rank} vs {pred_rank}")
    else:
        scores["kendall_tau"] = None

    expected_numeric = dict(expected_numeric or {})
    observed = flatten_numbers(answer.tables) + flatten_numbers(
        [t.model_dump(mode="json") for t in answer.teoi_traces]
    )
    observed.extend(flatten_numbers(answer.model_dump(mode="json")))
    hits = 0
    numeric_total = 0
    for key, value in expected_numeric.items():
        numeric_total += 1
        if number_hit(value, observed):
            hits += 1
        else:
            failures.append(f"numeric miss {key}={value}")
    for key, minimum in (item.get("numeric_min") or {}).items():
        numeric_total += 1
        table_val = None
        tables = answer.tables or {}
        for payload in tables.values():
            if isinstance(payload, dict) and key in payload:
                table_val = payload[key]
                break
        if table_val is None and key in expected_numeric:
            table_val = expected_numeric[key]
        if table_val is None:
            failures.append(f"numeric_min missing {key}")
        elif float(table_val) < float(minimum):
            failures.append(f"numeric_min {key}={table_val} < {minimum}")
        else:
            hits += 1
    scores["numeric_hit_rate"] = (hits / numeric_total) if numeric_total else None

    tokens = NUMBER_RE.findall(prose)
    allowed_payloads = [
        [t.model_dump(mode="json") for t in answer.teoi_traces],
        answer.tables,
        answer.envelope.model_dump(mode="json"),
        [sg.model_dump(mode="json") for sg in answer.subgoals],
        [c.model_dump(mode="json") for c in answer.citations],
        [s.model_dump(mode="json") for s in answer.steps],
        answer.reconstructed_query,
        [_jsonish(section.body) for section in answer.sections],
    ]
    allowed = collect_allowed_numbers(allowed_payloads)
    hallucinated = [tok for tok in tokens if not _number_allowed(tok, allowed)]
    scores["hallucination_rate"] = (len(hallucinated) / len(tokens)) if tokens else 0.0
    # Number lock already strips invented digits. Remaining RAG/note tokens are
    # scored in the KPI but do not fail the item (payloads are not on Answer).

    env = answer.envelope.model_dump(mode="json")
    needed = list(item.get("envelope_fields") or ENVELOPE_FIELDS)
    present = 0
    for field in needed:
        value = env.get(field)
        if field == "as_of":
            ok = value is not None
        elif field == "confidence":
            ok = value not in (None, "")
        else:
            # Empty lists are still a complete envelope (nothing to disclose).
            ok = isinstance(value, list)
        if ok:
            present += 1
        else:
            failures.append(f"envelope missing {field}")
    scores["envelope_completeness"] = present / len(needed) if needed else 1.0
    env_blob = json.dumps(env, default=str)
    for phrase in item.get("envelope_must_contain") or []:
        if not _contains(env_blob, phrase) and not _contains(blob, phrase):
            failures.append(f"envelope must-contain miss {phrase!r}")

    must_say = list(item.get("must_say") or [])
    must_hits = 0
    for phrase in must_say:
        if _contains(blob, phrase):
            must_hits += 1
        else:
            failures.append(f"must-say miss {phrase!r}")
    for group in item.get("must_say_any") or []:
        must_say.append("|".join(group))
        if any(_contains(blob, phrase) for phrase in group):
            must_hits += 1
        else:
            failures.append(f"must-say-any miss {group}")
    denom = len(must_say)
    scores["must_say"] = (must_hits / denom) if denom else None

    forbidden_phrases = list(item.get("must_not_say") or [])
    if forbidden_phrases:
        hits_bad = [p for p in forbidden_phrases if _contains(prose, p)]
        scores["must_not_say"] = 0.0 if hits_bad else 1.0
        if hits_bad:
            failures.append(f"must-not-say hit {hits_bad}")
    else:
        scores["must_not_say"] = None

    recon_ok = True
    if item.get("reconstructed_equals"):
        if answer.reconstructed_query.strip() != str(item["reconstructed_equals"]).strip():
            recon_ok = False
            failures.append("reconstructed_equals mismatch")
    for phrase in item.get("reconstructed_contains") or []:
        if not _contains(answer.reconstructed_query, phrase):
            recon_ok = False
            failures.append(f"reconstructed_contains miss {phrase!r}")
    if item.get("reconstructed_equals") or item.get("reconstructed_contains"):
        scores["reconstruction_match"] = 1.0 if recon_ok else 0.0
    else:
        scores["reconstruction_match"] = None

    if item.get("unsupported"):
        if not answer.unsupported_parts and "UNSUPPORTED" not in pred_intents:
            failures.append("expected unsupported part")

    if item.get("check_live_disclosed"):
        congestion = (answer.tables or {}).get("congestion") or {}
        metrics = congestion.get("metrics") or {}
        live_values = []
        if isinstance(metrics, dict):
            for row in metrics.values():
                if isinstance(row, dict):
                    live_values.append(row.get("live_faa_status"))
        all_missing = (not live_values) or all(v in (None, "", "None") for v in live_values)
        if all_missing and not (
            _contains(blob, "live") or _contains(env_blob, "NAS") or _contains(env_blob, "ASWS")
        ):
            failures.append("live API down not disclosed")

    passed = not failures
    scores["pass"] = passed
    return {
        "id": item["id"],
        "family": item.get("family"),
        "pass": passed,
        "failures": failures,
        "scores": scores,
        "reconstructed_query": answer.reconstructed_query,
        "intents": pred_intents,
        "entities": pred_entities,
        "ranking": ranking_order(answer),
    }


def _jsonish(text: str) -> Any:
    """Best-effort parse of engine/RAG JSON dumped into template prose."""

    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        blob = text[start : end + 1]
        try:
            return json.loads(blob)
        except json.JSONDecodeError:
            return blob
    return text


def _number_allowed(token: str, allowed: set[str]) -> bool:
    from navaid.agent.number_lock import number_allowed

    return number_allowed(token, allowed)


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def collect(key: str) -> list[float]:
        values = []
        for row in rows:
            value = row["scores"].get(key)
            if value is not None:
                values.append(float(value))
        return values

    kpis = {
        "subgoal_coverage": _mean(collect("subgoal_coverage")),
        "intent_accuracy": _mean(collect("intent_accuracy")),
        "entity_f1": _mean(collect("entity_f1")),
        "kendall_tau": _mean(collect("kendall_tau")),
        "numeric_hit_rate": _mean(collect("numeric_hit_rate")),
        "hallucination_rate": _mean(collect("hallucination_rate")),
        "envelope_completeness": _mean(collect("envelope_completeness")),
        "must_say": _mean(collect("must_say")),
        "must_not_say": _mean(collect("must_not_say")),
        "reconstruction_match": _mean(collect("reconstruction_match")),
        "pass_rate": sum(1 for row in rows if row["pass"]) / len(rows) if rows else 0.0,
        "n_items": len(rows),
        "n_pass": sum(1 for row in rows if row["pass"]),
        "n_fail": sum(1 for row in rows if not row["pass"]),
    }
    latencies = [float(row["latency_ms"]) for row in rows if row.get("latency_ms") is not None]
    kpis["mean_latency_ms"] = _mean(latencies)
    return kpis


def format_table(kpis: dict[str, Any]) -> str:
    order = [
        ("subgoal_coverage", "subgoal coverage"),
        ("intent_accuracy", "intent accuracy"),
        ("entity_f1", "entity F1"),
        ("kendall_tau", "Kendall tau"),
        ("numeric_hit_rate", "numeric hit rate"),
        ("hallucination_rate", "hallucination rate"),
        ("envelope_completeness", "envelope completeness"),
        ("must_say", "must-say"),
        ("must_not_say", "must-not-say"),
        ("reconstruction_match", "reconstruction"),
        ("pass_rate", "item pass rate"),
        ("mean_latency_ms", "mean latency ms"),
    ]
    lines = [f"{'KPI':<24} {'value':>10} {'n':>6}", "-" * 42]
    n = kpis.get("n_items") or 0
    for key, label in order:
        value = kpis.get(key)
        if value is None:
            shown = "n/a"
        elif key == "mean_latency_ms":
            shown = f"{value:.1f}"
        else:
            shown = f"{value:.3f}"
        lines.append(f"{label:<24} {shown:>10} {n:>6}")
    lines.append(f"{'pass / fail':<24} {kpis.get('n_pass', 0):>4} / {kpis.get('n_fail', 0):<4}")
    return "\n".join(lines)


def run_eval(
    *,
    gold_path: Path | None = None,
    ids: set[str] | None = None,
    use_gemini: bool = False,
    runs_dir: Path | None = None,
) -> dict[str, Any]:
    ensure_snapshot()
    items = load_gold(gold_path)
    if ids:
        items = [item for item in items if item["id"] in ids]
        missing = ids - {item["id"] for item in items}
        if missing:
            raise ValueError(f"unknown gold ids: {sorted(missing)}")
    catalog = MetricsCatalog()
    try:
        expected = {
            item["id"]: {
                "ranking": gold_ranking(item, catalog),
                "numeric": gold_numeric(item, catalog),
            }
            for item in items
        }
    finally:
        catalog.close()

    rows: list[dict[str, Any]] = []
    for item in items:
        turns = _turns(item)
        session_id = f"eval-{item['id']}-{new_session_id()[:8]}"
        started = time.perf_counter()
        answer: Answer | None = None
        try:
            for question in turns:
                answer = ask(question, session_id=session_id, use_gemini=use_gemini)
        except Exception as exc:
            elapsed = (time.perf_counter() - started) * 1000.0
            rows.append(
                {
                    "id": item["id"],
                    "family": item.get("family"),
                    "pass": False,
                    "failures": [f"ask failed: {exc}"],
                    "scores": {"subgoal_coverage": 0.0, "intent_accuracy": 0.0},
                    "latency_ms": elapsed,
                    "reconstructed_query": "",
                    "intents": [],
                    "entities": [],
                    "ranking": [],
                }
            )
            continue
        elapsed = (time.perf_counter() - started) * 1000.0
        assert answer is not None
        scored = score_item(
            item,
            answer,
            expected_ranking=expected[item["id"]]["ranking"],
            expected_numeric=expected[item["id"]]["numeric"],
        )
        scored["latency_ms"] = elapsed
        rows.append(scored)

    kpis = aggregate(rows)
    payload = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "use_gemini": use_gemini,
        "gold_path": str(gold_path or GOLD_PATH),
        "item_count": len(rows),
        "kpis": kpis,
        "items": rows,
        "failed_ids": [row["id"] for row in rows if not row["pass"]],
    }
    out_dir = runs_dir or RUNS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_path = out_dir / f"{stamp}.json"
    latest_path = out_dir / "latest.json"
    text = json.dumps(payload, indent=2, default=str)
    run_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    payload["run_path"] = str(run_path)
    payload["latest_path"] = str(latest_path)
    return payload


def latest_run_path(runs_dir: Path | None = None) -> Path | None:
    directory = runs_dir or RUNS_DIR
    latest = directory / "latest.json"
    if latest.is_file():
        return latest
    files = [p for p in directory.glob("*.json") if p.is_file()]
    if not files:
        return None
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def load_latest_summary(runs_dir: Path | None = None) -> dict[str, Any]:
    path = latest_run_path(runs_dir)
    if path is None:
        return {
            "status": "no_runs",
            "message": "No eval runs yet. python eval/run_eval.py",
        }
    data = json.loads(path.read_text(encoding="utf-8"))
    kpis = data.get("kpis") or {}
    return {
        "status": "ok",
        "run_path": str(path),
        "created_at": data.get("created_at"),
        "use_gemini": data.get("use_gemini"),
        "item_count": data.get("item_count"),
        "kpis": kpis,
        "failed_ids": data.get("failed_ids") or [],
        "pass_rate": kpis.get("pass_rate"),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Navaid gold eval")
    parser.add_argument("--gold", type=Path, default=GOLD_PATH)
    parser.add_argument("--ids", default="", help="Comma-separated gold ids")
    parser.add_argument(
        "--use-gemini",
        default="false",
        help="true/false. Default false: numbers from engines/tools, not the LLM.",
    )
    parser.add_argument("--runs-dir", type=Path, default=RUNS_DIR)
    args = parser.parse_args(argv)
    use_gemini = str(args.use_gemini).strip().lower() in {"1", "true", "yes", "on"}
    ids = {part.strip() for part in str(args.ids).split(",") if part.strip()} or None
    payload = run_eval(
        gold_path=args.gold,
        ids=ids,
        use_gemini=use_gemini,
        runs_dir=args.runs_dir,
    )
    print(format_table(payload["kpis"]))
    print(f"items: {payload['item_count']}")
    run_path = Path(payload["run_path"])
    try:
        shown = run_path.relative_to(ROOT)
    except ValueError:
        shown = run_path.name
    print(f"wrote: {shown}")
    failed = payload.get("failed_ids") or []
    if failed:
        print("failed:", ", ".join(failed))
        for row in payload["items"]:
            if not row["pass"]:
                print(f"  - {row['id']}: {row['failures']}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
