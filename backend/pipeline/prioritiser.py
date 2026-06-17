"""
Layer 4 — Prioritiser
"""

import pandas as pd
from datetime import datetime
from backend.config import DATA_DIR


def _impact_score(finding: dict) -> float:
    sid = finding.get("signal_id")
    if sid == "S1": return float(finding.get("gwp_at_risk", 0))
    if sid == "S2": return float(finding.get("open_pipeline_gwp", 0))
    if sid == "S3": return float(finding.get("est_underwriting_loss", 0))
    if sid == "S4": return float(finding.get("gwp_surplus", 0))
    return 0.0


def build_payload(df, enriched_signals, anomalies, week_start=None, week_end=None) -> dict:
    concerns_raw = (
        enriched_signals.get("S1_structural_underperformance", [])
        + enriched_signals.get("S2_hit_rate_collapse", [])
        + enriched_signals.get("S3_loss_ratio_deterioration", [])
    )
    opportunities_raw = enriched_signals.get("S4_profitable_outperformance", [])

    for c in concerns_raw:
        c["impact_score"] = _impact_score(c)
    for o in opportunities_raw:
        o["impact_score"] = _impact_score(o)

    concerns_ranked      = sorted(concerns_raw,      key=lambda x: x["impact_score"], reverse=True)
    opportunities_ranked = sorted(opportunities_raw, key=lambda x: x["impact_score"], reverse=True)

    latest_week = df["week_ending"].max()
    latest      = df[df["week_ending"] == latest_week]

    portfolio_summary = {
        "report_week":             latest_week.strftime("%Y-%m-%d"),
        "total_weeks_analysed":    int(df["week_ending"].nunique()),
        "week_range_start":        week_start or df["week_ending"].min().strftime("%Y-%m-%d"),
        "week_range_end":          week_end   or latest_week.strftime("%Y-%m-%d"),
        "total_ytd_actual_gwp":    round(latest["ytd_actual"].sum(), 0),
        "total_ytd_plan_gwp":      round(latest["ytd_plan"].sum(), 0),
        "portfolio_ytd_gwp_ratio": round(latest["ytd_actual"].sum() / latest["ytd_plan"].sum(), 3)
                                   if latest["ytd_plan"].sum() > 0 else None,
        "lob_count":               df["lob"].nunique(),
    }

    lob_snapshot = []
    for lob, grp in df.groupby("lob"):
        last = grp.sort_values("week_ending").iloc[-1]
        lob_snapshot.append({
            "lob":                lob,
            "latest_week":        last["week_ending"].strftime("%Y-%m-%d"),
            "actual_gwp":         round(last["actual_gwp"], 0),
            "plan_gwp":           round(last["plan_gwp"], 0),
            "gwp_vs_plan_ratio":  round(last["gwp_vs_plan_ratio"], 3),
            "ytd_actual":         round(last["ytd_actual"], 0),
            "ytd_plan":           round(last["ytd_plan"], 0),
            "ytd_gwp_vs_plan":    round(last["ytd_gwp_vs_plan_ratio"], 3),
            "hit_rate":           round(last["hit_rate"], 3) if pd.notna(last["hit_rate"]) else None,
            "loss_ratio_ytd":     round(last["attritional_loss_ratio_ytd"], 3),
            "combined_ratio_ytd": round(last["combined_ratio_ytd"], 3),
            "avg_pipeline_days":  round(last["avg_days_in_pipeline"], 1),
        })

    # Full weekly series across every LoB — powers the dashboard's
    # GWP-vs-plan trend chart (by LoB, 12 weeks) and hit-rate heatmap
    # (LoB x week), neither of which can be built from lob_snapshot
    # alone since that only carries each LoB's latest week.
    weekly_series = []
    for _, row in df.sort_values(["lob", "week_ending"]).iterrows():
        weekly_series.append({
            "week_ending":       row["week_ending"].strftime("%Y-%m-%d"),
            "lob":               row["lob"],
            "gwp_vs_plan_ratio": round(row["gwp_vs_plan_ratio"], 3) if pd.notna(row["gwp_vs_plan_ratio"]) else None,
            "hit_rate":          round(row["hit_rate"], 3) if pd.notna(row["hit_rate"]) else None,
        })

    return {
        "generated_at":      datetime.utcnow().isoformat() + "Z",
        "portfolio_summary": portfolio_summary,
        "lob_snapshot":      lob_snapshot,
        "weekly_series":     weekly_series,
        "all_concerns":      concerns_ranked,
        "all_opportunities": opportunities_ranked,
        "pipeline_friction": enriched_signals.get("pipeline_friction", []),
        "anomalies":         anomalies,
        "signal_counts": {
            "S1_structural_underperformance": len(enriched_signals.get("S1_structural_underperformance", [])),
            "S2_hit_rate_collapse":           len(enriched_signals.get("S2_hit_rate_collapse", [])),
            "S3_loss_ratio_deterioration":    len(enriched_signals.get("S3_loss_ratio_deterioration", [])),
            "S4_profitable_outperformance":   len(enriched_signals.get("S4_profitable_outperformance", [])),
            "total_anomalies":                sum(len(v) for v in anomalies.values()),
        },
    }
