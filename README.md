# Navaid

Local-first **Airport Investment Intelligence Agent**. Public aviation files land in one DuckDB warehouse. Deterministic engines compute TEOI (with a full scoring trace), unmet demand, long-haul share, and congestion compares. Gemini may narrate those traces; it never invents a rank.

Python **3.12**. One local database. The only required cloud call is Google Gemini via `google-genai`, authenticated with **`gcloud auth login --update-adc`** (Vertex AI) or a `GEMINI_API_KEY`. Default chat model: **gemini-2.5-flash**.

**Not used:** LangChain, LangGraph, LlamaIndex, CrewAI, Chroma, FAISS, Pinecone, or any embedding model. Retrieval is airport-keyed DuckDB FTS.

## Documents

| Doc | What it is |
| --- | --- |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Assignment deliverable: scoring methodology, tradeoffs, where Gemini is used |
| [docs/GLOSSARY.md](docs/GLOSSARY.md) | Every product and aviation term |
| [docs/DECISION_LOG.md](docs/DECISION_LOG.md) | How we investigated data, how we calculate, why these packages |

The designed analyst site serves the same three docs at `/architecture`, `/glossary`, and `/decisions`.

**Deploy:** GitHub Pages (frontend) + Cloud Run (API). One-time setup is in [docs/DEPLOY.md](docs/DEPLOY.md). Push to `main` after adding `GCP_PROJECT_ID` and `GCP_SA_KEY`.

## Local run

From the repo root.

### 1. Virtualenv and install

