"""
Layer 3a — Root Cause Enrichment
"""

import pandas as pd
import numpy as np
from scipy import stats as scipy_stats
from backend.config import SIGNAL_CONFIG


def _date_str(ts) -> str:
    return ts.strftime("%d %b %Y")


def enrich_signal1_root_cause(df: pd.DataFrame, signal1_findings: list) -> list:
    enriched = []
    for finding in signal1_findings:
        lob    = finding["lob"]
        grp    = df[df["lob"] == lob].sort_values("week_ending")
        n_recent = min(4, len(grp))
        recent = grp.iloc[-n_recent:]
        window_start = recent["week_ending"].iloc[0]
        window_end   = recent["week_ending"].iloc[-1]

        avg_decline_rate  = recent["decline_rate"].mean()
        avg_ntu_rate      = recent["ntu_rate"].mean()
        avg_hit_rate      = recent["hit_rate"].mean()
        avg_days_pipeline = recent["avg_days_in_pipeline"].mean()
        total_open_gwp    = recent["open_quotes_gwp_est"].sum()
        latest_days       = grp["avg_days_in_pipeline"].iloc[-1]
        days_trend        = grp["avg_days_in_pipeline"].diff().mean()

        too_selective = avg_decline_rate >= 0.25
        losing_price  = avg_ntu_rate >= 0.25 or avg_days_pipeline >= 30

        window_label = (
            f"averaged over the most recent {n_recent} weeks "
            f"({_date_str(window_start)} – {_date_str(window_end)}), not the full {len(grp)}-week period"
        )

        if too_selective and losing_price:
            root_cause = "MIXED"
            root_cause_detail = (
                f"Both selectivity and pricing appear to be factors, {window_label}. "
                f"Decline rate elevated at {avg_decline_rate:.1%} AND NTU rate is {avg_ntu_rate:.1%} "
                f"with avg pipeline days of {avg_days_pipeline:.0f}."
            )
        elif too_selective:
            root_cause = "TOO_SELECTIVE"
            root_cause_detail = (
                f"Underwriting appetite appears too restrictive, {window_label}. "
                f"Decline rate {avg_decline_rate:.1%}, while NTU rate remains modest at {avg_ntu_rate:.1%}. "
                f"Deals are being turned away before pricing, not lost at quote stage."
            )
        elif losing_price:
            root_cause = "LOSING_TO_PRICE"
            root_cause_detail = (
                f"Market pricing is likely more competitive, {window_label}. "
                f"Decline rate low at {avg_decline_rate:.1%}, but NTU rate is {avg_ntu_rate:.1%} "
                f"and avg days in pipeline is {avg_days_pipeline:.0f} days. "
                f"Quotes sitting on broker desks — brokers likely shopping for cheaper alternatives."
            )
        else:
            root_cause = "UNCLEAR"
            root_cause_detail = (
                f"No dominant root cause identified, {window_label}. "
                f"Decline rate {avg_decline_rate:.1%}, NTU rate {avg_ntu_rate:.1%}, "
                f"pipeline days {avg_days_pipeline:.0f}."
            )

        finding = dict(finding)
        finding.update({
            "root_cause":               root_cause,
            "root_cause_detail":        root_cause_detail,
            "recent_window_weeks":      int(n_recent),
            "recent_window_start":      window_start.strftime("%Y-%m-%d"),
            "recent_window_end":        window_end.strftime("%Y-%m-%d"),
            "recent_avg_decline_rate":  round(avg_decline_rate, 3),
            "recent_avg_ntu_rate":      round(avg_ntu_rate, 3),
            "recent_avg_hit_rate":      round(avg_hit_rate, 3),
            "recent_avg_pipeline_days": round(avg_days_pipeline, 1),
            "latest_pipeline_days":     round(latest_days, 1),
            "pipeline_days_trend":      round(days_trend, 2),
            "open_pipeline_gwp":        round(total_open_gwp, 0),
        })
        enriched.append(finding)
    return enriched


