# MosAIc — Underwriting Performance Intelligence

MosAIc is a weekly underwriting performance intelligence platform built for Mosaic Insurance (Lloyd's syndicates 1609 and 2610, eight lines of business). It ingests source data from a Postgres database, detects four categories of underwriting signal, enriches each with a date-disclosed root cause, ranks them through a two-stage LLM chain, and produces three outputs per run: a dashboard, a CUO-style narrative briefing, and a downloadable audit snapshot stored in S3. A text-to-SQL chat agent sits alongside the dashboard so a user can ask follow-up questions in plain English against that run's data.

**Live deployment:** `http://mosaic-frontend-alb-981712543.eu-west-2.elb.amazonaws.com`

---

## AWS deployment (current state — fully live)

All infrastructure runs in `eu-west-2` (London) under AWS account `211125777624`. The stack:

| Component | Resource |
|---|---|
| Frontend | ECS Fargate (`mosaic-frontend-service`), served by nginx, behind `mosaic-frontend-alb` |
| Backend | ECS Fargate (`mosaic-backend-service`), FastAPI/uvicorn, behind `mosaic-alb` |
| Database | RDS Postgres `mosaic-db` (`mosaic-db.cloaowwa646s.eu-west-2.rds.amazonaws.com`) |
| Run artifacts | S3 bucket `mosaic-runs-aditya-2026` |
| Secrets | AWS Secrets Manager (`mosaic/openai-api-key`, `mosaic/secret-key`, `mosaic/database-url`, `mosaic/langfuse-public-key`, `mosaic/langfuse-secret-key`) |
| Container registry | ECR repos `mosaic-backend`, `mosaic-frontend` |
| Cluster | ECS `mosaic-cluster` |

Both services run behind Application Load Balancers spanning all three `eu-west-2` AZs. The backend health check path is `/health`; the frontend health check path is `/`.

### Re-deploying after a code change

**Backend:**
```bash
docker buildx build --platform linux/amd64 -f Dockerfile.backend -t mosaic-backend .
aws ecr get-login-password --region eu-west-2 | docker login --username AWS --password-stdin 211125777624.dkr.ecr.eu-west-2.amazonaws.com
docker tag mosaic-backend:latest 211125777624.dkr.ecr.eu-west-2.amazonaws.com/mosaic-backend:latest
docker push 211125777624.dkr.ecr.eu-west-2.amazonaws.com/mosaic-backend:latest
# Then: ECS → mosaic-backend-service → Update service → Force new deployment
```

**Frontend** (`VITE_API_BASE` is baked in at build time — must be set correctly):
```bash
docker buildx build --platform linux/amd64 \
  -f Dockerfile.frontend \
  --build-arg VITE_API_BASE=http://mosaic-alb-1430485178.eu-west-2.elb.amazonaws.com \
  -t mosaic-frontend .
docker tag mosaic-frontend:latest 211125777624.dkr.ecr.eu-west-2.amazonaws.com/mosaic-frontend:latest
docker push 211125777624.dkr.ecr.eu-west-2.amazonaws.com/mosaic-frontend:latest
# Then: ECS → mosaic-frontend-service → Update service → Force new deployment
```

`--platform linux/amd64` is required — Fargate task definitions are set to `Linux/X86_64`, and building on Apple Silicon without this flag produces ARM64 images that fail with `exec format error`.

### One-off operational tasks (run via ECS "Run task" with command override)

These tasks reuse `mosaic-backend-task` (latest revision) with the same VPC/subnets/security group as the backend service, public IP ON. They connect to RDS through the VPC and pick up all secrets the same way the service does.

**Seed user accounts** (run once per database, or to rotate a password):
```
python,-m,scripts.seed_users
```
Reads from `scripts/seed_users.local.json` (gitignored) — this file must exist inside the image at run time. The three real accounts are `aditya16902@gmail.com`, `shambavi.vaidiyanathan@mosaicinsurance.com`, and `usha.badrinath@mosaicinsurance.com`.

**Seed raw metrics into RDS** (run once, or after a data refresh):
```
python,-m,scripts.seed_raw_metrics
```
Reads the four source CSVs from `/data/` inside the image, merges them, and upserts all rows into the `raw_metrics` table. Safe to re-run — uses `ON CONFLICT DO UPDATE`.

### Security groups

| Group | Purpose |
|---|---|
| `mosaic-alb-sg` | Backend ALB — inbound HTTP:80 from anywhere |
| `mosaic-frontend-alb-sg` | Frontend ALB — inbound HTTP:80 from anywhere |
| `mosaic-fargate-sg` | Fargate tasks — inbound TCP:8000 from `mosaic-alb-sg`, inbound TCP:80 from `mosaic-frontend-alb-sg` |
| `mosaic-rds-sg` | RDS — inbound TCP:5432 from `mosaic-fargate-sg` (SG reference) and from your dev IP (CIDR) |

### IAM roles

- **`mosaic-task-execution-role`** — attached to all task definitions. Manages ECR image pulls and Secrets Manager secret injection at container start. Policies: `AmazonECSTaskExecutionRolePolicy` (managed) + `mosaic-ssm-access` (SSM GetParameters) + `mosaic-secrets-access` (Secrets Manager GetSecretValue, scoped to the five secret ARNs).
- **`mosaic-task-role`** — the role the running container assumes. Policies: S3 read/write on `mosaic-runs-aditya-2026`, `mosaic-ssm-access`.

---

## Setup (local, no Docker)

```bash
cd /path/to/Mosaic
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Add keys to `.env` (see `.env.example`):

```
OPENAI_API_KEY=sk-...
SECRET_KEY=...                    # JWT signing key — set a real value outside localhost
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
# DATABASE_URL=...                # unset = SQLite; set to a postgres:// URL for Postgres
LANGFUSE_PUBLIC_KEY=pk-lf-...     # optional — enables tracing
LANGFUSE_SECRET_KEY=sk-lf-...     # optional
```

Initialise the database (creates all tables, seeds default schedule — does NOT create any user):

```bash
python -m backend.db.database
```

Seed raw metrics data into the database:

```bash
python -m scripts.seed_raw_metrics
```

Create user accounts (no hardcoded credentials anywhere — see Auth & Users):

```bash
cp scripts/seed_users.example.json scripts/seed_users.local.json
# edit seed_users.local.json with real username/password/display_name entries
python -m scripts.seed_users
```

Frontend:

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

Backend:

```bash
uvicorn main:app --reload --port 8000
```

---

## Setup (Docker, local)

`docker-compose.yml` runs the full stack — backend, frontend (nginx), and a local Postgres container. For local verification only; production uses Fargate + RDS.

```bash
docker compose up --build
```

Frontend: `http://localhost:5174`. Backend: `http://localhost:8000`. Seed the Postgres container after it starts:

```bash
export DATABASE_URL="postgresql+psycopg2://postgres:devpass@localhost:5432/mosaic"
python -m scripts.seed_raw_metrics
python -m scripts.seed_users
```

---

## Dependency management

`requirements.txt` is the hand-curated source of truth — pinned top-level packages only, not a `pip freeze` dump. **uv is not currently used** — it was discussed as a faster, lockfile-based alternative but deferred as the existing pinned `requirements.txt` was sufficient. Worth revisiting if dependency resolution becomes slow or flaky.

---

## Architecture — layer by layer

Each weekly run flows through five backend layers, then a packaging layer, then is exposed via the API to the frontend.

**Layer 1 — Ingestion (`backend/pipeline/ingestor.py`).** Reads raw metrics directly from the `raw_metrics` table in Postgres (or SQLite locally), which holds the merged view of the four original CSVs (submissions, premium, pipeline, loss indicators) keyed on `(week_ending, lob)`. Computes derived metrics: hit rate, GWP-vs-plan ratio (weekly and YTD), combined ratio (loss ratio + per-LoB assumed expense ratio from `LOB_PROFILES`), loss ratio velocity (week-over-week change), decline rate, NTU rate. An optional `week_start`/`week_end` filter is applied here for custom-range reports. The source CSVs in `/data/` are the seeding source of truth (read once by `scripts/seed_raw_metrics.py`); the pipeline itself reads only from the database at runtime.

**Layer 2 — Signal detection (`backend/pipeline/signals.py`).** Four independent detectors run per LoB against thresholds in `SIGNAL_CONFIG`:
- **S1 — Structural underperformance.** GWP-vs-plan ratio below 0.75 in ≥80% of weeks.
- **S2 — Hit rate collapse.** Baseline vs recent window comparison (recent = `max(3, round(total_weeks × 0.25))` weeks). Fires if drop ≥15pp or ≥50% relative, and ≥75% of recent window sits below the baseline's 25th percentile.
- **S3 — Loss ratio deterioration.** Rising for ≥4 consecutive weeks AND latest value exceeds the LoB's target.
- **S4 — Profitable outperformance.** GWP-vs-plan above 1.10 in ≥75% of weeks AND combined ratio below 100%.

**Layer 3a — Root cause enrichment (`backend/pipeline/enrichment.py`).** Every finding gets a `root_cause_detail` string that explicitly names the dates and window sizes behind its numbers — S1 discloses its fixed 4-week recent window with exact dates; S2 discloses both windows with exact dates and percentile-breach detail; S3 discloses the full trend period and underwriting-loss calculation; S4 adds GWP/loss-ratio correlation and the paired weekly series used by its chart.

**Layer 3b — Anomaly detection (`backend/pipeline/anomalies.py`).** Independent of the four signals: claims spikes (z-score > 2.5), stalled pipeline (avg days ≥ 45), funnel divergence (submissions spike ≥40% WoW without a matching quote movement), and missing data flags.

**Layer 4 — Prioritisation (`backend/pipeline/prioritiser.py`).** Assigns each finding an `impact_score` in £, ranks them, and assembles the full payload: portfolio summary, per-LoB snapshot, `weekly_series` (every LoB × every week — powers dashboard charts), ranked concerns/opportunities, anomalies, signal counts.

**Layer 5 — Two-LLM chain (`backend/llm/chain.py`).** LLM1 (`gpt-4o-mini`, low temperature) returns structured JSON: top 3 concerns ranked, top opportunity, one-line rationales, analyst notes. LLM2 (`gpt-4o`) writes the full CUO narrative as standalone HTML — instructed to disclose methodology and show calculation derivations. Both calls traced to Langfuse when configured.

**Packaging (`backend/report/snapshot.py`).** Every run writes a full audit bundle to `runs/{run_id}/` and uploads the entire directory to S3 (`runs/{run_id}/` prefix in `mosaic-runs-aditya-2026`). Bundle includes: raw CSVs, `merged_metrics.xlsx`, `merged_metrics.db` (SQLite, used by the chat agent), LLM1 input/output JSON, both prompt files, `signals_and_enrichment.md`, narrative HTML, `dashboard_data.json`, and a zip of everything.

**Run IDs** use the format `YYYYMMDD_HHMMSS_week<report_week>_<4hexsuffix>`.

---

## Database

Runs against either SQLite (local, unset `DATABASE_URL`) or Postgres (Docker Compose, AWS RDS) via SQLAlchemy Core — no ORM, no migration framework. Controlled by a single `DATABASE_URL` env var.

Four tables:

- **`users`** — real named accounts, bcrypt-hashed passwords.
- **`reports`** — one row per run: run_id, week range, status, source (`manual`/`automated`), JSON blobs of signals/concerns/opportunities/anomalies for fast history listing without touching S3.
- **`schedule_config`** — single-row table holding the automated report cadence (day, hour, minute in UTC). Persists across container restarts since it lives in RDS.
- **`raw_metrics`** — all source data rows, composite primary key `(week_ending, lob)`, 17 columns covering all four original CSV feeds merged. Seeded once via `scripts/seed_raw_metrics.py`; the pipeline reads from here at runtime rather than from flat files.

On AWS, RDS is **not publicly accessible** (private VPC only). Access from outside the VPC (e.g. running seed scripts from a laptop) is not possible regardless of security group rules — use ECS "Run task" with a command override to run one-off scripts from inside the VPC instead.

---

## Auth & users

No hardcoded username or password anywhere in the codebase. Passwords are bcrypt-hashed via `passlib`. Login verifies against a dummy hash even when the username doesn't exist (timing-safe). Accounts are created via `scripts/seed_users.py`, which reads from a gitignored local JSON file and upserts bcrypt hashes into the `users` table.

On AWS, the three real accounts (`aditya16902@gmail.com`, `shambavi.vaidiyanathan@mosaicinsurance.com`, `usha.badrinath@mosaicinsurance.com`) were seeded via a one-off ECS task using the command override pattern described in the AWS deployment section above.

---

## API

All routes except `/auth/login` and `/health` require a bearer JWT. Two routes (`narrative`, `snapshot/zip`) also accept `?token=` via `verify_token_flexible` for browser-initiated downloads that can't attach an Authorization header.

```
POST   /auth/login
GET    /auth/me
GET    /data/bounds                              min/max week_ending from raw_metrics
POST   /reports/generate                         {week_start?, week_end?} → full pipeline
GET    /reports                                  history list
GET    /reports/{run_id}
DELETE /reports/{run_id}                         deletes DB row + S3 run directory — irreversible
GET    /reports/{run_id}/dashboard
GET    /reports/{run_id}/narrative
GET    /reports/{run_id}/snapshot/files
GET    /reports/{run_id}/snapshot/download/{name}
GET    /reports/{run_id}/snapshot/zip
GET    /schedule / PUT /schedule
POST   /chat                                     {question, run_id?} → text-to-SQL agent
GET    /health
```

---

## Text-to-SQL chat agent

`backend/agents/text_to_sql/agent.py` generates SQL from a natural-language question, executes it against that run's `merged_metrics.db` (downloaded from S3 to the container's local disk on first access if not already present — `_ensure_run_files_local()`), and interprets the result into a business-language answer. `sql_executor.py` permits only `SELECT` on `merged_metrics`, blocks DDL/DML, caps at 500 rows. Up to 2 SQL retries with error context. Prompts versioned (`sql_gen_v1`/`v2`, `sql_interpret_v1`/`v2`). The agent's SQLite database is a per-run artifact, entirely separate from the application's Postgres database.

