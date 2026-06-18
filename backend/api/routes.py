"""
FastAPI Application
Auth, report generation, report history, snapshot serving, chat agent, scheduling.
"""

import json
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

# Must run before any backend.* import, since backend.config reads
# os.getenv(...) at import time. test_runner.py already does this, but
# routes.py is now a real entry point in its own right (uvicorn imports
# it directly) so it needs to load .env itself rather than relying on
# the caller having sourced it into the shell already.
load_dotenv()

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import jwt, JWTError
from pydantic import BaseModel
from sqlalchemy import text

from backend.config import AUTH_CONFIG, RUNS_DIR, CORS_ORIGINS
from backend.db.database import get_connection, init_db, IS_SQLITE
from backend.auth.passwords import verify_password
from backend.pipeline.orchestrator import run_pipeline
from backend.storage.s3_runs import (
    s3_enabled,
    fetch_object_text,
    presigned_download_url,
    list_run_files,
    delete_run_directory,
)

app = FastAPI(title="MosAIc API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

_scheduler = None  # set on startup if APScheduler is available

# SQLite uses datetime('now'), Postgres uses now() — used in the one UPDATE
# statement in this file that touches a timestamp column directly.
_NOW_SQL = "datetime('now')" if IS_SQLITE else "now()"


@app.on_event("startup")
def startup():
    init_db()
    _start_scheduler()


# ─── Auth ─────────────────────────────────────────────────────────────────────

def create_token(username: str) -> str:
    expire = datetime.utcnow() + timedelta(minutes=AUTH_CONFIG["access_token_expire_minutes"])
    return jwt.encode({"sub": username, "exp": expire},
                      AUTH_CONFIG["secret_key"], algorithm=AUTH_CONFIG["algorithm"])


def _decode_token(token: str) -> str:
    try:
        payload  = jwt.decode(token, AUTH_CONFIG["secret_key"],
                               algorithms=[AUTH_CONFIG["algorithm"]])
        username = payload.get("sub")
        if not username:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


def verify_token(token: str = Depends(oauth2_scheme)) -> str:
    return _decode_token(token)


def verify_token_flexible(
    token: Optional[str] = None,
    bearer: Optional[str] = Depends(OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=False)),
) -> str:
    candidate = token or bearer
    if not candidate:
        raise HTTPException(status_code=401, detail="Missing token")
    return _decode_token(candidate)


@app.post("/auth/login")
def login(form: OAuth2PasswordRequestForm = Depends()):
    username = form.username.strip().lower()

    conn = get_connection()
    user = conn.execute(
        text("SELECT * FROM users WHERE username = :username"), {"username": username}
    ).mappings().fetchone()
    conn.close()

    hash_to_check = user["password_hash"] if user else "$2b$12$" + "x" * 53
    valid = verify_password(form.password, hash_to_check)

    if not user or not valid:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    return {"access_token": create_token(username), "token_type": "bearer"}


@app.get("/auth/me")
def me(username: str = Depends(verify_token)):
    conn = get_connection()
    user = conn.execute(
        text("SELECT username, display_name FROM users WHERE username = :username"),
        {"username": username},
    ).mappings().fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return {"username": user["username"], "display_name": user["display_name"] or user["username"]}


# ─── Data bounds (for the frontend date-range picker) ────────────────────────

@app.get("/data/bounds")
def get_data_bounds(username: str = Depends(verify_token)):
    """
    Min/max week_ending available in raw_metrics, so the frontend's
    custom-range generate form can constrain the date picker to dates
    that actually exist rather than allowing an empty-result range.
    """
    conn = get_connection()
    row = conn.execute(
        text("SELECT MIN(week_ending) AS min_week, MAX(week_ending) AS max_week FROM raw_metrics")
    ).mappings().fetchone()
    conn.close()
    if not row or not row["min_week"]:
        raise HTTPException(status_code=404, detail="No data found in raw_metrics table")
    return {
        "min_week": str(row["min_week"]),
        "max_week": str(row["max_week"]),
    }


# ─── Report Generation ────────────────────────────────────────────────────────

class GenerateRequest(BaseModel):
    week_start: Optional[str] = None
    week_end:   Optional[str] = None


