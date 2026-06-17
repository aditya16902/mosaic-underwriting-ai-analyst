"""
MosAIc Pipeline & Agent Test Runner
"""

import sys
import json
import atexit
import argparse
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def _flush_langfuse_on_exit():
    """
    Flush ALL Langfuse client instances before process exits.
    The v2 SDK batches events in a background thread — without an explicit
    flush at exit the process dies before the batch is sent.
    We flush every possible client instance: manual client, decorator singleton,
    and the chain module-level client.
    """
    flushed = []

    try:
        from backend.llm.observability import get_langfuse
        lf = get_langfuse()
        if lf:
            lf.flush()
            flushed.append("observability")
    except Exception:
        pass

    try:
        import backend.llm.chain as chain_mod
        if hasattr(chain_mod, "langfuse") and chain_mod.langfuse:
            chain_mod.langfuse.flush()
            flushed.append("chain")
    except Exception:
        pass

    try:
        # The @observe decorator maintains its own internal Langfuse() singleton
        from langfuse import Langfuse
        Langfuse().flush()
        flushed.append("decorator-singleton")
    except Exception:
        pass

    if flushed:
        print(f"\n[Langfuse] Flushed: {', '.join(flushed)}")


atexit.register(_flush_langfuse_on_exit)

from backend.pipeline.ingestor     import ingest
from backend.pipeline.signals      import detect_all_signals
from backend.pipeline.enrichment   import enrich_all
from backend.pipeline.anomalies    import detect_all_anomalies
from backend.pipeline.prioritiser  import build_payload
from backend.pipeline.orchestrator import run_pipeline


# ─── Helpers ──────────────────────────────────────────────────────────────────

def divider(title=""):
    w = 60
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{'─'*pad} {title} {'─'*pad}")
    else:
        print("─" * w)


def print_signal1(findings):
    divider("SIGNAL 1 · Structural GWP Underperformance")
    if not findings:
        print("  No findings.")
        return
    for f in findings:
        print(f"\n  LoB:         {f['lob']}")
        print(f"  Severity:    {f['severity']}")
        print(f"  Weeks below threshold: {f['pct_weeks_below_threshold']:.0%}")
        print(f"  Mean GWP ratio: {f['mean_gwp_ratio']:.2f}  (range {f['min_gwp_ratio']:.2f}–{f['max_gwp_ratio']:.2f})")
        print(f"  YTD Actual:  £{f['ytd_actual_gwp']:,.0f}")
        print(f"  YTD Plan:    £{f['ytd_plan_gwp']:,.0f}")
        print(f"  GWP at risk: £{f['gwp_at_risk']:,.0f}")
        if f.get("root_cause"):
            print(f"  Root Cause:  {f['root_cause']}")
            print(f"  Detail:      {f['root_cause_detail']}")
            print(f"  Decline rate (recent): {f['recent_avg_decline_rate']:.1%}")
            print(f"  NTU rate (recent):     {f['recent_avg_ntu_rate']:.1%}")
            print(f"  Avg pipeline days:     {f['recent_avg_pipeline_days']:.0f} days")


def print_signal2(findings):
    divider("SIGNAL 2 · Hit Rate Collapse")
    if not findings:
        print("  No findings.")
        return
    for f in findings:
        print(f"\n  LoB:               {f['lob']}")
        print(f"  Severity:          {f['severity']}")
        print(f"  Baseline hit rate: {f['baseline_hit_rate']:.1%}")
        print(f"  Window hit rate:   {f['window_hit_rate']:.1%}  (last {f['n_window_weeks']} weeks)")
        print(f"  Absolute drop:     {f['abs_drop_pp']:.1%} pp")
        print(f"  Relative drop:     {f['relative_drop_pct']:.1%}")
        print(f"  % window below Q25: {f['pct_window_below_q25']:.0%}")
        print(f"  Open pipeline GWP: £{f['open_pipeline_gwp']:,.0f}")


def print_signal3(findings):
    divider("SIGNAL 3 · Deteriorating Loss Ratio Trend")
    if not findings:
        print("  No findings.")
        return
    for f in findings:
        print(f"\n  LoB:               {f['lob']}")
        print(f"  Severity:          {f['severity']}")
        print(f"  Target loss ratio: {f['loss_ratio_target']:.1%}")
        print(f"  Final loss ratio:  {f['final_loss_ratio']:.1%}  (+{f['breach_above_target']:.1%} above target)")
        print(f"  Regression slope:  +{f['regression_slope_per_week']:.4f}/week  (R²={f['r_squared']:.2f})")
        print(f"  Consecutive +ve weeks (recent): {f['recent_consecutive_positive_weeks']}")
        print(f"  Combined ratio YTD: {f['combined_ratio_ytd']:.1%}")
        print(f"  Est. underwriting loss: £{f['est_underwriting_loss']:,.0f}")
        history_str = " → ".join(f"{x:.3f}" for x in f["loss_ratio_history"])
        print(f"  LR history: {history_str}")