Windows (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
```

Unix/macOS:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
```

`pip install -e .` installs the `navaid` package in editable mode and registers the `navaid` console script.

### 2. Authenticate Gemini

Preferred: Google Cloud user login + Application Default Credentials (what Python client libraries actually read). `gcloud auth login` by itself is not enough.

```powershell
gcloud auth login --update-adc
gcloud config set project YOUR_GCP_PROJECT
```

Set `GOOGLE_CLOUD_PROJECT` in `.env` if you do not want to rely on `gcloud config`. Vertex region defaults to `us-central1`.

Optional: a Gemini Developer API key instead of Vertex.

Edit `.env`:

| Variable | Default | Meaning |
| --- | --- | --- |
| *(gcloud ADC)* | | After `gcloud auth login --update-adc` plus a Cloud project, chat/STT/TTS work with no API key. |
| `GOOGLE_CLOUD_PROJECT` | *(gcloud config)* | GCP project for Vertex AI. Also reads `GCLOUD_PROJECT`. |
| `GOOGLE_CLOUD_LOCATION` | `us-central1` | Vertex region. |
| `GOOGLE_GENAI_USE_VERTEXAI` | `0` | Set `1` to force Vertex even if `GEMINI_API_KEY` is set. |
| `GEMINI_API_KEY` | *(empty)* | Gemini Developer API key (optional if ADC is present). `GOOGLE_API_KEY` is an alias. |
| `NAVAID_MODEL` | `gemini-2.5-flash` | Chat/tool model. Keep Flash unless you want `gemini-2.5-pro` for narration. Numbers still come from engines. |
| `NAVAID_OFFLINE` | `0` | Set to `1` to skip government HTTP. Engines read the local DuckDB snapshot only. Chat still needs Gemini auth. |

### 3. Build the warehouse snapshot

```powershell
python scripts/build_snapshot.py
```

Offline / fixture-only (no government HTTP):

```powershell
python scripts/build_snapshot.py --offline --force-fixtures
```

Writes `data/warehouse/navaid.duckdb`. Chat, Gradio, the site workbench, and `navaid ask` all require this file.

### 4. Analyst site (FastAPI + uvicorn) — port 8000

```powershell
uvicorn navaid.api.app:app --host 127.0.0.1 --port 8000
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

| Path | Page |
| --- | --- |
| `/` | Landing / investment thesis |
| `/workbench` (also `/app`) | Analyst workbench over `POST /ask` |
| `/methodology` | TEOI formula and constraint multipliers |
| `/glossary` | [docs/GLOSSARY.md](docs/GLOSSARY.md) |
| `/decisions` | [docs/DECISION_LOG.md](docs/DECISION_LOG.md) |
| `/architecture` | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| `GET /health` | Process health, model name, warehouse present |
| `GET /eval/summary` | Latest gold-eval KPIs (`eval/runs/latest.json`) |
| `POST /ask` | Same `Answer` contract as the CLI and Gradio |

### 5. Gradio workbench — port 7860

```powershell
navaid ui
```

Optional: `navaid ui --host 127.0.0.1 --port 7860`. Opens [http://127.0.0.1:7860](http://127.0.0.1:7860). Same orchestrator as `POST /ask` (in-process, not HTTP-only).

Equivalent: `python -m navaid.ui.gradio_app`.

**Tools only** checkbox sets `use_gemini=false` (engines + template narration) for demos without Gemini auth. If an API key or gcloud ADC is present, narration is on unless you check the box.

Tabs: Chat, Steps, Rankings, TEOI waterfall, Compare, Citations, Eval. Envelope cards stay visible on every turn. Mic → Gemini STT; optional Gemini TTS. No OpenAI Whisper.

### 6. CLI ask

```powershell
navaid ask --json "Which airports in New England are strong candidates for terminal expansion?"
navaid ask --json --no-gemini "Compare LA and Santa Ana airport congestion levels."
navaid --help
python -m navaid --help
```

`--json` prints the structured `Answer` (reconstructed query, subgoals, steps, TEOI traces, envelope). `--session <id>` continues a DuckDB session for follow-ups (“those two”, “why is #2 above #3?”). `--no-gemini` skips narration.

### 7. Gold eval

Default is engines-only (`use_gemini=false`) so gold numbers stay deterministic and cheap:

```powershell
python eval/run_eval.py
python eval/run_eval.py --use-gemini false
python eval/run_eval.py --ids assign_ne_expansion,assign_sfo_unmet
```

Writes `eval/runs/<timestamp>.json` and `eval/runs/latest.json`. `GET /eval/summary` reads the latest file.

### 8. Tests

```powershell
pytest
```

Engine and schema tests do not need Gemini credentials. The first warehouse-backed test builds a fixture snapshot if `data/warehouse/navaid.duckdb` is missing.

## Assumptions (stated in every envelope)

- **Profit proxy is capacity unlock, not NPV.** We do not compute PFC, bond, capex, or airline-equity returns. High TEOI means a terminal project is more likely to raise throughput, not that NPV is positive.
- **Long-haul default is 4000 km** great-circle on T-100 **segments** (Eurocontrol). Also report international share and optional `pct_over_6h`. Cargo is out unless asked. T-100 is not true O&D (ANC→SEA→JFK is two segments). Pin `ANC→JFK` at ~5420 km.
- **New England** = CT, ME, MA, NH, RI, VT (BOS, BDL, PVD, PWM, MHT, BTV, BGR, ORH in the deep slice). PWM is Portland **Maine**, not PDX.
- US commercial primary airports in the warehouse; extra curated depth for New England + LAX/SNA + SFO/OAK/SJC + ANC.
- `"LA"` resolves to LAX, not the metro. `"Santa Ana"` resolves to SNA, not SAT (San Antonio).
- Live FAA NAS/ASWS is operations delay overlay, not a TEOI input and not passenger demand.
- Missing gates / TAF / NPIAS are **dropped and renormalized**, never invented, and disclosed on the ScoringTrace and envelope.
- Snapshot older than 90 days is always an envelope uncertainty.
- Gemini is the only required cloud service.

## What the agent always returns

Every `/ask` (and `navaid ask`) is a Pydantic `Answer`: reconstructed query, one section per subgoal, ordered `steps[]`, full `teoi_traces[]` whenever ranking ran, tables, envelope (assumptions / uncertainties / out-of-scope / confidence / sources / `as_of`), citations, and `unsupported_parts` for refusals (e.g. “buy AAL”) without dropping the rest.

Gemini’s prose may quote those fields. A **number lock** rejects digits that were not in a tool payload. RAG never ranks; T-100 wins factual disagreement.

## Layout

- `navaid/config.py` — URLs, TEOI weights (sum to 1.0), long-haul km, constraint multipliers, model name, offline flag
- `navaid/schemas.py` — locked Pydantic v2 contracts (`Envelope`, `ScoringTrace`, `Answer`, …)
- `navaid/scoring/` — TEOI, unmet, long-haul, congestion, stable ranker
- `navaid/agent/` — reconstruct, decompose, Gemini tools, number lock, sessions
- `navaid/api/` — FastAPI `/ask` plus the designed site
- `navaid/ui/` — Gradio workbench and site templates
- `navaid/warehouse/` — one DuckDB file (metrics, sessions, FTS `doc_chunks`; no embeddings table)
- `scripts/build_snapshot.py` — ingest into DuckDB
- `scripts/export_site.py` — static GitHub Pages export
- `scripts/bootstrap_gcp.ps1` — one-time Cloud Run / Artifact Registry / IAM
- `.github/workflows/deploy.yml` — pytest, Cloud Run, GitHub Pages
- `eval/gold/` + `eval/run_eval.py` — gold set and KPI runner
- `tests/` — pytest
- `docs/` — architecture, glossary, decision log