def enrich_signal2_root_cause(df: pd.DataFrame, signal2_findings: list) -> list:
    """
    S2 (Hit Rate Collapse) ships with baseline/window numbers from detection
    but no written explanation — this produces the same kind of explicit,
    date-labelled root_cause_detail string that S1 has, naming the exact
    baseline period, the exact recent window, and how the drop was computed.
    """
    enriched = []
    for finding in signal2_findings:
        lob = finding["lob"]
        grp = df[df["lob"] == lob].sort_values("week_ending").reset_index(drop=True)
        hit_rates = grp["hit_rate"].dropna().reset_index(drop=True)

        n_window = finding["n_window_weeks"]
        n_baseline = len(hit_rates) - n_window

        # Re-derive the date ranges for baseline and window from the same
        # rows the detector used, so the disclosed dates are exact.
        dated = grp.loc[grp["hit_rate"].notna(), ["week_ending"]].reset_index(drop=True)
        baseline_start = dated["week_ending"].iloc[0]
        baseline_end   = dated["week_ending"].iloc[n_baseline - 1]
        window_start   = dated["week_ending"].iloc[n_baseline]
        window_end     = dated["week_ending"].iloc[-1]

        baseline_mean = finding["baseline_hit_rate"]
        window_mean   = finding["window_hit_rate"]
        abs_drop      = finding["abs_drop_pp"]
        rel_drop      = finding["relative_drop_pct"]

        root_cause = "HIT_RATE_COLLAPSE"
        root_cause_detail = (
            f"Comparing a {n_baseline}-week baseline average "
            f"({_date_str(baseline_start)} – {_date_str(baseline_end)}, hit rate {baseline_mean:.1%}) "
            f"to the most recent {n_window}-week window "
            f"({_date_str(window_start)} – {_date_str(window_end)}, hit rate {window_mean:.1%}). "
            f"That is a {abs_drop:.1%} point drop, a {rel_drop:.1%} relative decline, "
            f"with {finding['pct_window_below_q25']:.0%} of the recent window's weeks "
            f"falling below the baseline's 25th percentile ({finding['baseline_q25']:.1%})."
        )

        finding = dict(finding)
        finding.update({
            "root_cause":          root_cause,
            "root_cause_detail":   root_cause_detail,
            "baseline_window_weeks": int(n_baseline),
            "baseline_window_start": baseline_start.strftime("%Y-%m-%d"),
            "baseline_window_end":   baseline_end.strftime("%Y-%m-%d"),
            "recent_window_weeks":   int(n_window),
            "recent_window_start":   window_start.strftime("%Y-%m-%d"),
            "recent_window_end":     window_end.strftime("%Y-%m-%d"),
            # Full hit-rate history (not just the window) so the dashboard
            # can chart the whole trend, with the window clearly distinguishable.
            "hit_rate_history":      hit_rates.round(3).tolist(),
        })
        enriched.append(finding)
    return enriched


