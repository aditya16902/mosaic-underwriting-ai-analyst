# MosAIc — Underwriting Performance Intelligence

MosAIc is a weekly underwriting performance intelligence platform built for Mosaic Insurance (Lloyd's syndicates 1609 and 2610, eight lines of business). It ingests four weekly CSV feeds, detects four categories of underwriting signal, enriches each with a date-disclosed root cause, ranks them through a two-stage LLM chain, and produces three outputs per run: a dashboard, a CUO-style narrative briefing, and a downloadable audit snapshot. A text-to-SQL chat agent sits alongside the dashboard so a user can ask follow-up questions in plain English against that run's data.

## Setup (local, no Docker)

```bash
cd /Users/aditya16902/Desktop/Github/Mosaic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Add keys to `.env` (see `.env.example`):

```
OPENAI_API_KEY=sk-...
SECRET_KEY=...                    # JWT signing key — set a real value outside localhost
CORS_ORIGINS=http://localhost:5173,http://localhost:3000   # comma-separated, defaults to local dev
# DATABASE_URL=...                # leave unset locally — defaults to a SQLite file; see Database section
LANGFUSE_PUBLIC_KEY=pk-lf-...     # optional — enables tracing
LANGFUSE_SECRET_KEY=sk-lf-...     # optional
```

Initialise the database (creates tables, seeds the default schedule — does **not** create any user):

```bash
python -m backend.db.database
```

Create real user accounts (there is no hardcoded username/password anywhere in the codebase — see Auth & Users below):

```bash
cp scripts/seed_users.example.json scripts/seed_users.local.json
# edit seed_users.local.json with real username/password/display_name entries
python -m scripts.seed_users
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

## Setup (Docker, local)

A `docker-compose.yml` at the project root runs the full stack — backend, frontend (built and served by nginx), and a local Postgres container — so the containerized app can be verified end to end before anything touches AWS. This is for local verification only; it is **not** what runs in production. On AWS, ECS Fargate runs the backend and frontend images separately, RDS replaces the Postgres container, and secrets come from Secrets Manager rather than this file's environment block.

```bash
docker compose up --build
```

Frontend: `http://localhost:5174` (intentionally not 5173, so it doesn't collide if `npm run dev` is also running). Backend: `http://localhost:8000`. The Postgres container starts empty — seed it the same way as local dev, just pointed at the container instead of the local SQLite file:

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:devpass@localhost:5432/mosaic"
python -m scripts.seed_users
```

Two Dockerfiles exist rather than one, since the two services have nothing in common at build time: `Dockerfile.backend` installs `requirements.txt` and runs uvicorn directly. `Dockerfile.frontend` is a two-stage build — stage one runs `npm run build` inside a Node image, stage two copies just the resulting static files into an nginx image and discards the Node toolchain entirely, so the final image is small and contains no source code, only built assets. `nginx.conf` adds the one thing a plain static file server doesn't do by default: falling back to `index.html` for any path that doesn't match a real file, which is required for React Router's client-side routes (`/reports/:runId`) to survive a page refresh rather than 404ing.

One constraint worth knowing: `VITE_API_BASE` (the backend URL the frontend calls) is baked into the JS bundle at **build** time, not read at container start — Vite inlines `import.meta.env.*` values during `vite build`, and a static build has no equivalent of a server reading an env var at runtime. This means if the backend's URL ever changes (a new load balancer DNS name, a new domain), the frontend image needs rebuilding with a new `--build-arg VITE_API_BASE=...`, not just restarting.

---

## Dependency management

`requirements.txt` is the hand-curated source of truth — pinned top-level packages only, not a `pip freeze` dump of every transitive dependency pip happened to resolve. This stays readable and makes it clear which packages the app actually depends on versus what something else pulled in. **uv is not currently used in this project** — it was discussed as a faster, lockfile-based alternative to plain pip (uv generates a `uv.lock` with exact, hashed versions of every package including transitive deps, on top of the same human-readable top-level list), but adopting it was deferred rather than implemented, since the existing pinned `requirements.txt` was already sufficient for this project's size and switching mid-build risked destabilising a working setup for marginal benefit at three users. Worth revisiting if dependency resolution ever becomes slow or flaky, but as of this writing, `pip install -r requirements.txt` is what both local dev and `Dockerfile.backend` use.

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

**Packaging (`backend/report/snapshot.py`).** Every run writes a full audit bundle to `runs/{run_id}/`: the raw CSVs as fed in, `merged_metrics.xlsx` (formatted), `merged_metrics.db` (SQLite, used by the chat agent — this is a separate, per-run file, unrelated to the application's own SQLite/Postgres database described below), the LLM1 input/output JSON, both prompt text files actually used, a markdown `signals_and_enrichment.md` audit document, the narrative HTML, `dashboard_data.json`, and finally a zip of everything in the directory. The zip is built last and simply archives every file already present — there's no allowlist, so anything written earlier in the run is automatically included.

**Run IDs** use the format `YYYYMMDD_HHMMSS_week<report_week>_<4hexsuffix>` — sortable and human-scannable, generated in `backend/pipeline/orchestrator.py`.

---

## Database

Runs against either SQLite or Postgres with the **same SQL**, via SQLAlchemy Core (`backend/db/database.py`) — not an ORM, no migration framework, just enough abstraction to handle the real differences between the two engines (parameter placeholders, autoincrement/identity syntax, upsert syntax, schema introspection) without maintaining two parallel implementations. Controlled by a single env var: `DATABASE_URL` unset defaults to a local SQLite file (`mosaic.db`), set to a Postgres connection string (`postgresql+psycopg2://user:pass@host:5432/dbname`) switches everything — local dev, Docker Compose, and AWS RDS — to Postgres with no code changes. This was validated locally against a real Postgres container before being used in `docker-compose.yml`.

Three tables: `users` (real named accounts, bcrypt-hashed passwords — see Auth & Users below), `reports` (one row per run: run_id, week range, status, source `manual`/`automated`, and JSON blobs of signals/concerns/opportunities/anomalies for fast history listing without touching the filesystem), and `schedule_config` (single-row table holding the automated report cadence).

---

## Auth & users

There is no hardcoded username or password anywhere in the codebase. Passwords are bcrypt-hashed via `passlib` (`backend/auth/passwords.py`) — a real salted, slow-by-design hashing scheme, not the unsalted SHA-256 this app used in an earlier iteration. Login (`POST /auth/login`) verifies against a dummy hash even when the username doesn't exist, so response timing can't be used to enumerate valid accounts.

Accounts are created with `scripts/seed_users.py`, which reads plaintext credentials from a **local, gitignored** file (`scripts/seed_users.local.json` — never committed; `scripts/seed_users.example.json` is the safe-to-commit placeholder template) and writes bcrypt hashes into the `users` table. Re-running the script is safe and idempotent — it upserts by username, so it's also how a password gets rotated. The same script works against Postgres by exporting `DATABASE_URL` first, which is how the three real accounts get created in any new environment (Docker Compose's Postgres container, RDS on AWS) — seed once per database, not once per environment file.

The frontend has a real login page (`frontend/src/pages/LoginPage.tsx`) with a show/hide toggle on the password field. There is no auto-login and no demo credential anywhere in frontend code.

---

## API

All routes except `/auth/login` and `/health` require a bearer JWT. Two routes (`narrative`, `snapshot/zip`) also accept the token as a `?token=` query param via `verify_token_flexible`, since browser-initiated downloads/`window.open` can't attach an Authorization header.

```
POST   /auth/login                              {username, password} → JWT
GET    /auth/me                                  current user's username + display_name
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

`backend/agents/text_to_sql/agent.py` takes a natural-language question, generates SQL against that run's `merged_metrics.db` (or the latest run if none specified), executes it through a hardened executor, and interprets the result back into a business-language answer. `sql_executor.py` only permits `SELECT` against the `merged_metrics` table, blocks DDL/DML keywords, and caps results at 500 rows. Prompts are versioned (`sql_gen_v1`/`v2`, `sql_interpret_v1`/`v2` — v2 are intentionally degraded prompts used only to validate that the eval framework actually detects regressions). This agent's database is always SQLite regardless of what `DATABASE_URL` is set to — it's a self-contained per-run artifact, not the application's database, and is unaffected by the SQLite/Postgres switch described above.

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

Key structure: `pages/LoginPage.tsx` (real login form, no auto-login), `lib/auth.ts` (login/logout/session-check, no hardcoded credentials), `lib/api.ts` (typed fetch wrapper, JWT-aware), `lib/types.ts` (mirrors backend response shapes exactly), `lib/reportEvents.ts` (a tiny pub/sub so the sidebar's report history refetches immediately after a new report is generated or deleted, without prop-drilling through `App.tsx`), `components/dashboard/*` (portfolio header, concern cards with expandable root-cause detail, LoB table, GWP trend chart, hit-rate heatmap, anomalies section), `components/layout/Sidebar.tsx` (report history with inline two-step delete confirmation, severity rail per row, signed-in-as display name with sign-out), `components/layout/ResizableChatPanel.tsx` (VS Code-style drag-resizable chat panel hosting the agent).

The GWP trend chart and hit-rate heatmap consume the pipeline's `weekly_series` field directly. Both gracefully no-op (rather than crash) on reports generated before this field existed, via `data.weekly_series ?? []`.

---

## Known limitations

The local scheduler (`APScheduler`, started in-process by `backend/api/routes.py::_start_scheduler`) only fires while the FastAPI process is running and is explicitly intended to be replaced by an AWS EventBridge rule invoking a Lambda/Fargate task directly — that's a clean removal, not a refactor, when the time comes. `DELETE /reports/{run_id}` is genuinely irreversible (it runs `shutil.rmtree` on the run directory) — there's no soft-delete or trash state. The `runs/` directory (every report's raw CSVs, narrative, snapshot zip) lives on local disk, which is fine for local dev and Docker Compose but won't survive on Fargate's ephemeral container filesystem — this needs to move to S3 before the backend runs on Fargate, and is tracked as upcoming work, not yet implemented.

---

## Pre-deployment hygiene

`.gitignore` excludes `.env`, `venv/`, `frontend/node_modules/`, `frontend/dist/`, `mosaic.db`, `runs/`, `evals/results/`, and `scripts/seed_users.local.json` (deliberately not `evals/baselines/`, `evals/fixtures/`, or `scripts/seed_users.example.json`, which are reference data/templates meant to be version-controlled). `.dockerignore` excludes the same local-only files from ever entering a Docker build context. CORS origins, the JWT signing key, and the database connection string are all environment-driven (`CORS_ORIGINS`, `SECRET_KEY`, `DATABASE_URL`) rather than hardcoded — a startup warning prints if `SECRET_KEY` is left at its default dev value.

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

# Full containerized stack (backend + frontend + Postgres)
docker compose up --build
```

Manual checks worth doing after any frontend/backend change: log in with a real seeded account; generate a report, confirm it appears in history immediately; delete a report, confirm it disappears and (if it was the one on screen) the view redirects; ask the chat agent a question grounded in the current report and one slightly out of scope; open the narrative and download the snapshot zip via the buttons (these use `?token=` auth, distinct from the rest of the app); change and save the schedule settings; sign out and confirm the login page reappears rather than silently re-authenticating.

---

## AWS deployment status

Stages completed so far, in order: (1) database layer migrated to run against either SQLite or Postgres via the same code, validated against a real local Postgres container; (2) both services Dockerized (`Dockerfile.backend`, `Dockerfile.frontend`, `nginx.conf`) and verified together via `docker-compose.yml`; (3) git initialized, secrets confirmed excluded, pushed to a remote. Not yet done: provisioning real AWS resources (ECR, RDS, S3 for the `runs/` directory, Secrets Manager), wiring ECS Fargate + EventBridge + CloudFront, and the S3 migration for run artifacts noted under Known Limitations above.
