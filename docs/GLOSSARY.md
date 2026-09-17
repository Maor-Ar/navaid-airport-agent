# Navaid glossary

Product terms, aviation data vocabulary, scoring language, and the airport set used in the assignment. IATA codes unless noted. This glossary is the contract for how Navaid talks about the domain.

---

## Assignment and product

**Navaid.** Product name. In aviation, a navaid is a navigational aid. Here it is the local airport-investment intelligence agent: DuckDB warehouse, deterministic TEOI engines, Gemini tool-calling, Gradio, and a designed analyst site.

**Agent.** An LLM plus tools, not next-token chat only. Gemini reconstructs follow-ups, decomposes multi-part questions, and may call engines. It may narrate a rank; it may never produce one.

**TEOI working / ScoringTrace.** The full arithmetic of a Terminal Expansion Opportunity Index score, shown to the user: raw inputs, peer min-max, original/dropped/used weights, contributions, constraint multiplier, formula text, final score, and rank. Gemini may quote these fields. It may not invent a different formula.

**Reconstruction.** Rewrite a follow-up into a standalone question using session state (last airports, last peer set, last TEOI traces, last congestion payload). Pronouns and ellipsis such as “those two” or “why is #2 above #3?” become explicit queries before any tool runs.

**Decomposition / subgoal.** Split a compound question into closed intents. Every subgoal is answered (or explicitly refused). The UI shows one section per subgoal so multi-part questions cannot collapse into one vague paragraph.

**KPI.** A number we use to judge quality: hallucination rate, subgoal coverage, intent accuracy, entity F1, Kendall tau, numeric hit rate, envelope completeness, reconstruction exact-match, latency.

**Envelope.** The honesty block on every answer: assumptions, uncertainties, out-of-scope, confidence, sources, and `as_of`. Stale snapshot (>90 days) is always an uncertainty.

**as_of.** Warehouse snapshot date. Every metric table and every answer carries it.

**Scoping.** Which airports and years the answer covers (for example US commercial primary airports; New England = CT, ME, MA, NH, RI, VT).

---

## Flowchart

**flowchart TB.** A top-to-bottom Mermaid diagram. Used in the architecture doc to show ingest → warehouse → engines → Gemini → UI.

**Subgraph.** A group of boxes in that diagram: Ingest, Warehouse, Engines, Agent, UI.

**Node.** One box in the diagram (for example FAA enplanements, TEOI scorer, Gradio workbench).

**Ingest.** The download-and-clean pipeline. Batch job, not chat. Writes clean tables via `scripts/build_snapshot.py`. Does not talk to the user.

**Warehouse.** One local DuckDB file: `data/warehouse/navaid.duckdb`. Holds metric tables, sessions (follow-up memory), and `doc_chunks` with FTS. No embeddings table.

**Deterministic engine.** Same input → same output; no LLM. TEOI + ScoringTrace, unmet demand, long-haul share, congestion compare, stable ranker.

**Interfaces.** FastAPI `/ask`, Gradio workbench, and the designed analyst site. All consume the same `Answer` object.

---

## Ingest sources

**FAA.** Federal Aviation Administration. Source of enplanements, TAF planning forecasts, NPIAS/AIP, and live NAS/ASWS status.

**Enplanement.** One passenger boarding an aircraft. Yearly boardings are the primary demand scale metric.

**CY.** Calendar year. FAA passenger statistics are published by calendar year.

**Hub size.** FAA classification: Large / Medium / Small / Non-hub, derived from enplanements.

**YoY.** Year-over-year change (for example enplanement growth).

**TAF (FAA).** Terminal Area Forecast — a *planning* forecast of passengers and operations, typically 10 years. Not a weather TAF (Terminal Aerodrome Forecast). If the TAF file extract is unobtainable, curated TAF for the deep slice is used and disclosed.

**CAGR.** Compound annual growth rate, used when summarizing TAF outlook.

**NPIAS.** National Plan of Integrated Airport Systems. Development-need classification. Used for capital feasibility, not as the rank itself.

**AIP.** Airport Improvement Program. Federal grant history. Already-funded airports may show lower incremental private return.

**NAS / NAS Status.** National Airspace System live delay / ground-stop feed (`nasstatus.faa.gov`). Overlay for “right now,” not a historical TEOI input.

**ASWS.** Airport Status Web Service (`external-api.faa.gov/asws`). JSON live airport status. Together with NAS Status, this satisfies the brief’s “public APIs” requirement.

