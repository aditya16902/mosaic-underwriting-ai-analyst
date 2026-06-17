"""
Layer 1 — Data Ingestor & Metric Calculator
"""

import pandas as pd
import numpy as np
from pathlib import Path
from backend.config import DATA_DIR, LOB_PROFILES

FILES = {
    "submissions": "case4_weekly_submissions.csv",
    "premium":     "case4_weekly_premium.csv",
    "pipeline":    "case4_pipeline.csv",
    "loss":        "case4_loss_indicators.csv",
}

MERGE_KEYS = ["week_ending", "lob"]


def load_raw(data_dir: Path = DATA_DIR) -> dict:
    raw = {}
    for key, fname in FILES.items():
        df = pd.read_csv(data_dir / fname, parse_dates=["week_ending"])
        df["week_ending"] = pd.to_datetime(df["week_ending"])
        raw[key] = df
    return raw


def merge_tables(raw: dict) -> pd.DataFrame:
    df = raw["premium"].copy()
    for key in ("submissions", "pipeline", "loss"):
        df = df.merge(raw[key], on=MERGE_KEYS, how="outer")
    return df.sort_values(MERGE_KEYS).reset_index(drop=True)


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


def ingest(data_dir: Path = DATA_DIR, week_start=None, week_end=None) -> tuple:
    raw    = load_raw(data_dir)
    merged = merge_tables(raw)
    merged = compute_metrics(merged)

    if week_start:
        merged = merged[merged["week_ending"] >= pd.to_datetime(week_start)]
    if week_end:
        merged = merged[merged["week_ending"] <= pd.to_datetime(week_end)]

    merged["week_num"] = merged.groupby("lob")["week_ending"].rank(method="dense").astype(int)
    return raw, merged