def print_signal4(findings):
    divider("SIGNAL 4 · Profitable Outperformance")
    if not findings:
        print("  No findings.")
        return
    for f in findings:
        print(f"\n  LoB:                 {f['lob']}")
        print(f"  Health verdict:      {f['health_verdict']}")
        print(f"  % weeks above 1.10×: {f['pct_weeks_above_threshold']:.0%}")
        print(f"  Mean GWP ratio:      {f['mean_gwp_ratio']:.2f}")
        print(f"  Final LR:            {f['final_loss_ratio']:.1%}  (target: {f['loss_ratio_target']:.0%})")
        print(f"  Final CR:            {f['final_combined_ratio']:.1%}")
        print(f"  GWP surplus:         £{f['gwp_surplus']:,.0f}")
        print(f"  Health note:         {f['health_note']}")


def print_anomalies(anomalies):
    divider("ANOMALIES")
    total = sum(len(v) for v in anomalies.values())
    print(f"  Total: {total}")
    for atype, items in anomalies.items():
        if items:
            print(f"\n  [{atype}] — {len(items)} item(s)")
            for a in items:
                print(f"    • {a['note']}")


def print_portfolio_summary(payload):
    divider("PORTFOLIO SUMMARY")
    ps = payload["portfolio_summary"]
    print(f"  Report week:       {ps['report_week']}")
    print(f"  Weeks analysed:    {ps['total_weeks_analysed']}  ({ps['week_range_start']} → {ps['week_range_end']})")
    print(f"  YTD Actual GWP:    £{ps['total_ytd_actual_gwp']:,.0f}")
    print(f"  YTD Plan GWP:      £{ps['total_ytd_plan_gwp']:,.0f}")
    print(f"  Portfolio vs Plan: {ps['portfolio_ytd_gwp_ratio']:.1%}")
    print(f"\n  {'LoB':<28} {'Actual GWP':>12} {'Plan GWP':>12} {'vs Plan':>8} {'Hit Rate':>9} {'LR YTD':>8} {'CR YTD':>8}")
    print(f"  {'─'*28} {'─'*12} {'─'*12} {'─'*8} {'─'*9} {'─'*8} {'─'*8}")
    for row in payload["lob_snapshot"]:
        hr = f"{row['hit_rate']:.1%}" if row["hit_rate"] is not None else "  N/A  "
        print(
            f"  {row['lob']:<28} "
            f"£{row['actual_gwp']:>10,.0f} "
            f"£{row['plan_gwp']:>10,.0f} "
            f"  {row['gwp_vs_plan_ratio']:>5.2f}  "
            f"  {hr:>7}  "
            f"  {row['loss_ratio_ytd']:>5.3f}  "
            f"  {row['combined_ratio_ytd']:>5.3f}"
        )


# ─── Run modes ────────────────────────────────────────────────────────────────

def run_dry(week_start, week_end):
    print(f"\n🔍  MosAIc Pipeline — DRY RUN (no LLM)")
    if week_start or week_end:
        print(f"    Filter: {week_start or 'START'} → {week_end or 'END'}\n")
    _, df     = ingest(week_start=week_start, week_end=week_end)
    signals   = detect_all_signals(df)
    enriched  = enrich_all(df, signals)
    anomalies = detect_all_anomalies(df)
    payload   = build_payload(df=df, enriched_signals=enriched, anomalies=anomalies,
                               week_start=week_start, week_end=week_end)
    print_portfolio_summary(payload)
    print_signal1(enriched["S1_structural_underperformance"])
    print_signal2(enriched["S2_hit_rate_collapse"])
    print_signal3(enriched["S3_loss_ratio_deterioration"])
    print_signal4(enriched["S4_profitable_outperformance"])
    print_anomalies(anomalies)
    divider("SIGNAL COUNTS")
    for k, v in payload["signal_counts"].items():
        print(f"  {k}: {v}")
    print(f"\n✅  Dry run complete.\n")


def run_signals_only(week_start, week_end):
    _, df     = ingest(week_start=week_start, week_end=week_end)
    signals   = detect_all_signals(df)
    enriched  = enrich_all(df, signals)
    anomalies = detect_all_anomalies(df)
    if week_start or week_end:
        print(f"\n  Filter: {week_start or 'START'} → {week_end or 'END'}")
    print_signal1(enriched["S1_structural_underperformance"])
    print_signal2(enriched["S2_hit_rate_collapse"])
    print_signal3(enriched["S3_loss_ratio_deterioration"])
    print_signal4(enriched["S4_profitable_outperformance"])
    print_anomalies(anomalies)


