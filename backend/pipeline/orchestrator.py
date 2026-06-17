"""
Master Pipeline Orchestrator
"""

import secrets
from datetime import datetime
from pathlib import Path

from backend.pipeline.ingestor    import ingest
from backend.pipeline.signals     import detect_all_signals
from backend.pipeline.enrichment  import enrich_all
from backend.pipeline.anomalies   import detect_all_anomalies
from backend.pipeline.prioritiser import build_payload
from backend.llm.chain            import run_llm_chain
from backend.report.snapshot      import create_snapshot
from backend.config               import DATA_DIR


def _make_run_id(report_week: str) -> str:
    """
    Human-scannable, sortable run ID:  YYYYMMDD_HHMMSS_week<report_week>_<4charsuffix>

    - Timestamp prefix sorts chronologically as plain strings (newest last).
    - report_week makes the report's coverage visible without opening the run.
    - 4-char random suffix guards against same-second double-triggers
      (e.g. a double-click on "Generate Report" in the frontend).
    """
    now    = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    suffix = secrets.token_hex(2)  # 4 hex chars
    week   = report_week or "unknown"
    return f"{now}_week{week}_{suffix}"


def run_pipeline(week_start=None, week_end=None, data_dir: Path = DATA_DIR, dry_run: bool = False) -> dict:
    started_at = datetime.utcnow().isoformat() + "Z"

    print(f"\n{'='*60}")
    print(f"[Pipeline] Run started")
    print(f"[Pipeline] Week filter: {week_start or 'ALL'} → {week_end or 'ALL'}")
    print('='*60)

    print("[L1] Ingesting and computing metrics...")
    raw_dfs, df = ingest(data_dir=data_dir, week_start=week_start, week_end=week_end)
    print(f"[L1] Shape: {df.shape} | Weeks: {df['week_ending'].nunique()} | LoB: {df['lob'].nunique()}")

    report_week = df["week_ending"].max().strftime("%Y-%m-%d")
    run_id      = _make_run_id(report_week)
    print(f"[Pipeline] Run ID: {run_id}")

    print("[L2] Detecting signals...")
    signals = detect_all_signals(df)
    for sig, items in signals.items():
        print(f"[L2]   {sig}: {len(items)}")

    print("[L3a] Enriching with root cause analysis...")
    enriched = enrich_all(df, signals)

    print("[L3b] Detecting anomalies...")
    anomalies = detect_all_anomalies(df)
    print(f"[L3b] Total: {sum(len(v) for v in anomalies.values())}")

    print("[L4] Building payload...")
    payload = build_payload(df=df, enriched_signals=enriched, anomalies=anomalies,
                            week_start=week_start, week_end=week_end)
    print(f"[L4] Concerns: {len(payload['all_concerns'])} | Opportunities: {len(payload['all_opportunities'])}")

    if dry_run:
        print("[L5] DRY RUN — skipping LLM")
        llm_chain = {
            "llm1": {}, "llm2": {},
            "top_concerns": [], "top_opportunity": {},
            "analyst_notes": "", "narrative_html": "<p>Dry run — no narrative generated.</p>",
        }
    else:
        print("[L5] Running two-LLM chain...")
        llm_chain = run_llm_chain(payload)

    print("[Snapshot] Packaging run...")
    snapshot = create_snapshot(run_id=run_id, df=df, payload=payload, llm_chain=llm_chain)

    print(f"\n[Pipeline] ✓ Complete: {run_id}")
    return {
        "run_id":          run_id,
        "started_at":      started_at,
        "completed_at":    datetime.utcnow().isoformat() + "Z",
        "status":          "completed",
        "week_start":      week_start,
        "week_end":        week_end,
        "report_week":     report_week,
        "total_weeks":     int(df["week_ending"].nunique()),
        "payload":         payload,
        "llm_chain":       llm_chain,
        "snapshot":        snapshot,
        "top_concerns":    llm_chain.get("top_concerns", []),
        "top_opportunity": llm_chain.get("top_opportunity", {}),
        "analyst_notes":   llm_chain.get("analyst_notes", ""),
        "narrative_html":  llm_chain.get("narrative_html", ""),
        "signal_counts":   payload.get("signal_counts", {}),
    }