**Ground stop / GDP (aviation).** ATC metering. A ground stop holds departures to a destination. GDP here is Ground Delay Program, not gross domestic product.

**ASPM.** Aviation System Performance Metrics. Restricted FAA dataset; we skip it.

**BTS.** Bureau of Transportation Statistics. Source of T-100 traffic and airport-month delay-cause.

**T-100.** BTS airline traffic. Segment or market. Navaid uses **segment** (one takeoff-to-landing). PREZIP bulk files from transtats.

**Segment vs O&D.** A T-100 *segment* is one flight leg. ANC→SEA→JFK is two segments. True origin-and-destination (O&D) for that passenger is ANC→JFK. We do not claim T-100 is O&D.

**PREZIP.** BTS bulk ZIP directory (`transtats.bts.gov/PREZIP`). Large; ingest streams and filters rather than loading the whole archive into memory.

**Load factor (LF).** Passengers / seats on a segment or at an airport. Used in unmet-demand (load-factor gap vs 0.85).

**OTP / delay-cause.** On-time performance. A flight is late at 15+ minutes. We use BTS *airport-month delay-cause totals*, not millions of flight-level OTP rows.

**OurAirports.** Open identity and runway data (`airports.csv`, `runways.csv`): IATA/ICAO, lat/lon, runway counts.

**IATA / ICAO.** IATA is the 3-letter passenger code (BOS). ICAO is the 4-letter operational code (KBOS). Navaid speaks IATA unless noted; leftover rank ties break by ICAO ascending.

**CBSA.** Core-Based Statistical Area. Metro area used to detect leakage (passengers using a nearby airport in the same catchment).

**Curated / gates / constraints.csv.** Hand-authored fields official files lack: gate counts, CBSA catchment, constraint type (landside / mixed / airside / demand-bound), qualitative notes. Gates are not in OurAirports.

**Drop-and-renormalize.** If a TEOI feature is missing (for example no NPIAS for capital feasibility), remove that weight and rescale the remaining weights to sum to 1.0. Never invent the missing count. Disclose the drop in the ScoringTrace and envelope.

---

## Warehouse and RAG

**DuckDB.** Embedded columnar SQL database in one local file. Warehouse, sessions, and document FTS live here. No server process.

**Snapshot.** Frozen tables plus a content hash plus `as_of`, written by ingest. Engine tests and gold eval pin to a snapshot so numbers are reproducible.

**FTS.** Full-text search inside DuckDB over notes keyed by airport. Retrieval is `WHERE airport = ?` plus keyword match. This corpus is tens of notes, not millions of pages.

**Embedding.** A numeric vector for a text chunk. **Not used.** The notes corpus is too small to justify an embedding model.

**RAG.** Retrieve chunks by airport + FTS, then quote them in the answer. RAG never ranks. If corpus notes and T-100 disagree, T-100 wins; the disagreement is an uncertainty.

**Chroma.** A vector database. **Rejected** so we do not run two databases or an embedding model.

---

## Scoring

**TEOI.** Terminal Expansion Opportunity Index, 0–100. Peer-relative score for where *terminal* renovations are most likely to unlock flight and passenger capacity. Busy is not investable; landside-bound airports score high, airside-bound airports are penalized. A TEOI is only meaningful **inside the peer set S you asked about**. It is not a national grade, so BOS can be ~70 versus New England and ~37 if ranked alone.

**Peer set S.** The comparison group for one ranking: a named region (New England) or the airports in the question. Min-max, TEOI, and expansion rank are computed only inside S.

**Peer-relative min-max.** Each feature is scaled 0–1 inside S, not against the entire US. Highest in S → 1; lowest → 0; all equal (including a one-airport set) → 0.5. Regional questions stay regional.

**EXPANSION_RANK.** Closed intent: run `rank_expansion` and return TEOI plus traces for peer set S. This is the New England “strong candidates” question.

**Expansion rank.** The ordinal that comes out of `EXPANSION_RANK` (1, 2, 3… after constraint multipliers). Rank 1 is the strongest *terminal-expansion* candidate **in S**, not FAA hub size and not a US ranking. “Why is #2 above #3?” means explain the traces for those ranks in the last peer set, not re-score one airport.

**Demand pressure, congestion, landside saturation, unmet demand, yield mix, growth outlook, capital feasibility.** The seven TEOI features. Default weights: 0.22, 0.18, 0.18, 0.15, 0.12, 0.10, 0.05 (sum 1.0). Defined in `navaid/scoring/weights.py` when the engines ship.

