"""
Lambda entry point for the scheduled weekly report.

EventBridge fires this on the configured cron schedule (stored in
schedule_config in RDS). This replaces the in-process APScheduler
that ran inside the Fargate container — it's a proper, durable
external trigger rather than an in-memory job tied to a container's
lifetime.

The actual report logic is unchanged — it calls the same
run_pipeline() function used by the manual /reports/generate route.
"""
import json
from dotenv import load_dotenv

load_dotenv()

from backend.db.database import get_connection, init_db
from backend.api.routes import run_scheduled_report
from sqlalchemy import text


def handler(event, context):
    """
    Called by EventBridge on the configured schedule.
    Checks schedule_config.enabled before running — if the user
    disabled the schedule in the UI, this exits early without
    generating a report.
    """
    print("[Scheduler Lambda] Triggered by EventBridge")

    init_db()

    conn = get_connection()
    row = conn.execute(
        text("SELECT enabled FROM schedule_config WHERE id = 1")
    ).mappings().fetchone()
    conn.close()

    if not row or not row["enabled"]:
        print("[Scheduler Lambda] Schedule is disabled — skipping.")
        return {"statusCode": 200, "body": json.dumps({"status": "skipped", "reason": "disabled"})}

    try:
        run_scheduled_report()
        print("[Scheduler Lambda] Report generation complete.")
        return {"statusCode": 200, "body": json.dumps({"status": "completed"})}
    except Exception as e:
        print(f"[Scheduler Lambda] ERROR: {e}")
        raise
