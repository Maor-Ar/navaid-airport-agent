# Navaid decision log

Investigation and build phases 0–9. Written in the order the work is supposed to happen so this reads as an analyst investigation, not a retro-fitted README.

Related: [GLOSSARY.md](GLOSSARY.md), [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Phase 0 — Assignment intake

### Brief (what we were asked)

**Title:** Airport Investment Intelligence Agent.

**Goal:** A firm that invests in US airport modernization wants an AI agent that helps analysts find airports where renovations will be most profitable based on increased flight and passenger capacity.

**Sample questions the agent must answer:**

- Which airports in New England are strong candidates for terminal expansion?
- Compare LA and Santa Ana airport congestion levels.
- What is the percentage of long haul flights out of Anchorage airport?
- What is the unmet flight demand in SFO airport and why?

**The agent should:** use public APIs to gather airport/aviation data; rank or compare airports on defined logic or KPI; explain its reasoning clearly; support conversational follow-up.

**Requirements:** some deterministic scoring or ranking logic (not only LLM output); a chat interface (voice is a bonus); clearly communicate assumption, uncertainty, and scoping.

**Deliverables:** source code; a short design/architecture document covering scoring methodology, key tradeoffs, and where/how AI is used.

The original brief mentioned an approximately one-day timeframe and asked to prioritize clarity over polish. That is not treated as a cut line. The system is a complete local analyst stack: TEOI workings, multi-part questions, follow-up reconstruction, eval, Gradio, and a designed site.

### Must-haves extracted from the brief

| Must-have | How we interpret it |
| --- | --- |
| Public data | Official bulk files first (FAA, BTS, OurAirports, NPIAS/AIP); live FAA NAS/ASWS as overlay. OpenSky optional. |
| Deterministic KPI | TEOI + ScoringTrace, unmet demand, long-haul share, congestion compare, stable ranker. Gemini never produces a rank. |
| Explain reasoning | Full TEOI waterfall in every ranking answer; `steps[]` on every `/ask`. |
| Follow-ups | Reconstruction into a standalone question from DuckDB session state, then re-plan. |
| Assumptions / uncertainty / scope | Envelope on every answer. Stale snapshot (>90 days) always an uncertainty. |
| Chat (+ voice bonus) | Gradio workbench first; Gemini audio on `/ask`; designed site on the same API. |
| Architecture doc | This log plus [ARCHITECTURE.md](ARCHITECTURE.md) (assignment deliverable) and [GLOSSARY.md](GLOSSARY.md). |

### Success definition

Gold eval passes on:

1. The four sample questions, with TEOI traces visible on any ranking answer.
2. Compound questions (two or three intents, including one unsupported) — every subgoal answered or listed in `unsupported_parts`.
3. Follow-up dialogs — reconstruction exact-match on gold (“those two”, “why rank 2”, “add PWM”).

An ordinary chatbot that wraps Gemini around a couple of HTTP calls and lets the model invent a ranking **fails the brief**.

---

## Phase 1 — Domain investigation (airport terms)

Worked the four sample questions until “busiest” was obviously the wrong investment answer. Output: [GLOSSARY.md](GLOSSARY.md).

### Landside vs airside (the investment thesis)

The brief asks where **terminal renovations** are most profitable because they **unlock flight and passenger capacity**. Busy is not investable.

- **Landside-bound** (gates, holdrooms, security, bag claim, curb): terminal capex can raise throughput. High TEOI.
- **Airside-bound** (runways, slots, weather, ATC, noise curfew): more terminal does not create slots. Score penalized; the answer must say so.
- **Demand-bound** (weak catchment, low load factor, leakage already served nearby): expansion is speculative.
- **Already-funded:** NPIAS/AIP money committed; incremental private return may be lower.

### Terms that change the math

| Term | Why it matters |
| --- | --- |
| Enplanement | Scale of passenger demand; hub size. |
| Load factor | Unmet demand uses a 0.85 threshold. High LF with no spare seats is pressure, not success. |
| Leakage | Same-CBSA airports growing faster while origin LF is high (SFO → OAK/SJC). |
| Curfew / slot | Airside/policy constraint. SNA is the Santa Ana example. |
| T-100 segment vs O&D | We measure legs, not true passenger journeys. ANC→SEA→JFK is two segments. |
| Long-haul conventions | Eurocontrol **>4000 km** on T-100 segments is the default; also **>6h** and international share. Pin ANC→JFK (~5420 km). |

### Canonical spoken answers (domain, not yet numbers)

- **SFO unmet:** high load factors, leakage to OAK/SJC, delay, slot/curfew. Much of the gap is airside/policy, not a missing concourse. Unmet is `max(0, implied − served)`.
- **LAX vs SNA:** LAX wins absolute delay volume; SNA is high-utilization and curfew-capped. Compare delay + utilization + constraint type. No fake single congestion score. `"LA"` → LAX, not the metro; `"Santa Ana"` → SNA, not SAT.
- **ANC long-haul:** default Eurocontrol >4000 km on T-100 segments; also >6h and international share. Cargo out unless asked.
- **New England:** BOS is scale; BDL/PVD/PWM/MHT can win as landside-constrained regionals. Peer-relative, not “biggest wins.” PWM is Portland Maine, not PDX.

Finance we will not fake: PFC, NPV, capex. Profit proxy is **capacity unlock**, stated as such.

---

## Phase 2 — Data investigation

For each needed field: official source, download method, license posture, failure mode. Prefer bulk files over live APIs. US primary commercial airports in the warehouse; extra curated depth for New England + LAX/SNA + SFO/OAK/SJC + ANC.

### Source matrix

| Field / table | Official source | How we get it | Failure mode | Decision |
| --- | --- | --- | --- | --- |
| Identity, lat/lon, runways | [OurAirports](https://davidmegginson.github.io/ourairports-data/airports.csv) `airports.csv` + `runways.csv` | HTTP CSV | Missing IATA, heliports mixed in | Filter to US commercial; IATA required for passenger questions |
| Yearly boardings, hub, YoY | [FAA CY enplanements Excel](https://www.faa.gov/airports/planning_capacity/passenger_allcargo_stats/passenger) | Download + parse Excel | Sheet layout changes year to year | Pin parser to published CY; disclose `as_of` |
| 10-year pax/ops forecast | [FAA TAF](https://taf.faa.gov/) | File extract if obtainable | UI is awkward; no clean bulk | Try file; else curated TAF for the deep slice, **disclosed** |
| Route passengers, seats, distance, international flag | BTS T-100 Segment [PREZIP](https://transtats.bts.gov/PREZIP/) | Stream ZIP + filter | File is large; easy to OOM | Stream + filter to US commercial; never keep raw T-100 as system of record |
| Delay / cancel | BTS airport-month delay-cause | Monthly aggregates | Flight-level OTP zips are huge and the wrong grain | **Use delay-cause.** Flight-level OTP is a trap |
| Development need, grants | NPIAS Appendix A / AIP summaries | Files where they exist | Incomplete coverage | Feasibility feature only; missing → drop-and-renormalize |
| Live delay / ground stop | [NAS Status XML](https://nasstatus.faa.gov/api/airport-status-information), [ASWS JSON](https://external-api.faa.gov/asws/api/api/airport/status/{airportCode}) | Live HTTP at tool time | 429 / downtime | Overlay only; not a TEOI input; envelope if down |
| ADS-B / airborne | OpenSky | OAuth2 | Auth friction | **Optional.** NAS/ASWS already satisfies “public APIs” |
| Restricted FAA metrics | ASPM | N/A | Access restricted | **Skip** |
| Gates, CBSA catchment, constraint type, notes | Not in OurAirports | Curated `gates.csv`, `catchment_cbsa.csv`, `constraints.csv`, notes | Hand-authored, can stale | Curate the deep slice or drop the feature; never invent gate counts |

### RAG corpus

Airport-keyed `doc_chunks` plus DuckDB FTS. Chunks carry `{airport, doc_type, as_of, url}`. Tens of notes, not millions of pages — keyword + IATA filter is the retrieval that fits.

If corpus and T-100 disagree, **T-100 wins**; disagreement is an uncertainty. No embedding model unless the notes corpus later outgrows FTS.

### Offline

`NAVAID_OFFLINE=1`: no government HTTP; local DuckDB only. Engine tests do not need Gemini. Chat still needs Gemini auth (gcloud ADC or `GEMINI_API_KEY`).

---

## Phase 3 — How TEOI is calculated

Frozen before any Gemini call. Unit tests before the model. Full formula, unmet clamp, long-haul, ranker, and ScoringTrace live in [ARCHITECTURE.md](ARCHITECTURE.md). Short version:

### Formula

Peer-relative min-max inside comparison set `S`. Weights sum to 1.0. Missing feature: **drop and renormalize**.

```
TEOI = 100 * (
  0.22 * demand_pressure +
  0.18 * congestion +
  0.18 * landside_saturation +
  0.15 * unmet_demand +
  0.12 * yield_mix +
  0.10 * growth_outlook +
  0.05 * capital_feasibility
) * constraint_multiplier
```

`constraint_multiplier`: landside **1.00**, mixed **0.75**, airside **0.40**, demand-bound **0.30**.

### Unmet demand (clamped at 0)

- Load-factor gap: `served * max(0, LF − 0.85) / 0.85`
- Forecast gap: `max(0, TAF_10y − implied_current_capacity)` if TAF exists
- Leakage: same-CBSA airports growing faster while origin LF is high

### Long-haul

`great_circle_km`, default **4000 km**. Also international share and optional `pct_over_6h`. Pin `ANC→JFK` (~5420 km / 3370 mi).

### Ranker and congestion

- **Ranker:** shared ranks (3, 3, 5); leftover ties by ICAO ascending.
- **Congestion compare:** `{delay_pct, avg_arrival_delay_min, cancel_pct, ops_per_runway, live_faa_status, constraint_type, winner_on_each_axis}`. No fake single congestion score.

Every engine returns an Envelope. Stale snapshot (>90 days) is always an uncertainty.

### What “steps” means (New England rank)

1. Reconstruct: n/a (first turn)
2. Decompose: one subgoal `EXPANSION_RANK` region=New England
3. Resolve airports: BOS, BDL, PVD, PWM, MHT, BTV, …
4. Pull warehouse metrics `as_of=…`
5. Compute unmet, yield mix, congestion per airport
6. Min-max each feature inside `S`
7. Drop missing weights; renormalize
8. Apply constraint multipliers
9. Stable rank
10. Number lock
11. Narrate from traces

Gemini may only narrate that trace. The UI renders a waterfall from the same JSON even if the model is terse.

---

## Phase 4 — Architecture

Warehouse first, engines second, Gemini third. Reconstruct + decompose in the agent. One DuckDB. FastAPI as the only contract.

### How to read the system in one paragraph

Public aviation files are **ingested** into a local **DuckDB warehouse**. **Deterministic engines** compute TEOI (with a full trace), unmet demand, long-haul share, and congestion compares. A **Gemini agent** first **reconstructs** follow-ups, **decomposes** multi-part questions, then may only call those engines as **tools**. A **number lock** rejects any digit that was not in a tool payload. **Gradio** and a **designed site** share local FastAPI `/ask`.

Diagram, ingest list, agent graph, and Answer/ScoringTrace contracts: [ARCHITECTURE.md](ARCHITECTURE.md).

### Ordering rationale

- **Warehouse first** so engines and eval pin to a hashed snapshot.
- **Engines second** so unit tests prove TEOI without a network.
- **Gemini third** so the model cannot become the source of ranks.
- **FastAPI `/ask`** is the only public contract. Gradio, the site, CLI, and eval all consume `Answer`. Forking the schema per UI would hide bugs.

Live FAA NAS/ASWS **skips the warehouse**: right-now delay overlay, not a historical score input. Curated gates/curfews feed engines because those fields are not in OurAirports.

---

## Phase 5 — Package decisions

### Why these, not the alternatives

| Choice | Decision | Why | Rejected |
| --- | --- | --- | --- |
| Language | **Python 3.12** | Scoring, tests, DuckDB, Excel/CSV ingest are native. | Node (would fight the warehouse). |
| Warehouse | **DuckDB, one local file** | Columnar SQL, streams T-100 CSVs, no server. Metric tables + sessions + FTS in one place. | **Postgres** (ops burden for a local assignment). **SQLite** (weaker analytics). **Pandas-only** (T-100 is too large to keep as the system of record). **Snowflake/BigQuery** (not local). |
| RAG | **DuckDB FTS + airport metadata** | Dozens of note/PDF chunks. `WHERE airport = ?` plus keyword is the retrieval that fits. | **Chroma, FAISS, Pinecone** (second datastore). **LangChain indexes** (hides retrieval). **Gemini embeddings / sentence-transformers** as default (extra model, extra failure mode, no gain on tens of airport-keyed chunks). |
| Embeddings | **None** | Corpus is too small. | Any embedding model unless notes later outgrow FTS. |
| LLM | **gemini-2.5-flash** via official `google-genai` | Scoring and TEOI traces are engines, not the model. Flash: strong function calling, snappy Gradio demo, cheap gold-eval loops. Manual function calling (AFC disabled). Auth: **Vertex AI + ADC** (`gcloud auth login --update-adc`) or `GEMINI_API_KEY`. Pin `google-genai<3`. | **gemini-2.5-pro as default**. **OpenAI**. `gcloud auth login` without `--update-adc` (Python cannot use CLI user creds). |
| Agent framework | **Hand-rolled orchestrator** (~200 lines) | Reconstruct, decompose, traces, and number lock must be visible Python we control. | **LangChain, LangGraph, LlamaIndex, CrewAI, AutoGen, Google ADK.** They hide the loop we must show. LangChain also churns APIs and would fight Gemini’s native SDK. |
| HTTP | **httpx** | Timeout, 429/5xx backoff, on-disk cache. | `requests` (sync-only, weaker timeout story). |
| Schemas | **Pydantic v2** | FastAPI + Gemini tool JSON + ScoringTrace share models. | Ad-hoc dicts. |
| API | **FastAPI** | One OpenAPI contract for Gradio, site, CLI, eval. | Flask (untyped), Django (too much), Gradio-only (eval and site would fork). |
| Chat UI | **Gradio first**, then a designed site on the same API | Gradio: chat, files, voice fast. Site: waterfall, methodology, glossary. | Streamlit (weaker conversational agent UX). |
| Voice | **Gemini audio** on `/ask` | Same vendor as the chat model. | OpenAI Whisper (wrong vendor). |
| Tests | **pytest** + gold eval script | Gold numbers come from the same engines. | LLM-as-judge as the product. |

### Why DuckDB (expanded)

T-100 PREZIP is large. We need SQL over filtered segment rows, session tables, and FTS notes without standing up a database server. DuckDB is a single file (`data/warehouse/navaid.duckdb`), columnar, and can stream CSVs. That is the whole local-first story: clone, build snapshot, ask questions.

Postgres would be the right warehouse for a hosted product. It is the wrong warehouse for a laptop assignment. SQLite would store sessions fine and lose on analytics. Keeping Pandas DataFrames as the system of record would break as soon as T-100 is ingested for real.

### Why not LangChain / Chroma / embeddings (expanded)

LangChain (and LangGraph, LlamaIndex, CrewAI) would wrap the one loop we are graded on: reconstruct follow-ups, decompose compound questions, attach ScoringTraces, number-lock digits. Those frameworks hide that loop, churn APIs, and fight `google-genai`. A short orchestrator we own is the product.

Chroma (or FAISS/Pinecone) would add a second database and an embedding model for a corpus of tens of airport-keyed notes. DuckDB FTS plus `WHERE airport = ?` is the retrieval that fits. RAG never ranks; T-100 wins facts.

Embeddings (Gemini embeddings or sentence-transformers) are an extra model, an extra failure mode, and no gain until the notes corpus outgrows keyword search. Default is **no embedding model**.

### Why gemini-2.5-flash default, Pro as override (expanded)

Numbers come from engines. The model’s job is function calling and narration. Flash is strong enough at that, cheaper for gold-eval loops, and snappier in Gradio. Pro as the default would spend latency and cost on zero extra numeric correctness.

`NAVAID_MODEL=gemini-2.5-pro` stays as an override if a reviewer finds Flash narration thin. It does not change TEOI, unmet, long-haul, or congestion math.

---

## Phase 6 — Agent protocol

Manual Gemini tools, number lock, session tables, compound coverage, TEOI waterfall in the UI.

### Graph

User question → **Reconstruct** → **Decompose into subgoals** → **Plan tools per subgoal** → **Run engines in parallel** → **Number lock plus TEOI traces** → **Narrate every section** → **Store session** → (next turn).

### Reconstruction (follow-ups)

Before any tool call, build a standalone question from session memory.

- Pronouns and ellipsis: “those two”, “why is #2 above #3?”, “add PWM”, “what about cargo?”
- Copy forward: last airports, last peer set, last TEOI traces, last congestion payload.
- Output: `reconstructed_query` + `reconstruction_notes` (what was filled in).
- If the new question is independent, reconstruction is a no-op and we still record that.

Examples:

- After LAX vs SNA: “which is more curfew-constrained?” → “Compare constraint type and curfew for LAX vs SNA using last congestion payload; re-run only if needed.”
- After New England rank: “why is #2 above #3?” → “Explain TEOI traces for rank 2 vs rank 3 in peer set [BOS, BDL, …]” and **reuse traces**, do not invent a new ranking.
- “add PWM” when PWM was missing → reconstruct peer set, **re-run ranker**, keep the same recipe.

Sessions persist in DuckDB (`session_id`, turns, last entities, last payloads, last traces) so follow-ups survive a Gradio refresh.

### Decomposition (compound questions)

A planner (Gemini with a strict schema, or rules + Gemini) emits `subgoals[]`. Each subgoal has one closed intent. We execute **all** of them. The narrator produces one section per subgoal. If one subgoal is `UNSUPPORTED`, we answer the others and list the refusal in `unsupported_parts`.

Example: “Which New England airports are strong expansion candidates, compare LAX and SNA congestion, and should I buy AAL?”

1. `EXPANSION_RANK` New England — full TEOI traces
2. `CONGESTION_COMPARE` LAX, SNA
3. `UNSUPPORTED` AAL stock

Eval gold includes this class of question. Coverage KPI = fraction of subgoals answered.

### Closed intents and tools

**Intents:** `EXPANSION_RANK`, `CONGESTION_COMPARE`, `LONGHAUL_SHARE`, `UNMET_DEMAND`, `AIRPORT_BRIEF`, `EXPLAIN_TEOI`, `FOLLOW_UP` (only as a flag; reconstruction turns it into a real intent), `UNSUPPORTED`.

**Tools:** `resolve_airport`, `rank_expansion`, `compare_congestion`, `longhaul_share`, `unmet_demand`, `airport_metrics`, `explain_teoi`, `search_corpus`, `get_live_status`.

**Entity rules:** `"LA"` → LAX not the metro; `"Santa Ana"` → SNA not SAT; `"Anchorage"` → ANC; `"those two"` from session.

### Number lock and TEOI traces

Every digit in prose must exist in tool JSON. Ranking answers must contain `teoi_traces[]` with formula fields. The Gradio/site UI renders a waterfall from that JSON even if the model is terse. AFC is disabled so this intercept is possible.

---

## Phase 7 — Eval

Gold from a frozen snapshot: `eval/gold/questions.jsonl` (~40–50 items). Numbers come from the same engines. Gold eval is a script, not an LLM-as-judge product.

### Must include

- Four assignment questions
- Compound (two or three intents, including one unsupported)
- Follow-up dialogs (reconstruct “those two”, “why rank 2”, “add PWM”)
- Adversarial: AAL, restaurant, empty ICAO, Santa Ana vs San Antonio, LA = LAX
- Envelope: missing gates, live API down
- TEOI trace presence: ranking answers must contain `teoi_traces` with formula fields

### KPIs

Subgoal coverage, intent accuracy, entity F1, Kendall tau, numeric hit rate, hallucination rate, envelope completeness, must-say / must-not-say, reconstruction exact-match on gold follow-ups, latency.

Engine tests (`pytest`) do not need Gemini. Chat still needs a key.

---

## Phase 8 — Interfaces

### Gradio workbench

Ships first. Same `/ask` `Answer` object. Shows:

- Reconstruction and subgoals
- Ordered `steps[]`
- TEOI waterfall from `teoi_traces[]`
- Envelope (assumptions, uncertainties, out-of-scope, confidence, sources, `as_of`)
- Citations
- Voice (Gemini audio) as the bonus

### Designed analyst site

Polished surface on the same API, after gold canonicals + compound + follow-up are green. Landing, workbench, methodology, glossary, decision log. Same waterfall, same envelope. Gradio and the site are skins, not two products.

Streamlit was considered and rejected (weaker conversational agent UX). Gradio-only was rejected as the long-term surface (eval and site would fork the contract).

---

## Phase 9 — Narrative docs and what shipped vs dropped

This phase is the three markdown files. Python app, engines, and UI are later todos. What follows is the **committed ship set vs explicitly dropped**, so later implementation cannot quietly reintroduce rejected pieces.

### Ships (documentation locked here; code later)

| Piece | Notes |
| --- | --- |
| [GLOSSARY.md](GLOSSARY.md) | Every term. |
| [DECISION_LOG.md](DECISION_LOG.md) | This file. Phases 0–9. |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Assignment deliverable: brief, TEOI + ScoringTrace, tradeoffs, Gemini vs engines, mermaid. |
| Local-first stack | Python 3.12, FastAPI, Gradio, one DuckDB file, Gemini via `google-genai`. |
| Default model | **gemini-2.5-flash**. `NAVAID_MODEL` may override to Pro. |
| RAG | DuckDB FTS + airport-keyed notes. |
| Agent protocol | Reconstruct, decompose, manual tools, number lock, TEOI traces, persistent sessions. |
| Eval | Gold set including compound + follow-up + adversarial. |
| UI | Gradio workbench; designed site on the same API. |

### Dropped (and why)

| Dropped | Why |
| --- | --- |
| LangChain / LangGraph / LlamaIndex / CrewAI / AutoGen / Google ADK | Hide reconstruct/decompose/traces/number lock; API churn; fight native Gemini SDK. |
| Chroma / FAISS / Pinecone | Second datastore for tens of notes. |
| Embedding models (Gemini embeddings, sentence-transformers) | Extra model and failure mode; no gain on airport-keyed FTS. |
| gemini-2.5-pro as default | Cost/latency; numbers already come from engines. Override only. |
| OpenAI chat or Whisper | Wrong vendor. |
| Postgres / Snowflake / BigQuery | Not local. |
| SQLite as warehouse | Weaker analytics for T-100. |
| Pandas as system of record | T-100 too large. |
| ASPM | Restricted. |
| Flight-level OTP zips | Trap; use delay-cause aggregates. |
| OpenSky as required | OAuth friction; NAS/ASWS already covers public APIs. Optional only. |
| Invented gate counts | Missing → drop-and-renormalize, disclosed. |
| PFC / NPV / airport finance | Out of scope; profit proxy is capacity unlock. |
| National TEOI for a regional question | Peer-relative min-max inside `S`. |
| Single fake congestion score | Axis-by-axis compare + constraint type. |
| RAG-as-ranker | RAG never ranks; T-100 wins facts. |
| Automatic function calling (AFC) | Would skip the number lock intercept. |
| LLM-as-judge as the eval product | Gold numbers from engines. |
| Streamlit | Weaker agent UX than Gradio. |
| One-day polish cut | Clarity still wins, but the system is complete, not a thin chatbot. |

If a later todo tries to add Chroma, embeddings, LangChain, or Pro-as-default, this log is the reason to refuse.
