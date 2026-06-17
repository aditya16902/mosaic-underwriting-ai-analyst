"""
Layer 2 — Dynamic Signal Detection Engine
"""

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
from backend.config import SIGNAL_CONFIG, LOB_PROFILES


def _profile(lob: str) -> dict:
    return LOB_PROFILES.get(lob, LOB_PROFILES["Default"])


def detect_signal1(df: pd.DataFrame) -> list:
    ratio_thresh = SIGNAL_CONFIG["s1_gwp_ratio_threshold"]
    pct_thresh   = SIGNAL_CONFIG["s1_pct_weeks_threshold"]
    findings = []

    for lob, grp in df.groupby("lob"):
        grp = grp.sort_values("week_ending")
        if len(grp) < 3:
            continue
        ratios    = grp["gwp_vs_plan_ratio"].dropna()
        pct_below = (ratios < ratio_thresh).sum() / len(ratios)

        if pct_below >= pct_thresh:
            ytd_actual  = grp["ytd_actual"].iloc[-1]
            ytd_plan    = grp["ytd_plan"].iloc[-1]
            mean_ratio  = ratios.mean()
            findings.append({
                "signal_id":   "S1",
                "signal_name": "Structural GWP Underperformance",
                "lob":         lob,
                "severity":    "HIGH" if mean_ratio < 0.65 else "MEDIUM",
                "pct_weeks_below_threshold": round(pct_below, 3),
                "mean_gwp_ratio": round(mean_ratio, 3),
                "min_gwp_ratio":  round(ratios.min(), 3),
                "max_gwp_ratio":  round(ratios.max(), 3),
                "ytd_actual_gwp": round(ytd_actual, 0),
                "ytd_plan_gwp":   round(ytd_plan, 0),
                "gwp_at_risk":    round(ytd_plan - ytd_actual, 0),
                "total_weeks":    len(grp),
                "weekly_ratios":  ratios.round(3).tolist(),
            })

    return sorted(findings, key=lambda x: x["gwp_at_risk"], reverse=True)


def detect_signal2(df: pd.DataFrame) -> list:
    abs_drop_thresh  = SIGNAL_CONFIG["s2_abs_drop_pp"]
    rel_drop_thresh  = SIGNAL_CONFIG["s2_relative_drop_pct"]
    window_below_q25 = SIGNAL_CONFIG["s2_pct_of_window_below_q25"]
    findings = []

    for lob, grp in df.groupby("lob"):
        grp       = grp.sort_values("week_ending").reset_index(drop=True)
        hit_rates = grp["hit_rate"].dropna()
        if len(hit_rates) < 5:
            continue

        n_window      = max(3, round(len(hit_rates) * 0.25))
        baseline      = hit_rates.iloc[:-n_window]
        window        = hit_rates.iloc[-n_window:]
        if len(baseline) < 3:
            continue

        baseline_mean = baseline.mean()
        baseline_q25  = baseline.quantile(0.25)
        window_mean   = window.mean()
        abs_drop      = baseline_mean - window_mean
        rel_drop      = abs_drop / baseline_mean if baseline_mean > 0 else 0
        pct_below_q25 = (window < baseline_q25).sum() / len(window)

        if (abs_drop >= abs_drop_thresh or rel_drop >= rel_drop_thresh) and pct_below_q25 >= window_below_q25:
            open_gwp = grp["open_quotes_gwp_est"].iloc[-n_window:].sum()
            findings.append({
                "signal_id":            "S2",
                "signal_name":          "Hit Rate Collapse",
                "lob":                  lob,
                "severity":             "HIGH" if rel_drop >= 0.40 else "MEDIUM",
                "baseline_hit_rate":    round(baseline_mean, 3),
                "window_hit_rate":      round(window_mean, 3),
                "abs_drop_pp":          round(abs_drop, 3),
                "relative_drop_pct":    round(rel_drop, 3),
                "pct_window_below_q25": round(pct_below_q25, 3),
                "n_window_weeks":       int(n_window),
                "baseline_q25":         round(baseline_q25, 3),
                "window_hit_rates":     window.round(3).tolist(),
                "open_pipeline_gwp":    round(open_gwp, 0),
                "total_weeks":          len(hit_rates),
            })

    return sorted(findings, key=lambda x: x["open_pipeline_gwp"], reverse=True)


