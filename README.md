# MosAIc — Underwriting Performance Intelligence

MosAIc is a weekly underwriting performance intelligence platform built for Mosaic Insurance (Lloyd's syndicates 1609 and 2610, eight lines of business). It ingests four weekly CSV feeds, detects four categories of underwriting signal, enriches each with a date-disclosed root cause, ranks them through a two-stage LLM chain, and produces three outputs per run: a dashboard, a CUO-style narrative briefing, and a downloadable audit snapshot. A text-to-SQL chat agent sits alongside the dashboard so a user can ask follow-up questions in plain English against that run's data.

## Setup

```bash
cd /Users/aditya16902/Desktop/Github/Mosaic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Add keys to `.env` (see `.env.example`):

```
OPENAI_API_KEY=sk-...
LANGFUSE_PUBLIC_KEY=pk-lf-...     # optional — enables tracing
LANGFUSE_SECRET_KEY=sk-lf-...     # optional
SECRET_KEY=...                    # JWT signing key — set a real value outside localhost
CORS_ORIGINS=http://localhost:5173,http://localhost:3000   # comma-separated, defaults to local dev
```

Initialise the database (creates tables, seeds `admin`/`admin123`, seeds default schedule):

```bash
python -m backend.db.database
```

Frontend:

```bash
cd frontend
npm install
npm run dev      # http://localhost:5173
```

Backend:

```bash
uvicorn main:app --reload --port 8000
# equivalently: uvicorn backend.api.routes:app --reload --port 8000
```

---

## Architecture — layer by layer

Each weekly run flows through five backend layers, then a packaging layer, then is exposed via the API to the frontend.

**Layer 1 — Ingestion (`backend/pipeline/ingestor.py`).** Loads the four source CSVs (submissions, premium, pipeline, loss indicators), merges them on `(week_ending, lob)`, and computes derived metrics: hit rate, GWP-vs-plan ratio (weekly and YTD), combined ratio (loss ratio + a per-LoB assumed expense ratio from `LOB_PROFILES`), loss ratio velocity (week-over-week change), decline rate, and NTU (not-taken-up) rate. An optional `week_start`/`week_end` filter is applied here for custom-range report generation.

**Layer 2 — Signal detection (`backend/pipeline/signals.py`).** Four independent detectors run per LoB against thresholds in `SIGNAL_CONFIG`:
- **S1 — Structural underperformance.** GWP-vs-plan ratio below 0.75 in ≥80% of weeks.
- **S2 — Hit rate collapse.** Compares a baseline window against a recent window (recent window size = `max(3, round(total_weeks × 0.25))`, baseline = everything before it). Fires if the drop is ≥15 percentage points or ≥50% relative, and ≥75% of the recent window sits below the baseline's 25th percentile.
- **S3 — Loss ratio deterioration.** Loss ratio has risen for ≥4 consecutive weeks AND the latest value exceeds the LoB's target.
- **S4 — Profitable outperformance.** GWP-vs-plan ratio above 1.10 in ≥75% of weeks AND combined ratio below 100% (underwriting profit).

**Layer 3a — Root cause enrichment (`backend/pipeline/enrichment.py`).** Every finding from S1–S4 gets a `root_cause_detail` string that explicitly names the dates and window sizes behind its numbers — this was a deliberate fix after early versions stated figures like "decline rate 19.1%" without disclosing they were a 4-week average, not a full-period figure. S1 discloses its fixed 4-week recent window with exact dates; S2 discloses both the baseline window and recent window with exact dates and the percentile-breach detail; S3 discloses the full trend period and shows the underwriting-loss calculation (`YTD actual GWP × (combined ratio − 100%)`); S4 adds a GWP/loss-ratio correlation and the paired weekly series used by its chart.

**Layer 3b — Anomaly detection (`backend/pipeline/anomalies.py`).** Independent of the four signals: claims spikes (z-score > 2.5 vs that LoB's own mean), stalled pipeline (avg days in pipeline ≥ 45), funnel divergence (submissions spike ≥40% WoW while quoted count doesn't follow), and missing data flags across key columns.

**Layer 4 — Prioritisation (`backend/pipeline/prioritiser.py`).** Assigns each finding an `impact_score` in £ (GWP at risk for S1, open pipeline GWP for S2, estimated underwriting loss for S3, GWP surplus for S4), ranks them, and assembles the full payload: portfolio summary, per-LoB latest-week snapshot, a full `weekly_series` (every LoB × every week, GWP ratio + hit rate — this is what powers the dashboard's trend chart and heatmap), ranked concerns/opportunities, anomalies, and signal counts.

**Layer 5 — Two-LLM chain (`backend/llm/chain.py`).** LLM1 (`gpt-4o-mini`, low temperature) receives the full payload and returns a structured JSON prioritisation: top 3 concerns ranked, top opportunity, one-line rationales, analyst notes. LLM2 (`gpt-4o`) receives the same payload plus LLM1's output and writes the full CUO narrative briefing as standalone HTML — instructed to disclose methodology (name the actual window/dates whenever a figure is windowed rather than full-period) and show calculation derivations for financial figures, mirroring the same discipline enforced in Layer 3a. Both calls are traced to Langfuse when configured (see Observability below).

**Packaging (`backend/report/snapshot.py`).** Every run writes a full audit bundle to `runs/{run_id}/`: the raw CSVs as fed in, `merged_metrics.xlsx` (formatted), `merged_metrics.db` (SQLite, used by the chat agent), the LLM1 input/output JSON, both prompt text files actually used, a markdown `signals_and_enrichment.md` audit document, the narrative HTML, `dashboard_data.json`, and finally a zip of everything in the directory. The zip is built last and simply archives every file already present — there's no allowlist, so anything written earlier in the run is automatically included.

**Run IDs** use the format `YYYYMMDD_HHMMSS_week<report_week>_<4hexsuffix>` — sortable and human-scannable, generated in `backend/pipeline/orchestrator.py`.

---

## Database

SQLite locally (`mosaic.db`), intended to move to Postgres on AWS (`backend/db/database.py` already isolates all access behind `get_connection()`, so the migration is a connection-string change, not a rewrite). Three tables: `users` (single seeded admin account, sha256-hashed password — see Known Limitations), `reports` (one row per run: run_id, week range, status, source `manual`/`automated`, and JSON blobs of signals/concerns/opportunities/anomalies for fast history listing without touching the filesystem), and `schedule_config` (single-row table holding the automated report cadence).

---

## API

All routes except `/auth/login` and `/health` require a bearer JWT. Two routes (`narrative`, `snapshot/zip`) also accept the token as a `?token=` query param via `verify_token_flexible`, since browser-initiated downloads/`window.open` can't attach an Authorization header.

```
POST   /auth/login                              admin/admin123 → JWT
GET    /auth/me
GET    /data/bounds                              min/max week available, for the date picker
POST   /reports/generate                         {week_start?, week_end?} → runs the full pipeline
GET    /reports                                  history list
GET    /reports/{run_id}                         single report row
DELETE /reports/{run_id}                         deletes DB row AND the entire runs/{run_id} directory — irreversible
GET    /reports/{run_id}/dashboard                dashboard_data.json
GET    /reports/{run_id}/narrative                narrative HTML (renders directly)
GET    /reports/{run_id}/snapshot/files           list of files in the run directory
GET    /reports/{run_id}/snapshot/download/{name} single file download
GET    /reports/{run_id}/snapshot/zip             full audit zip
GET    /schedule / PUT /schedule                  automated report cadence
POST   /chat                                      {question, run_id?} → text-to-SQL agent
GET    /health
```

---

## Text-to-SQL chat agent

`backend/agents/text_to_sql/agent.py` takes a natural-language question, generates SQL against that run's `merged_metrics.db` (or the latest run if none specified), executes it through a hardened executor, and interprets the result back into a business-language answer. `sql_executor.py` only permits `SELECT` against the `merged_metrics` table, blocks DDL/DML keywords, and caps results at 500 rows. Prompts are versioned (`sql_gen_v1`/`v2`, `sql_interpret_v1`/`v2` — v2 are intentionally degraded prompts used only to validate that the eval framework actually detects regressions).

---

## Eval & regression framework

Two parallel eval frameworks, both fixture-driven and stored under `evals/`.

**Pipeline eval** (`evals/runners/eval_runner.py`) runs synthetic fixtures (`evals/fixtures/{easy_single_signal, medium_two_signals, hard_all_signals, edge_borderline, adversarial_blip}.json`) through the full pipeline and both LLM stages, scoring signal recall deterministically (did detection find the right LoBs for each expected signal) and using an LLM judge (`evals/judges/llm1_judge.py`, `llm2_judge.py`) for ranking correctness, rationale faithfulness, and narrative quality. `--no-llm` runs the deterministic signal-detection check only, with no API cost — useful as a fast post-change sanity check. Scores are saved against a baseline (`evals/baselines/baseline_scores.json`) and `regression.py` flags any metric that drops more than 5 points from baseline.

**Agent eval** (`evals/runners/agent_eval_runner.py`) runs golden questions (`evals/fixtures/agent_*.json` — easy direct lookup, medium aggregation/trend, hard report-grounded/ambiguous, adversarial out-of-scope/schema-trap) through the chat agent. SQL correctness is scored deterministically (`evals/judges/sql_comparator.py` does loose value-set comparison ignoring column order/naming, plus a schema-adherence regex check for hallucinated column names), and answer quality through an LLM judge (`evals/judges/agent_judge.py`) on faithfulness, report-grounding, tone, specificity, and refusal-correctness for the adversarial cases.

Both frameworks were validated by intentionally degrading prompts (`*_v2.txt` files) and confirming the eval/regression machinery actually catches the regression — v2 prompts measurably dropped tone/directness scores and, for the agent, caused hallucinated column references that the schema check correctly flagged.

---

## Observability (Langfuse)

Free tier at `cloud.langfuse.com`. When keys are set, every pipeline run produces a trace (`weekly_performance_analyst`) with child spans for LLM1 and LLM2 — each logging the model, prompt version, token usage, and a preview of the output — under a session ID format `weekly_report_{week_ending}`. The chat agent shares the same session ID convention (`backend/llm/observability.py::make_session_id`) so a report's generation trace and any chat questions asked about it can be correlated in the Langfuse UI.

Two separate Langfuse client instances exist by design, not by accident: `backend/llm/chain.py` uses the `@observe` decorator pattern (its own module-level client, required by that decorator's internals), while `backend/llm/observability.py::get_langfuse()` is a lazily-initialised client used by code that creates traces manually (the chat agent). These were kept apart after diagnosing a real trace-flush-timing bug — flushing too early, before the decorator finished writing to its buffer, silently dropped traces. `run_llm_chain()` flushes only after the decorated function fully returns, with a short sleep to let the buffer settle first.

---

## Frontend

React + Vite + TypeScript + Tailwind. Paper-and-ledger visual design: warm off-white background, a signature colored "severity rail" down the left edge of concern cards and history rows, Source Serif for display type, Inter for body text, JetBrains Mono for all numeric values.

Key structure: `lib/api.ts` (typed fetch wrapper, JWT-aware), `lib/types.ts` (mirrors backend response shapes exactly), `lib/reportEvents.ts` (a tiny pub/sub so the sidebar's report history refetches immediately after a new report is generated or deleted, without prop-drilling through `App.tsx`), `components/dashboard/*` (portfolio header, concern cards with expandable root-cause detail, LoB table, GWP trend chart, hit-rate heatmap, anomalies section), `components/layout/Sidebar.tsx` (report history with inline two-step delete confirmation, severity rail per row), `components/layout/ResizableChatPanel.tsx` (VS Code-style drag-resizable chat panel hosting the agent).

The GWP trend chart and hit-rate heatmap consume the pipeline's `weekly_series` field directly. Both gracefully no-op (rather than crash) on reports generated before this field existed, via `data.weekly_series ?? []`.

---

## Known limitations

Password hashing uses unsalted `hashlib.sha256`, not bcrypt/argon2 — acceptable for this single-seeded-user (`admin`/`admin123`) assessment demo, but should be hardened with a proper salted scheme (e.g. passlib + bcrypt, or argon2) before any real multi-user deployment. The local scheduler (`APScheduler`, started in-process by `backend/api/routes.py::_start_scheduler`) only fires while the FastAPI process is running and is explicitly intended to be replaced by an AWS EventBridge rule invoking a Lambda/Fargate task directly — that's a clean removal, not a refactor, when the time comes. `DELETE /reports/{run_id}` is genuinely irreversible (it runs `shutil.rmtree` on the run directory) — there's no soft-delete or trash state.

---

## Pre-deployment hygiene

`.gitignore` now excludes `.env`, `venv/`, `frontend/node_modules/`, `frontend/dist/`, `mosaic.db`, `runs/`, and `evals/results/` (deliberately not `evals/baselines/` or `evals/fixtures/`, which are reference data meant to be version-controlled). CORS origins and the JWT signing key are both environment-driven (`CORS_ORIGINS`, `SECRET_KEY` in `.env`) rather than hardcoded — a startup warning prints if `SECRET_KEY` is left at its default dev value. Docker/AWS infrastructure itself (Dockerfiles, ECS/Fargate task definitions, EventBridge rules, RDS migration) is intentionally out of scope for this pass — these env-driven config points exist so that work can proceed without first refactoring hardcoded values.

A few files predate this cleanup pass and need manual removal (no file-delete capability is available to make these edits directly): `debug_langfuse.py`, `test_langfuse_direct.py`, and `payload_out.json` at the project root were one-off diagnostic scripts/output from earlier debugging sessions, and `frontend/tsconfig.app.json` is an orphaned stray file never referenced by the actual build config. Run:

```bash
rm debug_langfuse.py test_langfuse_direct.py payload_out.json frontend/tsconfig.app.json
```

---

## Testing after a change

```bash
# Backend imports cleanly
python -c "from backend.api.routes import app"

# Pipeline dry run (no LLM cost)
python test_runner.py dry --to 2024-09-15

# Full pipeline + LLM chain
python test_runner.py llm

# Pipeline eval, no LLM cost — fastest signal-detection sanity check
python evals/runners/eval_runner.py --no-llm

# Full pipeline eval with judges
python evals/runners/eval_runner.py

# Agent eval, no LLM cost
python evals/runners/agent_eval_runner.py --no-llm

# Full agent eval with judges
python evals/runners/agent_eval_runner.py

# Regression check against baseline
python evals/runners/regression.py evals/results/eval_v1_<timestamp>.json
python evals/runners/agent_regression.py evals/results/agent_eval_v1_<timestamp>.json

# Frontend — catches TypeScript errors the dev server tolerates
cd frontend && npm run build

# Frontend dev server
cd frontend && npm run dev

# Backend dev server
uvicorn main:app --reload --port 8000
```

Manual checks worth doing after any frontend/backend change: generate a report, confirm it appears in history immediately; delete a report, confirm it disappears and (if it was the one on screen) the view redirects; ask the chat agent a question grounded in the current report and one slightly out of scope; open the narrative and download the snapshot zip via the buttons (these use `?token=` auth, distinct from the rest of the app); change and save the schedule settings.