---

## Schedule settings

The schedule UI (`/settings`) accepts times in the user's detected local timezone (auto-detected via `Intl.DateTimeFormat().resolvedOptions().timeZone`) and displays the UTC equivalent inline. Saves convert local time to UTC before sending to the backend. The backend always stores and fires in UTC.

The in-process APScheduler reads the `schedule_config` table on every container boot, so changes made via the UI persist across container replacements (the schedule is stored in RDS, not in process memory). The scheduler re-registers the cron job immediately when `PUT /schedule` is called, so the new time takes effect without a restart.

**Known limitation:** the in-process scheduler only fires while that specific container instance is running. On AWS, this means the job could silently miss if the task is replaced at the exact scheduled moment. The production-correct replacement is an AWS EventBridge rule invoking a Lambda or Fargate task directly — this is a clean swap-out when needed, not a refactor.

---

## S3 run artifact storage

When `S3_RUNS_BUCKET` is set (always true on AWS), `backend/report/snapshot.py` uploads the full run directory to S3 after packaging. All API routes that serve run artifacts (`/dashboard`, `/narrative`, `/snapshot/*`) branch on `s3_enabled()` — if true, they fetch from S3 (presigned URLs for downloads, direct content fetch for dashboard JSON and narrative HTML) rather than the local filesystem. Dashboard data and the chat agent's SQLite database are downloaded to the container's local disk on first access and reused for the lifetime of that container instance.

