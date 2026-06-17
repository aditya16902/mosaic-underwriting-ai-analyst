"""
MosAIc Pipeline Configuration
Central config: LoB profiles, signal thresholds, model settings, paths.
"""

import os
from pathlib import Path

# ─── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
RUNS_DIR = BASE_DIR / "runs"
DB_PATH  = BASE_DIR / "mosaic.db"

# ─── Database ─────────────────────────────────────────────────────────────────
# Local dev: no DATABASE_URL needed, defaults to the SQLite file at DB_PATH.
# AWS: set DATABASE_URL to a Postgres connection string, e.g.
#   postgresql+psycopg2://mosaic_app:<password>@<rds-endpoint>:5432/mosaic
# backend/db/database.py uses this via SQLAlchemy, so the same SQL runs
# against either backend — only this URL changes between environments.
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DB_PATH}")

# ─── LoB Profiles ─────────────────────────────────────────────────────────────
# assumed_expense_ratio: fixed cost per £ of premium for each LoB
# loss_ratio_target    : upper bound before flagging deterioration
LOB_PROFILES = {
    "Cyber": {
        "assumed_expense_ratio": 0.28,
        "loss_ratio_target": 0.60,
    },
    "Transactional Liability": {
        "assumed_expense_ratio": 0.42,
        "loss_ratio_target": 0.50,
    },
    "Environmental": {
        "assumed_expense_ratio": 0.35,
        "loss_ratio_target": 0.55,
    },
    "Political Violence": {
        "assumed_expense_ratio": 0.32,
        "loss_ratio_target": 0.55,
    },
    "Political Risk": {
        "assumed_expense_ratio": 0.35,
        "loss_ratio_target": 0.55,
    },
    "Financial Institutions": {
        "assumed_expense_ratio": 0.33,
        "loss_ratio_target": 0.55,
    },
    "Professional Lines": {
        "assumed_expense_ratio": 0.34,
        "loss_ratio_target": 0.55,
    },
    "Excess Casualty": {
        "assumed_expense_ratio": 0.30,
        "loss_ratio_target": 0.60,
    },
    "Default": {
        "assumed_expense_ratio": 0.35,
        "loss_ratio_target": 0.60,
    },
}

# ─── Signal Detection Thresholds ──────────────────────────────────────────────
SIGNAL_CONFIG = {
    # Signal 1: Structural Underperformance
    # Flag if gwp_vs_plan < this threshold in >= pct_weeks_threshold of all weeks
    "s1_gwp_ratio_threshold": 0.75,
    "s1_pct_weeks_threshold": 0.80,          # 80% of weeks must be below ratio

    # Signal 2: Hit Rate Collapse
    # Assessment window = max(3, round(total_weeks * 0.25))
    # Flag if drop from baseline > abs_drop_pp OR relative_drop_pct
    # AND pct_of_window_below_q25 of window weeks are below historical Q25
    "s2_abs_drop_pp": 0.15,                  # 15 percentage points
    "s2_relative_drop_pct": 0.50,            # 50% relative decline
    "s2_pct_of_window_below_q25": 0.75,      # 75% of window weeks below Q25

    # Signal 3: Deteriorating Loss Ratio Trend
    # Flag if slope positive for >= consecutive_weeks AND final value > LoB target
    "s3_consecutive_weeks": 4,

    # Signal 4: Profitable Outperformance
    # Flag if gwp_vs_plan > ratio_threshold in >= pct_weeks_threshold of all weeks
    # AND final combined_ratio < combined_ratio_cap (underwriting profit)
    "s4_gwp_ratio_threshold": 1.10,
    "s4_pct_weeks_threshold": 0.75,
    "s4_combined_ratio_cap": 1.00,
}

# ─── Anomaly Detection ────────────────────────────────────────────────────────
ANOMALY_CONFIG = {
    "claims_zscore_threshold": 2.5,          # Z-score to flag spike in claims
    "pipeline_days_threshold": 45,           # Days in pipeline = stalled
    "funnel_submission_spike_pct": 0.40,     # 40% WoW spike in submissions
    "funnel_quote_drop_pct": -0.10,          # -10% WoW drop in quoted count
}

# ─── LLM Settings ─────────────────────────────────────────────────────────────
LLM_CONFIG = {
    "llm1_model": "gpt-4o-mini",            # Analytical prioritisation
    "llm2_model": "gpt-4o",                 # CUO narrative generation
    "llm1_max_tokens": 2000,
    "llm2_max_tokens": 4000,
    "temperature": 0.2,                     # Low temp = consistent, factual output
    "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
}

# ─── Auth ─────────────────────────────────────────────────────────────────────
_DEFAULT_DEV_SECRET = "mosaic-dev-secret-change-in-prod"

AUTH_CONFIG = {
    "secret_key": os.getenv("SECRET_KEY", _DEFAULT_DEV_SECRET),
    "algorithm": "HS256",
    "access_token_expire_minutes": 480,      # 8-hour session
}

if AUTH_CONFIG["secret_key"] == _DEFAULT_DEV_SECRET:
    print("[Config] WARNING: SECRET_KEY is using the default dev value. "
          "Set a real SECRET_KEY env var before deploying anywhere but localhost.")

# ─── CORS ─────────────────────────────────────────────────────────────────────
# Comma-separated list of allowed origins, e.g.
#   CORS_ORIGINS=https://app.mosaic-demo.com,https://staging.mosaic-demo.com
# Falls back to local Vite/CRA dev ports when unset.
_default_origins = "http://localhost:5173,http://localhost:3000"
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _default_origins).split(",")
    if origin.strip()
]