def _save_report(run_id: str, result: dict, week_start, week_end, source: str = "manual"):
    effective_week_end = week_end or result.get("report_week")

    conn = get_connection()
    conn.execute(
        text(
            """INSERT INTO reports
               (run_id, week_start, week_end, total_weeks, status, source,
                signals_json, concerns_json, opportunities_json,
                anomalies_json, narrative_html, snapshot_path)
               VALUES (:run_id, :week_start, :week_end, :total_weeks, :status, :source,
                       :signals_json, :concerns_json, :opportunities_json,
                       :anomalies_json, :narrative_html, :snapshot_path)
               ON CONFLICT (run_id) DO UPDATE SET
                 week_start         = excluded.week_start,
                 week_end           = excluded.week_end,
                 total_weeks        = excluded.total_weeks,
                 status             = excluded.status,
                 source             = excluded.source,
                 signals_json       = excluded.signals_json,
                 concerns_json      = excluded.concerns_json,
                 opportunities_json = excluded.opportunities_json,
                 anomalies_json     = excluded.anomalies_json,
                 narrative_html     = excluded.narrative_html,
                 snapshot_path      = excluded.snapshot_path"""
        ),
        {
            "run_id": run_id,
            "week_start": week_start,
            "week_end": effective_week_end,
            "total_weeks": result.get("total_weeks"),
            "status": "completed",
            "source": source,
            "signals_json": json.dumps(result.get("payload", {}).get("signal_counts", {}), default=str),
            "concerns_json": json.dumps(result.get("top_concerns", []), default=str),
            "opportunities_json": json.dumps(result.get("top_opportunity", {}), default=str),
            "anomalies_json": json.dumps(result.get("payload", {}).get("anomalies", {}), default=str),
            "narrative_html": result.get("narrative_html", ""),
            "snapshot_path": result.get("snapshot", {}).get("run_dir", ""),
        },
    )
    conn.commit()
    conn.close()


@app.post("/reports/generate")
def generate_report(req: GenerateRequest, username: str = Depends(verify_token)):
    """Manual generation — triggered from the dashboard's Generate Report action."""
    result = run_pipeline(week_start=req.week_start, week_end=req.week_end)
    run_id = result["run_id"]
    _save_report(run_id, result, req.week_start, req.week_end, source="manual")
    return {
        "run_id":          run_id,
        "status":          "completed",
        "total_weeks":     result.get("total_weeks"),
        "report_week":     result.get("report_week"),
        "signal_counts":   result.get("signal_counts"),
        "top_concerns":    result.get("top_concerns"),
        "top_opportunity": result.get("top_opportunity"),
        "analyst_notes":   result.get("analyst_notes"),
        "session_id":      result.get("llm_chain", {}).get("session_id", ""),
    }


def run_scheduled_report():
    """Called by APScheduler at the configured day/time."""
    print("[Scheduler] Firing scheduled report generation...")
    result = run_pipeline(week_start=None, week_end=None)
    run_id = result["run_id"]
    _save_report(run_id, result, None, None, source="automated")
    print(f"[Scheduler] Scheduled report complete: {run_id}")


# ─── Report History ───────────────────────────────────────────────────────────

@app.get("/reports")
def list_reports(username: str = Depends(verify_token)):
    conn = get_connection()
    rows = conn.execute(
        text(
            "SELECT run_id, created_at, week_start, week_end, total_weeks, status, source, signals_json "
            "FROM reports ORDER BY created_at DESC"
        )
    ).mappings().fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/reports/{run_id}")
def get_report(run_id: str, username: str = Depends(verify_token)):
    conn = get_connection()
    row = conn.execute(
        text("SELECT * FROM reports WHERE run_id = :run_id"), {"run_id": run_id}
    ).mappings().fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Report not found")
    return dict(row)


@app.delete("/reports/{run_id}")
def delete_report(run_id: str, username: str = Depends(verify_token)):
    conn = get_connection()
    row = conn.execute(
        text("SELECT run_id FROM reports WHERE run_id = :run_id"), {"run_id": run_id}
    ).fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Report not found")

    conn.execute(text("DELETE FROM reports WHERE run_id = :run_id"), {"run_id": run_id})
    conn.commit()
    conn.close()

    run_dir = Path(RUNS_DIR) / run_id
    if run_dir.exists():
        shutil.rmtree(run_dir)

    delete_run_directory(run_id)
    return {"status": "deleted", "run_id": run_id}


# ─── Dashboard ────────────────────────────────────────────────────────────────

@app.get("/reports/{run_id}/dashboard")
def get_dashboard_data(run_id: str, username: str = Depends(verify_token)):
    if s3_enabled():
        try:
            return json.loads(fetch_object_text(run_id, "dashboard_data.json"))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Dashboard data not found")

    f = Path(RUNS_DIR) / run_id / "dashboard_data.json"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Dashboard data not found")
    return json.loads(f.read_text())


# ─── Narrative ────────────────────────────────────────────────────────────────

@app.get("/reports/{run_id}/narrative", response_class=HTMLResponse)
def get_narrative(run_id: str, username: str = Depends(verify_token_flexible)):
    if s3_enabled():
        try:
            return HTMLResponse(content=fetch_object_text(run_id, "narrative_report.html"))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Narrative not found")

    f = Path(RUNS_DIR) / run_id / "narrative_report.html"
    if not f.exists():
        raise HTTPException(status_code=404, detail="Narrative not found")
    return HTMLResponse(content=f.read_text(encoding="utf-8"))


# ─── Snapshot Files ───────────────────────────────────────────────────────────

