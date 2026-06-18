"""
scripts/seed_raw_metrics.py
────────────────────────────
Loads the four source CSVs, merges them on (week_ending, lob), and
upserts every row into the raw_metrics table.

Safe to run multiple times — uses ON CONFLICT DO UPDATE so re-running
after a data refresh will overwrite stale rows rather than error.

Usage (run from repo root):
    export DATABASE_URL="postgresql+psycopg2://..."
    python -m scripts.seed_raw_metrics
"""

import sys
from pathlib import Path

# Allow running as `python -m scripts.seed_raw_metrics` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text
from backend.db.database import get_connection, init_db, get_engine
from backend.config import DATA_DIR

FILES = {
    "premium":     "case4_weekly_premium.csv",
    "submissions": "case4_weekly_submissions.csv",
    "pipeline":    "case4_pipeline.csv",
    "loss":        "case4_loss_indicators.csv",
}
MERGE_KEYS = ["week_ending", "lob"]


def load_and_merge() -> pd.DataFrame:
    dfs = {}
    for key, fname in FILES.items():
        dfs[key] = pd.read_csv(DATA_DIR / fname, parse_dates=["week_ending"])

    df = dfs["premium"].copy()
    for key in ("submissions", "pipeline", "loss"):
        df = df.merge(dfs[key], on=MERGE_KEYS, how="outer")

    df["week_ending"] = pd.to_datetime(df["week_ending"]).dt.date
    return df.sort_values(MERGE_KEYS).reset_index(drop=True)


def seed():
    print("[Seed] Initialising DB...")
    init_db()

    df = load_and_merge()
    print(f"[Seed] Loaded {len(df)} rows across {df['lob'].nunique()} lines of business.")

    conn = get_connection()
    upserted = 0
    for _, row in df.iterrows():
        conn.execute(
            text("""
                INSERT INTO raw_metrics (
                    week_ending, lob,
                    actual_gwp, plan_gwp, ytd_actual, ytd_plan,
                    submissions_count, quoted_count, bound_count,
                    declined_count, ntu_count,
                    open_quotes_count, open_quotes_gwp_est, avg_days_in_pipeline,
                    new_claims_count, new_claims_incurred_est,
                    attritional_loss_ratio_ytd
                ) VALUES (
                    :week_ending, :lob,
                    :actual_gwp, :plan_gwp, :ytd_actual, :ytd_plan,
                    :submissions_count, :quoted_count, :bound_count,
                    :declined_count, :ntu_count,
                    :open_quotes_count, :open_quotes_gwp_est, :avg_days_in_pipeline,
                    :new_claims_count, :new_claims_incurred_est,
                    :attritional_loss_ratio_ytd
                )
                ON CONFLICT (week_ending, lob) DO UPDATE SET
                    actual_gwp                 = excluded.actual_gwp,
                    plan_gwp                   = excluded.plan_gwp,
                    ytd_actual                 = excluded.ytd_actual,
                    ytd_plan                   = excluded.ytd_plan,
                    submissions_count          = excluded.submissions_count,
                    quoted_count               = excluded.quoted_count,
                    bound_count                = excluded.bound_count,
                    declined_count             = excluded.declined_count,
                    ntu_count                  = excluded.ntu_count,
                    open_quotes_count          = excluded.open_quotes_count,
                    open_quotes_gwp_est        = excluded.open_quotes_gwp_est,
                    avg_days_in_pipeline       = excluded.avg_days_in_pipeline,
                    new_claims_count           = excluded.new_claims_count,
                    new_claims_incurred_est    = excluded.new_claims_incurred_est,
                    attritional_loss_ratio_ytd = excluded.attritional_loss_ratio_ytd
            """),
            {
                "week_ending":                 str(row["week_ending"]),
                "lob":                         row["lob"],
                "actual_gwp":                  _nullable(row, "actual_gwp"),
                "plan_gwp":                    _nullable(row, "plan_gwp"),
                "ytd_actual":                  _nullable(row, "ytd_actual"),
                "ytd_plan":                    _nullable(row, "ytd_plan"),
                "submissions_count":           _nullable(row, "submissions_count"),
                "quoted_count":                _nullable(row, "quoted_count"),
                "bound_count":                 _nullable(row, "bound_count"),
                "declined_count":              _nullable(row, "declined_count"),
                "ntu_count":                   _nullable(row, "ntu_count"),
                "open_quotes_count":           _nullable(row, "open_quotes_count"),
                "open_quotes_gwp_est":         _nullable(row, "open_quotes_gwp_est"),
                "avg_days_in_pipeline":        _nullable(row, "avg_days_in_pipeline"),
                "new_claims_count":            _nullable(row, "new_claims_count"),
                "new_claims_incurred_est":     _nullable(row, "new_claims_incurred_est"),
                "attritional_loss_ratio_ytd":  _nullable(row, "attritional_loss_ratio_ytd"),
            },
        )
        upserted += 1

    conn.commit()
    conn.close()
    print(f"[Seed] Done — {upserted} row(s) upserted into raw_metrics.")


def _nullable(row, col):
    """Return None for NaN values so Postgres/SQLite store NULL rather than NaN."""
    import math
    val = row.get(col)
    if val is None:
        return None
    try:
        if math.isnan(float(val)):
            return None
    except (TypeError, ValueError):
        pass
    return val


if __name__ == "__main__":
    seed()