Deleting a report via the API removes the DB row, any local run directory, and the S3 prefix.

---

## Eval & regression framework

Two parallel eval frameworks under `evals/`.

**Pipeline eval** (`evals/runners/eval_runner.py`): synthetic fixtures through the full pipeline and both LLM stages, scoring signal recall deterministically and using LLM judges for ranking correctness, rationale faithfulness, and narrative quality. `--no-llm` runs deterministic checks only (no API cost).

**Agent eval** (`evals/runners/agent_eval_runner.py`): golden questions through the chat agent, scored deterministically for SQL correctness (`sql_comparator.py` — loose value-set comparison plus schema-adherence regex) and via LLM judge for answer quality.

Both frameworks were validated by intentionally degrading prompts (`*_v2.txt`) and confirming the machinery detects the regression.

---

## Observability (Langfuse)

Free tier at `cloud.langfuse.com`. Pipeline runs produce a trace (`weekly_performance_analyst`) with child spans for LLM1 and LLM2. Chat agent traces share the same session ID convention, linking both workflows per report in the Langfuse UI. Two separate Langfuse client instances by design (one for the `@observe` decorator pattern in `chain.py`, one lazily-initialised in `observability.py`) — kept apart after diagnosing a trace-flush-timing bug where early flushing silently dropped traces.