def enrich_signal3_root_cause(df: pd.DataFrame, signal3_findings: list) -> list:
    """
    S3 (Deteriorating Loss Ratio Trend) similarly ships with a regression
    slope and final value but no written explanation of the trend window
    or how the estimated underwriting loss figure was derived.
    """
    enriched = []
    for finding in signal3_findings:
        lob = finding["lob"]
        grp = df[df["lob"] == lob].sort_values("week_ending").reset_index(drop=True)
        loss_series = grp["attritional_loss_ratio_ytd"].dropna().reset_index(drop=True)
        dated = grp.loc[grp["attritional_loss_ratio_ytd"].notna(), ["week_ending"]].reset_index(drop=True)

        period_start = dated["week_ending"].iloc[0]
        period_end   = dated["week_ending"].iloc[-1]
        target       = finding["loss_ratio_target"]
        final_value  = finding["final_loss_ratio"]
        recent_consec = finding["recent_consecutive_positive_weeks"]
        combined      = finding["combined_ratio_ytd"]
        ytd_actual    = finding["ytd_actual_gwp"]

        root_cause = "LOSS_RATIO_DETERIORATION"
        root_cause_detail = (
            f"Loss ratio has risen for {recent_consec} consecutive week(s) most recently, "
            f"across the full {len(loss_series)}-week period analysed "
            f"({_date_str(period_start)} – {_date_str(period_end)}). "
            f"It now stands at {final_value:.1%} as of {_date_str(period_end)}, "
            f"{(final_value - target):.1%} points above the {target:.0%} target for this line. "
            f"Estimated underwriting loss of £{finding['est_underwriting_loss']:,.0f} is calculated as "
            f"YTD actual GWP (£{ytd_actual:,.0f}) × the combined ratio's excess over 100% "
            f"(combined ratio {combined:.1%} − 100%)."
        )

        finding = dict(finding)
        finding.update({
            "root_cause":         root_cause,
            "root_cause_detail":  root_cause_detail,
            "trend_period_weeks": len(loss_series),
            "trend_period_start": period_start.strftime("%Y-%m-%d"),
            "trend_period_end":   period_end.strftime("%Y-%m-%d"),
        })
        enriched.append(finding)
    return enriched


def enrich_signal4_loss_health(df: pd.DataFrame, signal4_findings: list) -> list:
    enriched = []
    for finding in signal4_findings:
        lob  = finding["lob"]
        grp  = df[df["lob"] == lob].sort_values("week_ending").reset_index(drop=True)
        gwp  = grp["gwp_vs_plan_ratio"].dropna()
        lr   = grp["attritional_loss_ratio_ytd"].dropna()
        n    = min(len(gwp), len(lr))
        corr = float(np.corrcoef(gwp.values[:n], lr.values[:n])[0, 1]) if n >= 4 else None

        paired = grp[["week_ending", "gwp_vs_plan_ratio", "attritional_loss_ratio_ytd"]].copy()
        paired["week_ending"] = paired["week_ending"].dt.strftime("%Y-%m-%d")

        finding = dict(finding)
        finding.update({
            "gwp_loss_correlation": round(corr, 3) if corr is not None else None,
            "gwp_lr_paired_weekly": paired.to_dict("records"),
        })
        enriched.append(finding)
    return enriched


def enrich_pipeline_friction(df: pd.DataFrame) -> list:
    findings = []
    for lob, grp in df.groupby("lob"):
        latest = grp.sort_values("week_ending").iloc[-1]
        if latest["avg_days_in_pipeline"] >= 40 and latest["open_quotes_gwp_est"] > 0:
            findings.append({
                "lob":                  lob,
                "latest_pipeline_days": round(latest["avg_days_in_pipeline"], 1),
                "open_gwp_est":         round(latest["open_quotes_gwp_est"], 0),
                "open_quotes_count":    int(latest["open_quotes_count"]),
                "note": (
                    f"{lob}: {int(latest['open_quotes_count'])} open quotes worth "
                    f"£{latest['open_quotes_gwp_est']:,.0f} stalled at "
                    f"{latest['avg_days_in_pipeline']:.0f} days average."
                ),
            })
    return sorted(findings, key=lambda x: x["open_gwp_est"], reverse=True)


def enrich_all(df: pd.DataFrame, signals: dict) -> dict:
    enriched = dict(signals)
    enriched["S1_structural_underperformance"] = enrich_signal1_root_cause(
        df, signals["S1_structural_underperformance"]
    )
    enriched["S2_hit_rate_collapse"] = enrich_signal2_root_cause(
        df, signals["S2_hit_rate_collapse"]
    )
    enriched["S3_loss_ratio_deterioration"] = enrich_signal3_root_cause(
        df, signals["S3_loss_ratio_deterioration"]
    )
    enriched["S4_profitable_outperformance"] = enrich_signal4_loss_health(
        df, signals["S4_profitable_outperformance"]
    )
    enriched["pipeline_friction"] = enrich_pipeline_friction(df)
    return enriched
