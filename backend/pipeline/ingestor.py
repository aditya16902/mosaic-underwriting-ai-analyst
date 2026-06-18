"""
Layer 1 — Data Ingestor & Metric Calculator

Raw data is sourced from the raw_metrics table in RDS/SQLite rather than
flat CSV files. The CSV files remain in /data as the canonical source of
truth for seeding (scripts/seed_raw_metrics.py reads them once to populate
the DB), but the pipeline no longer reads them directly at runtime.
"""

import pandas as pd
import numpy as np
from backend.config import LOB_PROFILES
from backend.db.database import get_engine

MERGE_KEYS = ["week_ending", "lob"]


def load_raw() -> pd.DataFrame:
    """
    Read all rows from raw_metrics and return as a single merged DataFrame,
    equivalent to the four-CSV merge the old load_raw()+merge_tables() did.
    week_ending is parsed to datetime for consistency with downstream code.
    """
    engine = get_engine()
    df = pd.read_sql("SELECT * FROM raw_metrics ORDER BY week_ending, lob", engine)
    df["week_ending"] = pd.to_datetime(df["week_ending"])
    return df


def _get_lob_profile(lob: str) -> dict:
    return LOB_PROFILES.get(lob, LOB_PROFILES["Default"])


def compute_metrics(df: pd.DataFrame) -> pd.DataFrame:
    denom = (
        df["bound_count"].fillna(0)
        + df["quoted_count"].fillna(0)
        + df["declined_count"].fillna(0)
        + df["ntu_count"].fillna(0)
    )
    df["hit_rate"] = np.where(denom > 0, df["bound_count"].fillna(0) / denom, np.nan)

    df["gwp_vs_plan_ratio"]     = np.where(df["plan_gwp"] > 0,  df["actual_gwp"] / df["plan_gwp"],  np.nan)
    df["ytd_gwp_vs_plan_ratio"] = np.where(df["ytd_plan"] > 0,  df["ytd_actual"] / df["ytd_plan"],  np.nan)

    df["assumed_expense_ratio"] = df["lob"].apply(lambda l: _get_lob_profile(l)["assumed_expense_ratio"])
    df["loss_ratio_target"]     = df["lob"].apply(lambda l: _get_lob_profile(l)["loss_ratio_target"])
    df["combined_ratio_ytd"]    = df["attritional_loss_ratio_ytd"] + df["assumed_expense_ratio"]

    df = df.sort_values(MERGE_KEYS)
    df["loss_ratio_velocity"] = df.groupby("lob")["attritional_loss_ratio_ytd"].diff()

    df["decline_rate"] = np.where(df["submissions_count"] > 0, df["declined_count"].fillna(0) / df["submissions_count"], np.nan)
    df["ntu_rate"]     = np.where(df["submissions_count"] > 0, df["ntu_count"].fillna(0)     / df["submissions_count"], np.nan)

    df["week_num"] = df.groupby("lob")["week_ending"].rank(method="dense").astype(int)
    return df


def ingest(week_start=None, week_end=None) -> tuple:
    """
    Load raw metrics from DB, compute derived metrics, apply optional
    date filters, and return (raw_df, merged_df).

    The returned 'raw' value is the same DataFrame as 'merged' before
    metric computation — kept for API compatibility with callers that
    unpack the two-tuple but only use the second element.
    """
    df = load_raw()
    df = compute_metrics(df)

    if week_start:
        df = df[df["week_ending"] >= pd.to_datetime(week_start)]
    if week_end:
        df = df[df["week_ending"] <= pd.to_datetime(week_end)]

    df["week_num"] = df.groupby("lob")["week_ending"].rank(method="dense").astype(int)

    # Return (raw, merged) to preserve the two-tuple contract orchestrator.py expects.
    # Both point to the same DataFrame since the DB already stores the merged view.
    return df, df