def run_payload_only(week_start, week_end):
    _, df     = ingest(week_start=week_start, week_end=week_end)
    signals   = detect_all_signals(df)
    enriched  = enrich_all(df, signals)
    anomalies = detect_all_anomalies(df)
    payload   = build_payload(df=df, enriched_signals=enriched, anomalies=anomalies,
                               week_start=week_start, week_end=week_end)
    print(json.dumps(payload, indent=2, default=str))


def run_full_llm(week_start, week_end):
    print(f"\n🤖  MosAIc Pipeline — FULL RUN (with LLM chain)")
    if week_start or week_end:
        print(f"    Filter: {week_start or 'START'} → {week_end or 'END'}\n")
    result = run_pipeline(week_start=week_start, week_end=week_end, dry_run=False)
    print_portfolio_summary(result["payload"])
    divider("LLM1 TOP CONCERNS (gpt-4o-mini)")
    for c in result.get("top_concerns", []):
        print(f"\n  #{c['rank']} [{c['signal_id']}] {c['lob']} — {c['signal_name']}")
        print(f"     {c['one_line_rationale']}")
    divider("LLM1 TOP OPPORTUNITY")
    opp = result.get("top_opportunity", {})
    if opp:
        print(f"\n  [{opp.get('signal_id')}] {opp.get('lob')} — {opp.get('signal_name')}")
        print(f"  {opp.get('one_line_rationale')}")
    divider("LLM1 ANALYST NOTES")
    print(f"\n  {result.get('analyst_notes', '')}")
    divider("SNAPSHOT")
    snap = result["snapshot"]
    print(f"  Run ID:   {result['run_id']}")
    print(f"  Location: {snap['run_dir']}")
    print(f"  Files:    {list(snap['files'].keys())}")
    print(f"\n  Open narrative:  open \"{snap['run_dir']}/narrative_report.html\"")
    print(f"\n✅  Full run complete.\n")


def run_chat(question: Optional[str]):
    from backend.agents.text_to_sql.agent import run_agent

    print(f"\n💬  MosAIc Text-to-SQL Agent")
    print(f"    Queries the latest report's merged_metrics.db")
    print(f"    Type 'quit' to exit\n")

    sample_questions = [
        "What was Cyber's hit rate in each of the last 4 weeks?",
        "Which line of business had the highest loss ratio in the latest week?",
        "Show me all weeks where Excess Casualty GWP was below 60% of plan",
        "Compare Political Violence actual GWP vs plan week by week",
        "What is the average pipeline days for each LoB in the latest week?",
    ]

    if not question:
        print("  Sample questions:")
        for i, q in enumerate(sample_questions, 1):
            print(f"    {i}. {q}")
        print()

    while True:
        if question:
            q = question
        else:
            try:
                q = input("  Your question: ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Exiting.")
                break

        if q.lower() in ("quit", "exit", "q"):
            break
        if not q:
            continue

        print(f"\n  [Agent] Processing...")
        result = run_agent(question=q)

        divider("ANSWER")
        print(f"\n  {result['answer']}\n")

        divider("SQL EXECUTED")
        print(f"\n  {result['sql']}\n")

        if result["result"] and result["result"]["success"]:
            divider(f"DATA ({result['result']['row_count']} rows)")
            rows    = result["result"]["rows"]
            columns = result["result"]["columns"]
            if rows:
                col_w = {c: max(len(c), max(len(str(r.get(c, ""))) for r in rows)) for c in columns}
                header = "  " + "  ".join(c.ljust(col_w[c]) for c in columns)
                print(header)
                print("  " + "  ".join("─" * col_w[c] for c in columns))
                for row in rows[:20]:
                    print("  " + "  ".join(str(row.get(c, "")).ljust(col_w[c]) for c in columns))
                if len(rows) > 20:
                    print(f"  ... and {len(rows) - 20} more rows")
        elif result.get("error"):
            print(f"\n  ⚠️  SQL Error: {result['error']}")

        print()

        if question:
            break


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="MosAIc Test Runner")
    parser.add_argument("mode", nargs="?", default="dry",
                        choices=["dry", "signals", "payload", "llm", "chat"],
                        help="Run mode (default: dry)")
    parser.add_argument("--from",     dest="week_start", metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--to",       dest="week_end",   metavar="YYYY-MM-DD", default=None)
    parser.add_argument("--question", dest="question",   default=None,
                        help="Single question for chat mode")
    args = parser.parse_args()

    if args.mode == "dry":
        run_dry(args.week_start, args.week_end)
    elif args.mode == "signals":
        run_signals_only(args.week_start, args.week_end)
    elif args.mode == "payload":
        run_payload_only(args.week_start, args.week_end)
    elif args.mode == "llm":
        run_full_llm(args.week_start, args.week_end)
    elif args.mode == "chat":
        run_chat(args.question)