def detect_signal3(df: pd.DataFrame) -> list:
    k_consecutive = SIGNAL_CONFIG["s3_consecutive_weeks"]
    findings = []

    for lob, grp in df.groupby("lob"):
        grp         = grp.sort_values("week_ending").reset_index(drop=True)
        loss_series = grp["attritional_loss_ratio_ytd"].dropna()
        if len(loss_series) < k_consecutive + 1:
            continue

        target      = _profile(lob)["loss_ratio_target"]
        final_value = loss_series.iloc[-1]
        x           = np.arange(len(loss_series))
        slope, _, r_value, _, _ = scipy_stats.linregress(x, loss_series.values)

        velocity = loss_series.diff().dropna()
        max_consec, run, recent_consec = 0, 0, 0
        for v in velocity:
            run = run + 1 if v > 0 else 0
            max_consec = max(max_consec, run)
        for v in reversed(velocity.tolist()):
            if v > 0:
                recent_consec += 1
            else:
                break

        if slope > 0 and final_value > target and (recent_consec >= k_consecutive or max_consec >= k_consecutive):
            ytd_actual     = grp["ytd_actual"].iloc[-1]
            combined_ratio = final_value + _profile(lob)["assumed_expense_ratio"]
            findings.append({
                "signal_id":   "S3",
                "signal_name": "Deteriorating Loss Ratio Trend",
                "lob":         lob,
                "severity":    "HIGH" if final_value > target * 1.15 else "MEDIUM",
                "loss_ratio_target":    round(target, 3),
                "final_loss_ratio":     round(final_value, 3),
                "breach_above_target":  round(final_value - target, 3),
                "regression_slope_per_week": round(slope, 4),
                "r_squared":            round(r_value ** 2, 3),
                "recent_consecutive_positive_weeks": int(recent_consec),
                "max_consecutive_positive_weeks":    int(max_consec),
                "combined_ratio_ytd":   round(combined_ratio, 3),
                "ytd_actual_gwp":       round(ytd_actual, 0),
                "est_underwriting_loss": round(ytd_actual * max(0, combined_ratio - 1.0), 0),
                "loss_ratio_history":   loss_series.round(3).tolist(),
                "total_weeks":          len(loss_series),
            })

    return sorted(findings, key=lambda x: x["est_underwriting_loss"], reverse=True)


def detect_signal4(df: pd.DataFrame) -> list:
    ratio_thresh = SIGNAL_CONFIG["s4_gwp_ratio_threshold"]
    pct_thresh   = SIGNAL_CONFIG["s4_pct_weeks_threshold"]
    cr_cap       = SIGNAL_CONFIG["s4_combined_ratio_cap"]
    findings = []

    for lob, grp in df.groupby("lob"):
        grp = grp.sort_values("week_ending").reset_index(drop=True)
        if len(grp) < 3:
            continue

        ratios         = grp["gwp_vs_plan_ratio"].dropna()
        pct_above      = (ratios >= ratio_thresh).sum() / len(ratios)
        final_combined = grp["combined_ratio_ytd"].iloc[-1]
        final_lr       = grp["attritional_loss_ratio_ytd"].iloc[-1]
        lr_target      = _profile(lob)["loss_ratio_target"]

        lr_series = grp["attritional_loss_ratio_ytd"].dropna()
        lr_slope, *_ = scipy_stats.linregress(np.arange(len(lr_series)), lr_series.values)

        if pct_above >= pct_thresh and final_combined < cr_cap:
            ytd_actual  = grp["ytd_actual"].iloc[-1]
            ytd_plan    = grp["ytd_plan"].iloc[-1]

            if final_lr < lr_target and lr_slope <= 0.002:
                health_verdict = "HEALTHY_GROWTH"
                health_note    = f"Loss ratio stable at {final_lr:.1%}, below target of {lr_target:.0%}. Growth is clean."
            elif final_lr < lr_target:
                health_verdict = "WATCH"
                health_note    = f"Loss ratio {final_lr:.1%} still below target but creeping upward (slope +{lr_slope:.4f}/week). Monitor."
            else:
                health_verdict = "RISK"
                health_note    = f"Loss ratio {final_lr:.1%} breaching target {lr_target:.0%}. Top-line chasing suspected."

            findings.append({
                "signal_id":   "S4",
                "signal_name": "Profitable GWP Outperformance",
                "lob":         lob,
                "severity":    "OPPORTUNITY",
                "pct_weeks_above_threshold": round(pct_above, 3),
                "mean_gwp_ratio":     round(ratios.mean(), 3),
                "final_combined_ratio": round(final_combined, 3),
                "final_loss_ratio":   round(final_lr, 3),
                "loss_ratio_target":  lr_target,
                "lr_slope_per_week":  round(lr_slope, 4),
                "health_verdict":     health_verdict,
                "health_note":        health_note,
                "ytd_actual_gwp":     round(ytd_actual, 0),
                "ytd_plan_gwp":       round(ytd_plan, 0),
                "gwp_surplus":        round(ytd_actual - ytd_plan, 0),
                "weekly_ratios":      ratios.round(3).tolist(),
                "total_weeks":        len(grp),
            })

    return sorted(findings, key=lambda x: x["gwp_surplus"], reverse=True)


def detect_all_signals(df: pd.DataFrame) -> dict:
    return {
        "S1_structural_underperformance": detect_signal1(df),
        "S2_hit_rate_collapse":           detect_signal2(df),
        "S3_loss_ratio_deterioration":    detect_signal3(df),
        "S4_profitable_outperformance":   detect_signal4(df),
    }
