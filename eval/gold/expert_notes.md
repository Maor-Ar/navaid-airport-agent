# Navaid gold eval — expert notes

Gold lives in `eval/gold/questions.jsonl` (~40 items). Numbers are **not** LLM
judgments. They come from the frozen DuckDB snapshot through the same
deterministic engines the orchestrator calls (`rank_expansion`, `unmet_demand`,
`longhaul_share`, `compare_congestion`). `eval/run_eval.py` re-queries those
engines at run time (`ranking_from`, `numeric_from`) so the gold file does not
drift if the snapshot is rebuilt from the same fixtures.

## How to run

From the repo root, engines only (no Gemini):

```powershell
python eval/run_eval.py
python eval/run_eval.py --use-gemini false
```

If `data/warehouse/navaid.duckdb` is missing:

```powershell
python scripts/build_snapshot.py --offline
```

The runner writes `eval/runs/<timestamp>.json` and `eval/runs/latest.json`, then
prints a KPI table. FastAPI `GET /eval/summary` reads that latest file.

A subset:

```powershell
python eval/run_eval.py --ids assign_ne_expansion,assign_sfo_unmet,fu_those_two
```

## What must be in the set

- Four assignment questions (New England expansion, LA vs Santa Ana congestion,
  ANC long-haul %, SFO unmet + why).
- Compound questions with two/three intents, including unsupported **buy AAL**.
- Follow-ups: **those two**, **why rank 2**, **add PWM** (PWM missing from the
  prior peer set), plus cargo-after-ANC and an independent SFO turn.
- Adversarial: AAL, restaurant at LAX, empty ICAO, Santa Ana vs San Antonio,
  LA = LAX, Portland = PWM not PDX.
- Envelope: SAT missing gates (`landside_saturation` dropped and renormalized),
  live FAA overlay disclosed when status is absent, SFO airside/slot/curfew.

## Scoring (do not retune TEOI here)

| KPI | How it is counted |
| --- | --- |
| Subgoal coverage | Fraction of expected intents present and answered (or refused if `UNSUPPORTED`) |
| Intent accuracy | Jaccard of predicted vs expected intent sets |
| Entity F1 | IATA codes on supported subgoals vs gold |
| Kendall tau | Ranking items only; gold order from `rank_expansion` on the snapshot |
| Numeric hit rate | Engine fields (`pct_longhaul`, `unmet`, `threshold_km`, …) found in tables/traces |
| Hallucination rate | Regex numbers in prose that are absent from tool/trace JSON (number lock) |
| Envelope completeness | `assumptions`, `uncertainties`, `out_of_scope`, `confidence`, `sources`, `as_of` |
| Must-say / must-not-say | Phrase checks on answer text (must-not-say is prose-only) |
| Reconstruction | Exact or substring match on `reconstructed_query` for follow-ups |

Ranking answers must attach `teoi_traces` with formula fields (`formula_text`,
weights, contributions, constraint multiplier, rank).

## Snapshot notes (fixtures / offline warehouse)

**New England.** Peer set is BDL, BGR, BOS, BTV, MHT, ORH, PVD, PWM. Gold
requires the core five (BOS, BDL, PVD, PWM, MHT) on every NE rank. BOS may
outscore landside regionals on this snapshot; that is allowed. The fail
condition is claiming BOS is best *solely because it is biggest*. Template
narration is peer-relative and says busy is not investable.

**SFO unmet.** Unmet is `max(0, implied − served)` and is non-negative (TAF
gap on this snapshot). Same-CBSA leakage to OAK/SJC is **zero** here: SFO load
factor is below the 0.85 leakage gate, and OAK/SJC YoY is not faster. Gold
still requires the leakage field, the OAK/SJC pair via a Bay Area compound
item, and airside/slot/curfew language in the why.

**ANC long-haul.** Default threshold **4000 km** (Eurocontrol) on T-100
segments, plus **international share**. Units are kilometres (ANC–JFK is the
~5420 km / 3370 mi pin). Cargo is out of the *engine* default; the planner
notes string currently contains the word “cargo”, so the tool may set
`include_cargo=True`. The G-class ANC–JFK row has zero passengers, so the
passenger shares match the cargo-out engine dump. Gold keys on 4000 km +
international %, not the cargo flag.

**SAT missing gates.** SAT is in the warehouse without `gates.csv` / NPIAS
rows. Ranking SAT with LAX/SNA drops `landside_saturation` and
`capital_feasibility` and lists that drop in the envelope.

**Live API.** Congestion compare overlays FAA NAS/ASWS only when not offline.
When the feed is down or skipped, `live_faa_status` is empty and the envelope
still cites live FAA as a source / assumption. Eval treats “disclosed missing”
as a pass.

**Empty ICAO.** “Airport brief for ICAO code ” has no resolvable identity. The
orchestrator falls through to `AIRPORT_BRIEF` (warehouse default). Gold checks
the intent and forbids invented codes such as KZZZ; it does not require a
hard failure.

**LA / Santa Ana.** `LA` → LAX (not the metro). `Santa Ana` → SNA (John Wayne),
never SAT. San Antonio is SAT when asked by name.
