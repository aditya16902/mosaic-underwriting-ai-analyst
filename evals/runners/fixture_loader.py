"""
Fixture Data Generator
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from backend.config import DATA_DIR

ALL_LOBS = [
    "Cyber", "Transactional Liability", "Environmental", "Political Risk",
    "Political Violence", "Financial Institutions", "Professional Lines", "Excess Casualty"
]

LOB_BASE_GWP_PLAN = {
    "Cyber": 180000, "Transactional Liability": 220000, "Environmental": 80000,
    "Political Risk": 95000, "Political Violence": 45000,
    "Financial Institutions": 130000, "Professional Lines": 70000, "Excess Casualty": 160000,
}


def _make_week_dates(n_weeks: int) -> list:
    return pd.date_range("2024-07-07", periods=n_weeks, freq="7D").tolist()


def _generate_healthy_lob_data(lob: str, weeks: list, gwp_ratio_range: tuple, loss_ratio_range: tuple) -> dict:
    n    = len(weeks)
    plan = LOB_BASE_GWP_PLAN.get(lob, 100000)
    rng  = np.random.default_rng(hash(lob) % 2**32)

    ratios     = rng.uniform(*gwp_ratio_range, n)
    actuals    = (plan * ratios).round(0)
    ytd_actual = np.cumsum(actuals)
    ytd_plan   = np.array([plan * (i + 1) for i in range(n)])

    loss_ratios = rng.uniform(*loss_ratio_range, n)
    loss_ytd    = np.array([loss_ratios[:i+1].mean() for i in range(n)])

    submissions = rng.integers(15, 30, n)
    bound       = rng.integers(4, 8, n)
    quoted      = bound + rng.integers(2, 5, n)
    declined    = rng.integers(2, 5, n)
    ntu         = rng.integers(1, 4, n)

    pipeline_days = rng.uniform(15, 28, n)
    open_count    = rng.integers(8, 16, n)
    open_gwp      = (open_count * plan * rng.uniform(0.8, 1.2, n)).round(0)

    claims_count    = rng.integers(0, 3, n)
    claims_incurred = (claims_count * rng.uniform(20000, 60000, n)).round(0)

    return {
        "premium":     pd.DataFrame({"week_ending": weeks, "lob": lob, "actual_gwp": actuals,
                                      "plan_gwp": plan, "ytd_actual": ytd_actual, "ytd_plan": ytd_plan}),
        "submissions": pd.DataFrame({"week_ending": weeks, "lob": lob, "submissions_count": submissions,
                                      "quoted_count": quoted, "bound_count": bound,
                                      "declined_count": declined, "ntu_count": ntu}),
        "pipeline":    pd.DataFrame({"week_ending": weeks, "lob": lob, "open_quotes_count": open_count,
                                      "open_quotes_gwp_est": open_gwp, "avg_days_in_pipeline": pipeline_days}),
        "loss":        pd.DataFrame({"week_ending": weeks, "lob": lob, "new_claims_count": claims_count,
                                      "new_claims_incurred_est": claims_incurred,
                                      "attritional_loss_ratio_ytd": loss_ytd}),
    }


def _apply_s1_override(lob_data: dict, lob: str, weeks: list, cfg: dict) -> dict:
    """Override premium data to create structural GWP underperformance (S1)."""
    n    = len(weeks)
    plan = LOB_BASE_GWP_PLAN.get(lob, 100000)
    rng  = np.random.default_rng(hash(lob + "s1") % 2**32)

    lo, hi  = cfg.get("gwp_ratio_range", [0.52, 0.68])
    ratios  = rng.uniform(lo, hi, n)
    actuals = (plan * ratios).round(0)
    ytd_actual = np.cumsum(actuals)
    ytd_plan   = np.array([plan * (i + 1) for i in range(n)])

    # High NTU rate to trigger LOSING_TO_PRICE root cause
    submissions = rng.integers(18, 26, n)
    bound       = rng.integers(3, 6, n)
    quoted      = bound + rng.integers(3, 6, n)
    declined    = rng.integers(2, 4, n)          # low decline = not too selective
    ntu         = rng.integers(6, 10, n)          # high NTU = losing to price
    pipeline_days = rng.uniform(35, 50, n)        # long pipeline = friction

    open_count = rng.integers(10, 18, n)
    open_gwp   = (open_count * plan * rng.uniform(0.9, 1.3, n)).round(0)

    lr_flat = cfg.get("loss_ratio_flat", 0.52)
    loss_ytd = np.full(n, lr_flat) + rng.uniform(-0.01, 0.01, n)

    claims_count    = rng.integers(1, 3, n)
    claims_incurred = (claims_count * rng.uniform(20000, 50000, n)).round(0)

    return {
        "premium":     pd.DataFrame({"week_ending": weeks, "lob": lob, "actual_gwp": actuals,
                                      "plan_gwp": plan, "ytd_actual": ytd_actual, "ytd_plan": ytd_plan}),
        "submissions": pd.DataFrame({"week_ending": weeks, "lob": lob, "submissions_count": submissions,
                                      "quoted_count": quoted, "bound_count": bound,
                                      "declined_count": declined, "ntu_count": ntu}),
        "pipeline":    pd.DataFrame({"week_ending": weeks, "lob": lob, "open_quotes_count": open_count,
                                      "open_quotes_gwp_est": open_gwp, "avg_days_in_pipeline": pipeline_days}),
        "loss":        pd.DataFrame({"week_ending": weeks, "lob": lob, "new_claims_count": claims_count,
                                      "new_claims_incurred_est": claims_incurred,
                                      "attritional_loss_ratio_ytd": loss_ytd}),
    }


def _apply_s3_override(lob_data: dict, lob: str, weeks: list, cfg: dict) -> dict:
    """Override loss data to create deteriorating loss ratio trend (S3)."""
    n    = len(weeks)
    plan = LOB_BASE_GWP_PLAN.get(lob, 100000)
    rng  = np.random.default_rng(hash(lob + "s3") % 2**32)

    # GWP on-plan
    ratios     = rng.uniform(0.97, 1.03, n)
    actuals    = (plan * ratios).round(0)
    ytd_actual = np.cumsum(actuals)
    ytd_plan   = np.array([plan * (i + 1) for i in range(n)])

    start      = cfg.get("loss_ratio_start", 0.53)
    end        = cfg.get("loss_ratio_end", 0.72)
    detn_week  = cfg.get("deterioration_starts_week", 5) - 1   # 0-indexed

    # Flat until deterioration week, then linear climb
    loss_ytd = np.zeros(n)
    for i in range(n):
        if i < detn_week:
            loss_ytd[i] = start + rng.uniform(-0.005, 0.005)
        else:
            progress = (i - detn_week) / max(n - detn_week - 1, 1)
            loss_ytd[i] = start + (end - start) * progress + rng.uniform(-0.003, 0.003)

    # Monotonically increasing after detn_week (enforce cumulative direction)
    for i in range(detn_week + 1, n):
        if loss_ytd[i] <= loss_ytd[i-1]:
            loss_ytd[i] = loss_ytd[i-1] + 0.008

    claims_count    = rng.integers(1, 4, n)
    claims_incurred = (claims_count * rng.uniform(25000, 80000, n)).round(0)

    # Healthy submission funnel
    submissions   = rng.integers(15, 25, n)
    bound         = rng.integers(4, 8, n)
    quoted        = bound + rng.integers(2, 5, n)
    declined      = rng.integers(2, 4, n)
    ntu           = rng.integers(1, 3, n)
    pipeline_days = rng.uniform(15, 25, n)
    open_count    = rng.integers(8, 14, n)
    open_gwp      = (open_count * plan * rng.uniform(0.8, 1.1, n)).round(0)

    return {
        "premium":     pd.DataFrame({"week_ending": weeks, "lob": lob, "actual_gwp": actuals,
                                      "plan_gwp": plan, "ytd_actual": ytd_actual, "ytd_plan": ytd_plan}),
        "submissions": pd.DataFrame({"week_ending": weeks, "lob": lob, "submissions_count": submissions,
                                      "quoted_count": quoted, "bound_count": bound,
                                      "declined_count": declined, "ntu_count": ntu}),
        "pipeline":    pd.DataFrame({"week_ending": weeks, "lob": lob, "open_quotes_count": open_count,
                                      "open_quotes_gwp_est": open_gwp, "avg_days_in_pipeline": pipeline_days}),
        "loss":        pd.DataFrame({"week_ending": weeks, "lob": lob, "new_claims_count": claims_count,
                                      "new_claims_incurred_est": claims_incurred,
                                      "attritional_loss_ratio_ytd": loss_ytd}),
    }


def _load_real_csvs() -> dict:
    return {
        "premium":     pd.read_csv(DATA_DIR / "case4_weekly_premium.csv",     parse_dates=["week_ending"]),
        "submissions": pd.read_csv(DATA_DIR / "case4_weekly_submissions.csv", parse_dates=["week_ending"]),
        "pipeline":    pd.read_csv(DATA_DIR / "case4_pipeline.csv",           parse_dates=["week_ending"]),
        "loss":        pd.read_csv(DATA_DIR / "case4_loss_indicators.csv",    parse_dates=["week_ending"]),
    }


def _load_inline_data(data: dict) -> dict:
    """Convert inline JSON arrays to DataFrames, ensuring week_ending is datetime."""
    dfs = {}
    key_map = {
        "case4_weekly_premium":     "premium",
        "case4_weekly_submissions": "submissions",
        "case4_pipeline":           "pipeline",
        "case4_loss_indicators":    "loss",
    }
    for json_key, df_key in key_map.items():
        df = pd.DataFrame(data[json_key])
        df["week_ending"] = pd.to_datetime(df["week_ending"])
        dfs[df_key] = df
    return dfs


def generate_from_params(params: dict, n_weeks: int) -> dict:
    """Synthesise full multi-LoB DataFrames from generation_params spec."""
    weeks        = _make_week_dates(n_weeks)
    healthy_lobs = params.get("healthy_lobs", [])
    healthy_gwp  = tuple(params.get("healthy_gwp_ratio_range", [0.95, 1.05]))
    healthy_lr   = tuple(params.get("healthy_loss_ratio_range", [0.40, 0.55]))

    # Collect signal-specific LoB configs
    signal_lobs = {}
    for key in ("lobs_with_signals", "lobs_with_borderline", "lobs_with_blip"):
        signal_lobs.update(params.get(key, {}))

    all_dfs = {"premium": [], "submissions": [], "pipeline": [], "loss": []}

    # Generate healthy LoB data
    for lob in healthy_lobs:
        lob_data = _generate_healthy_lob_data(lob, weeks, healthy_gwp, healthy_lr)
        for key in all_dfs:
            all_dfs[key].append(lob_data[key])

    # Generate signal-specific LoB data
    for lob, cfg in signal_lobs.items():
        signal = cfg.get("signal")
        base   = _generate_healthy_lob_data(lob, weeks, healthy_gwp, healthy_lr)

        if signal == "S1":
            lob_data = _apply_s1_override(base, lob, weeks, cfg)
        elif signal == "S3":
            lob_data = _apply_s3_override(base, lob, weeks, cfg)
        else:
            lob_data = base   # borderline/blip: use healthy base (test expects no signal)

        for key in all_dfs:
            all_dfs[key].append(lob_data[key])

    return {key: pd.concat(dfs, ignore_index=True) for key, dfs in all_dfs.items()}


def load_fixture_data(fixture: dict) -> dict:
    """Main entry point: return raw DataFrames ready for pipeline ingestion."""
    data_spec = fixture.get("data")
    n_weeks   = fixture.get("week_count", 12)

    if data_spec == "USE_REAL_CSVS":
        return _load_real_csvs()
    elif data_spec == "GENERATE_FROM_PARAMS":
        return generate_from_params(fixture.get("generation_params", {}), n_weeks)
    elif isinstance(data_spec, dict):
        return _load_inline_data(data_spec)
    else:
        raise ValueError(f"Unknown data spec in fixture: {data_spec}")
