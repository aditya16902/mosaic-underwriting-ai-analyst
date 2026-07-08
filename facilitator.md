Exactly the expected error — this confirms the local SQLite database (`mosaic.db`, since no `DATABASE_URL` is set) has never had `raw_metrics` created or seeded. The pipeline change earlier in this session moved reads to that table, but your local environment was never updated to match — only RDS was.

Fix: initialize and seed the local SQLite DB the same way RDS was seeded.

```bash
python -m backend.db.database
python -m scripts.seed_raw_metrics
```

The first command runs `init_db()`, which creates all four tables (including `raw_metrics`) in your local `mosaic.db` file. The second reads the CSVs from `/data/` and upserts all 96 rows — same script, same logic that seeded RDS, just targeting SQLite this time since no `DATABASE_URL` is exported in this shell.

After that, retry:

```bash
python test_runner.py dry --to 2024-09-15
```

This should now run cleanly against local SQLite, fully isolated from AWS — exactly the local dev loop described as option #10 in the earlier list, just using SQLite directly rather than the Docker Compose Postgres container (also fine — SQLite is the actual default when `DATABASE_URL` is unset, per `config.py`).

If you also want users seeded locally for testing login/report-generation through the API itself:

```bash
cp scripts/seed_users.example.json scripts/seed_users.local.json
# edit with test credentials
python -m scripts.seed_users
```

Good question — since the deployed system reads from RDS and S3 now (not local CSVs/files), local testing needs to either point at the same AWS resources or stand up local equivalents. Here's the full list of what's actually testable and how.

## 1. Unit/import sanity checks
```bash
python -c "from backend.api.routes import app"
```
Confirms the app imports cleanly — catches broken imports immediately after any code change, no DB or LLM needed.

## 2. Pipeline dry run (no LLM cost)
```bash
python test_runner.py dry --to 2024-09-15
```
Runs Layers 1–4 only (ingestion through prioritisation), skips the LLM chain entirely. Needs a `DATABASE_URL` pointing somewhere with `raw_metrics` populated — either local SQLite (if seeded) or AWS RDS directly, if your IP is allowlisted on `mosaic-rds-sg` (it likely isn't anymore, per earlier in this session — RDS isn't reachable from outside the VPC regardless).

## 3. Full pipeline + LLM chain
```bash
python test_runner.py llm
```
Runs everything including LLM1/LLM2 — real OpenAI cost, real narrative output written locally.

## 4. Pipeline eval framework (deterministic + LLM-judged)
```bash
python evals/runners/eval_runner.py --no-llm    # deterministic only, zero cost
python evals/runners/eval_runner.py             # full, with LLM judges
```
Runs the five fixtures (`adversarial_blip`, `easy_single_signal`, `edge_borderline`, `hard_all_signals`, `medium_two_signals`) and scores Pipeline Signal Recall, LLM1/LLM2 metrics.

## 5. Agent eval framework
```bash
python evals/runners/agent_eval_runner.py --no-llm
python evals/runners/agent_eval_runner.py
```
Runs the golden chat-agent questions, scores SQL correctness and answer quality.

## 6. Regression testing — comparing two eval runs
```bash
python evals/runners/regression.py evals/results/eval_v1_<old_timestamp>.json evals/results/eval_v1_<new_timestamp>.json
python evals/runners/agent_regression.py evals/results/agent_eval_v1_<old>.json evals/results/agent_eval_v1_<new>.json
```
Run an eval before a change, run it again after, diff the two result files. This is how you catch a prompt edit or code change quietly making things worse.

## 7. Deliberate degraded-prompt regression test
```bash
# Temporarily point prompts at the *_v2.txt (intentionally worse) variants, then:
python evals/runners/eval_runner.py
python evals/runners/regression.py evals/results/<v1_baseline>.json evals/results/<v2_run>.json
```
Confirms the regression detection itself actually works — scores should drop in the expected categories.

## 8. Frontend build check
```bash
cd frontend && npm run build
```
Catches TypeScript errors the dev server silently tolerates — run this before every deploy, since it's the cheapest possible check against shipping a broken build.

## 9. Local full-stack run against AWS RDS/S3 (closest to "test like production")
```bash
export DATABASE_URL="<RDS connection string>"   # won't work unless allowlisted — see below
export S3_RUNS_BUCKET="mosaic-runs-aditya-2026"
uvicorn main:app --reload --port 8000
```
**Limitation, already established this session:** RDS has "Publicly accessible" set to No — this will time out from your laptop regardless of IP rules. This path only works from inside the VPC.

## 10. Local full-stack run via Docker Compose (local Postgres, not AWS)
```bash
docker compose up --build
export DATABASE_URL="postgresql+psycopg2://postgres:devpass@localhost:5432/mosaic"
python -m scripts.seed_raw_metrics
python -m scripts.seed_users
```
This is the realistic local option — same SQL engine (Postgres, not SQLite), fully isolated from production data, lets you test schema changes and pipeline logic safely before ever touching AWS.

## 11. Manual smoke test checklist (after any deploy)
- Log in with a seeded account
- Generate a report, confirm it appears in history
- Open the narrative, download the snapshot zip
- Ask the chat agent a grounded question and one out-of-scope question
- Change schedule settings, hard-refresh, confirm persistence
- Sign out

## 12. One-off ECS "Run task" for testing against real production data safely
For anything that genuinely needs to touch the real RDS/S3 (rather than a local Postgres copy), run it as a one-off ECS task with a command override — same pattern used for seeding earlier. This is the only way to safely run a real script against production data without exposing RDS publicly.

---

**Practical recommendation:** for day-to-day development, use #10 (Docker Compose + local Postgres) as your main loop — it's fast, free, and isolated. Use #4/#5 (the eval frameworks) before any prompt or pipeline change to catch regressions. Reserve #12 (ECS one-off tasks) only for genuinely production-data-dependent checks, and always run #8 before every deploy regardless of what else you've tested.