**Constraint multiplier.** Applied after the weighted sum: landside 1.00, mixed 0.75, airside 0.40, demand-bound 0.30. Encodes the investment thesis: more terminal does not create slots.

**Landside / airside.** Landside is the building: gates, holdrooms, security, bag claim, curb. Airside is runways, slots, weather, ATC, noise curfew. Mixed is both. Demand-bound is weak catchment / low load factor / leakage already served nearby.

**Leakage.** Metro passengers using a nearby airport (SFO demand leaking to OAK/SJC). Part of unmet demand.

**Long-haul.** Default: great-circle distance **>4000 km** (Eurocontrol convention) on T-100 segments. Also reported: international share and optional `pct_over_6h`. Pin `ANC→JFK` at ~5420 km / 3370 mi. Cargo is out unless asked.

**Stable ranker.** Ties share rank (3, 3, 5 — the next rank is skipped). Leftover ties break by ICAO ascending so the order is deterministic.

**Pax / ops.** Passengers / aircraft operations.

---

## Agent

**google-genai.** Official Google Gemini SDK. The only required cloud client. Pin `google-genai<3` until the Chats automatic-function-calling migration is verified.

**gemini-2.5-flash.** Default chat and tool-calling model (`NAVAID_MODEL` unset). Scoring and TEOI traces come from engines, so Flash is the assignment-fit choice: strong function calling, snappy Gradio demo, cheap gold-eval loops.

**gemini-2.5-pro.** Optional override via `NAVAID_MODEL=gemini-2.5-pro` if narration quality needs a bump. Not the default. Does not change numeric correctness.

**Function calling / tools.** The model requests a named tool with JSON arguments, for example `unmet_demand(airport='SFO')`. Closed tool list: `resolve_airport`, `rank_expansion`, `compare_congestion`, `longhaul_share`, `unmet_demand`, `airport_metrics`, `explain_teoi`, `search_corpus`, `get_live_status`.

**AFC.** Automatic function calling. **Disabled.** We intercept every tool call so number lock and TEOI traces are visible Python.

**Number lock.** Every digit in Gemini’s prose must exist in a tool JSON payload. Reject (and rewrite) any invented number.

**EXPLAIN_TEOI.** Closed intent that returns ScoringTraces without re-ranking unless the reconstructed question requires a new peer set. Follow-ups such as “why does BOS have this score?” reuse the last S.

**UNSUPPORTED.** Closed intent for questions outside the product: stocks, restaurants, empty ICAO, “buy AAL.” Other subgoals of a compound question are still answered; the refusal is listed in `unsupported_parts`.

**AAL.** American Airlines ticker. Not an airport. Adversarial gold item.

**LangChain / LlamaIndex / CrewAI.** Agent frameworks we do not use. The reconstruct → decompose → tools → number lock loop must be visible Python we control. (AutoGen and Google ADK are also out.)

---

## Airports in the brief

**LAX.** Los Angeles International.

**SNA.** John Wayne Airport, Santa Ana. High-utilization and curfew-capped. Not SAT (San Antonio).

**LA.** Resolves to LAX, not the whole Los Angeles metro.

**SFO / OAK / SJC.** San Francisco, Oakland, San Jose. Bay Area leakage set for unmet-demand at SFO.

**ANC.** Ted Stevens Anchorage International. Canonical long-haul example.

**BOS, BDL, PVD, PWM, MHT, BTV, BGR, ORH.** New England deep slice: Boston, Bradley (Hartford), T. F. Green (Providence), Portland (Maine), Manchester-Boston, Burlington, Bangor, Worcester.

**New England.** Connecticut, Maine, Massachusetts, New Hampshire, Rhode Island, Vermont.

**PWM.** Portland **Maine**, not PDX (Portland, Oregon).

---

## Finance we will not fake

**PFC / NPV / capex.** Passenger Facility Charge, net present value, capital expenditure. Navaid does not compute airport finance. Profit is proxied by **capacity unlock** (TEOI), and product copy says so.

---

## Local run

**Local.** DuckDB file on disk, FastAPI on `127.0.0.1`, Gradio in the browser. The only cloud call is Gemini.

**GEMINI_API_KEY / gcloud ADC.** Chat needs one of: a Gemini Developer API key, or Google Cloud Application Default Credentials from `gcloud auth login --update-adc` plus a Vertex project. Engine tests need neither. `NAVAID_OFFLINE=1` skips government HTTP and uses local DuckDB only.

**pytest.** Unit-test runner. Engine tests pin to fixtures; gold eval is a separate script, not an LLM-as-judge product.