---

## Frontend

React + Vite + TypeScript + Tailwind. Paper-and-ledger visual design: warm off-white background, signature colored severity rail on concern cards and history rows, Source Serif for display type, Inter for body, JetBrains Mono for numeric values.

Key structure: `pages/LoginPage.tsx`, `pages/SettingsPage.tsx` (timezone-aware schedule UI), `lib/auth.ts`, `lib/api.ts`, `lib/types.ts`, `lib/reportEvents.ts` (pub/sub for immediate sidebar refresh after generate/delete), `components/dashboard/*` (portfolio header, concern cards, LoB table, GWP trend chart, hit-rate heatmap, anomalies), `components/layout/Sidebar.tsx`, `components/layout/ResizableChatPanel.tsx`, `components/chat/ChatPanelContent.tsx`.

**Note:** `crypto.randomUUID()` is only available in secure contexts (HTTPS or localhost). `ChatPanelContent.tsx` uses a `localId()` fallback that works on plain HTTP (current deployment) as well as HTTPS, since these IDs are only used as React list keys and are never security-sensitive.

---

## Known limitations

- **Plain HTTP, no TLS.** Both ALBs serve HTTP only. Adding HTTPS requires an ACM certificate + HTTPS listener — this is the correct fix for the secure-context restriction on `crypto.randomUUID()` and would also remove the "Not Secure" browser warning. Straightforward to add when a domain name is available.
- **In-process scheduler.** APScheduler runs inside the Fargate task. The schedule persists in RDS across container restarts, but the job could miss if the container is replaced at the exact moment of firing. EventBridge is the production-correct replacement.
- **Report deletion is irreversible.** `DELETE /reports/{run_id}` removes the DB row, local run directory, and S3 prefix. No soft-delete or trash state.
- **Chat agent SQLite download per container.** `merged_metrics.db` is downloaded from S3 to the container's local disk on first access per run per container instance. Subsequent questions reuse the cached file. If the container is replaced, the file is re-downloaded on the next question.