@app.get("/reports/{run_id}/snapshot/files")
def list_snapshot_files(run_id: str, username: str = Depends(verify_token)):
    if s3_enabled():
        files = list_run_files(run_id)
        if not files:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return [{"name": f["name"], "size_bytes": f["size_bytes"],
                 "download_url": f"/reports/{run_id}/snapshot/download/{f['name']}"}
                for f in sorted(files, key=lambda f: f["name"])]

    snapshot_dir = Path(RUNS_DIR) / run_id
    if not snapshot_dir.exists():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return [{"name": f.name, "size_bytes": f.stat().st_size,
             "download_url": f"/reports/{run_id}/snapshot/download/{f.name}"}
            for f in sorted(snapshot_dir.iterdir())]


@app.get("/reports/{run_id}/snapshot/download/{filename}")
def download_snapshot_file(run_id: str, filename: str, username: str = Depends(verify_token)):
    if s3_enabled():
        try:
            url = presigned_download_url(run_id, filename)
            return RedirectResponse(url=url)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="File not found")

    file_path = Path(RUNS_DIR) / run_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    try:
        file_path.resolve().relative_to((Path(RUNS_DIR) / run_id).resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(path=str(file_path), filename=filename)


@app.get("/reports/{run_id}/snapshot/zip")
def download_zip(run_id: str, username: str = Depends(verify_token_flexible)):
    if s3_enabled():
        try:
            url = presigned_download_url(run_id, f"snapshot_{run_id}.zip")
            return RedirectResponse(url=url)
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="ZIP not found")

    zip_path = Path(RUNS_DIR) / run_id / f"snapshot_{run_id}.zip"
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP not found")
    return FileResponse(path=str(zip_path),
                        filename=f"mosaic_snapshot_{run_id}.zip",
                        media_type="application/zip")


# ─── Schedule Config ──────────────────────────────────────────────────────────

class ScheduleConfigRequest(BaseModel):
    enabled:     bool
    day_of_week: str
    hour:        int
    minute:      int


@app.get("/schedule")
def get_schedule(username: str = Depends(verify_token)):
    conn = get_connection()
    row = conn.execute(
        text("SELECT * FROM schedule_config WHERE id = 1")
    ).mappings().fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Schedule config not found")
    return dict(row)


@app.put("/schedule")
def update_schedule(req: ScheduleConfigRequest, username: str = Depends(verify_token)):
    conn = get_connection()
    conn.execute(
        text(
            f"""UPDATE schedule_config
                SET enabled = :enabled, day_of_week = :day_of_week,
                    hour = :hour, minute = :minute, updated_at = {_NOW_SQL}
                WHERE id = 1"""
        ),
        {
            "enabled": 1 if req.enabled else 0,
            "day_of_week": req.day_of_week,
            "hour": req.hour,
            "minute": req.minute,
        },
    )
    conn.commit()
    conn.close()
    _refresh_scheduler_job()
    return {"status": "updated", **req.dict()}


def _start_scheduler():
    global _scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        print("[Scheduler] APScheduler not installed — automated scheduling disabled locally.")
        return

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.start()
    _refresh_scheduler_job()
    print("[Scheduler] Started.")


def _refresh_scheduler_job():
    if _scheduler is None:
        return

    conn = get_connection()
    row = conn.execute(
        text("SELECT * FROM schedule_config WHERE id = 1")
    ).mappings().fetchone()
    conn.close()
    if not row:
        return

    _scheduler.remove_all_jobs()
    if not row["enabled"]:
        print("[Scheduler] Disabled — no job registered.")
        return

    _scheduler.add_job(
        run_scheduled_report,
        trigger="cron",
        day_of_week=row["day_of_week"],
        hour=row["hour"],
        minute=row["minute"],
        id="weekly_report_job",
        replace_existing=True,
    )
    print(f"[Scheduler] Job set: {row['day_of_week']} at {row['hour']:02d}:{row['minute']:02d} UTC")


# ─── Text-to-SQL Chat Agent ───────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question:       str
    run_id:          Optional[str] = None
    session_id:      Optional[str] = None
    prompt_version:  str = "v1"


@app.post("/chat")
def chat(req: ChatRequest, username: str = Depends(verify_token)):
    from backend.agents.text_to_sql.agent import run_agent

    result = run_agent(
        question=req.question,
        run_id=req.run_id,
        session_id=req.session_id,
        prompt_version=req.prompt_version,
    )

    return {
        "answer":     result["answer"],
        "sql":        result["sql"],
        "rows":       result["result"]["rows"]     if result["result"] else [],
        "columns":    result["result"]["columns"]  if result["result"] else [],
        "row_count":  result["result"]["row_count"] if result["result"] else 0,
        "success":    result["result"]["success"]  if result["result"] else False,
        "error":      result.get("error"),
        "session_id": result.get("session_id"),
    }


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "service": "MosAIc API"}
