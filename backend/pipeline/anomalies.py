"""
Layer 3b — Anomaly Detection
"""

import pandas as pd
import numpy as np
from backend.config import ANOMALY_CONFIG


def detect_claims_spikes(df: pd.DataFrame) -> list:
    z_thresh  = ANOMALY_CONFIG["claims_zscore_threshold"]
    anomalies = []
    for lob, grp in df.groupby("lob"):
        grp    = grp.sort_values("week_ending").reset_index(drop=True)
        series = grp["new_claims_incurred_est"].fillna(0)
        mean_val, std_val = series.mean(), series.std()
        if std_val == 0:
            continue
        z_scores = (series - mean_val) / std_val
        for _, row in grp[z_scores > z_thresh].iterrows():
            z = (row["new_claims_incurred_est"] - mean_val) / std_val
            anomalies.append({
                "type":         "CLAIMS_SPIKE",
                "lob":          lob,
                "week_ending":  row["week_ending"].strftime("%Y-%m-%d"),
                "claims_value": round(row["new_claims_incurred_est"], 0),
                "lob_mean":     round(mean_val, 0),
                "z_score":      round(z, 2),
                "note": (
                    f"{lob}: Claim of £{row['new_claims_incurred_est']:,.0f} in week "
                    f"{row['week_ending'].strftime('%d %b %Y')} is {z:.1f}σ above LoB mean "
                    f"(£{mean_val:,.0f}). Likely a single shock loss, not a trend."
                ),
            })
    return sorted(anomalies, key=lambda x: x["claims_value"], reverse=True)


def detect_stalled_pipeline(df: pd.DataFrame) -> list:
    days_thresh = ANOMALY_CONFIG["pipeline_days_threshold"]
    anomalies   = []
    for lob, grp in df.groupby("lob"):
        grp = grp.sort_values("week_ending").reset_index(drop=True)
        for _, row in grp[grp["avg_days_in_pipeline"] >= days_thresh].iterrows():
            anomalies.append({
                "type":         "STALLED_PIPELINE",
                "lob":          lob,
                "week_ending":  row["week_ending"].strftime("%Y-%m-%d"),
                "avg_days":     round(row["avg_days_in_pipeline"], 1),
                "open_gwp_est": round(row["open_quotes_gwp_est"], 0),
                "open_count":   int(row["open_quotes_count"]),
                "note": (
                    f"{lob}: {int(row['open_quotes_count'])} quotes worth "
                    f"£{row['open_quotes_gwp_est']:,.0f} stalled at "
                    f"{row['avg_days_in_pipeline']:.0f} avg days "
                    f"(week {row['week_ending'].strftime('%d %b %Y')})."
                ),
            })
    return sorted(anomalies, key=lambda x: x["open_gwp_est"], reverse=True)


def detect_funnel_divergence(df: pd.DataFrame) -> list:
    sub_spike  = ANOMALY_CONFIG["funnel_submission_spike_pct"]
    quote_drop = ANOMALY_CONFIG["funnel_quote_drop_pct"]
    anomalies  = []
    for lob, grp in df.groupby("lob"):
        grp = grp.sort_values("week_ending").reset_index(drop=True)
        grp["sub_pct_change"]   = grp["submissions_count"].pct_change()
        grp["quote_pct_change"] = grp["quoted_count"].pct_change()
        diverged = grp[(grp["sub_pct_change"] >= sub_spike) & (grp["quote_pct_change"] <= quote_drop)]
        for _, row in diverged.iterrows():
            anomalies.append({
                "type":              "FUNNEL_DIVERGENCE",
                "lob":               lob,
                "week_ending":       row["week_ending"].strftime("%Y-%m-%d"),
                "submissions_count": int(row["submissions_count"]),
                "quoted_count":      int(row["quoted_count"]),
                "sub_pct_change":    round(row["sub_pct_change"], 3),
                "quote_pct_change":  round(row["quote_pct_change"], 3),
                "note": (
                    f"{lob}: Submissions surged {row['sub_pct_change']:.0%} WoW to "
                    f"{int(row['submissions_count'])} but quoted count changed "
                    f"{row['quote_pct_change']:.0%}. Underwriting bottleneck suspected."
                ),
            })
    return anomalies


def detect_missing_data(df: pd.DataFrame) -> list:
    key_cols  = ["actual_gwp", "plan_gwp", "hit_rate", "attritional_loss_ratio_ytd", "avg_days_in_pipeline"]
    anomalies = []
    for col in key_cols:
        for _, row in df[df[col].isna()][["week_ending", "lob"]].iterrows():
            anomalies.append({
                "type":        "MISSING_DATA",
                "lob":         row["lob"],
                "week_ending": row["week_ending"].strftime("%Y-%m-%d"),
                "column":      col,
                "note":        f"Missing: {col} for {row['lob']} week {row['week_ending'].strftime('%d %b %Y')}.",
            })
    return anomalies


def detect_all_anomalies(df: pd.DataFrame) -> dict:
    return {
        "claims_spikes":     detect_claims_spikes(df),
        "stalled_pipeline":  detect_stalled_pipeline(df),
        "funnel_divergence": detect_funnel_divergence(df),
        "missing_data":      detect_missing_data(df),
    }