---

## Pre-deployment hygiene

`.gitignore` excludes `.env`, `venv/`, `frontend/node_modules/`, `frontend/dist/`, `mosaic.db`, `runs/`, `evals/results/`, and `scripts/seed_users.local.json`. `.dockerignore` excludes the same. CORS origins, JWT key, and database URL are all environment-driven. A startup warning prints if `SECRET_KEY` is left at its default dev value.

---

## Testing after a change

```bash
# Backend imports cleanly
python -c "from backend.api.routes import app"

# Pipeline dry run (no LLM cost)
python test_runner.py dry --to 2024-09-15

# Full pipeline + LLM chain
python test_runner.py llm

# Pipeline eval, no LLM cost
python evals/runners/eval_runner.py --no-llm

# Full pipeline eval with judges
python evals/runners/eval_runner.py

# Agent eval, no LLM cost
python evals/runners/agent_eval_runner.py --no-llm

# Full agent eval with judges
python evals/runners/agent_eval_runner.py

# Regression checks
python evals/runners/regression.py evals/results/eval_v1_<timestamp>.json
python evals/runners/agent_regression.py evals/results/agent_eval_v1_<timestamp>.json

# Frontend build (catches TypeScript errors the dev server tolerates)
cd frontend && npm run build

# Frontend dev server
cd frontend && npm run dev

# Backend dev server
uvicorn main:app --reload --port 8000

# Full containerized stack
docker compose up --build
```

Manual checks after any change: log in with a real seeded account; generate a report, confirm it appears in history; delete a report, confirm redirect; ask the chat agent a question grounded in the report and one out of scope; open the narrative and download the snapshot zip (these use `?token=` auth); change and save schedule settings, confirm persistence after hard refresh; sign out.
