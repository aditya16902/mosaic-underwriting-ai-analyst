"""
Text-to-SQL Agent
Workflow 2 of the MosAIc platform.

Flow:
  User question
      → SQL generation (gpt-4o-mini, fast)
      → SQL validation + execution (SQLite)
      → Retry with error context if SQL fails (up to 2 retries)
      → Business interpretation (gpt-4o)
      → Response with SQL shown for transparency

Langfuse tracing: trace name "text_to_sql_agent", same session_id as the
report that triggered the chat session, linking both workflows in Langfuse.

Supports versioned prompts via prompt_version param (mirrors backend.llm.chain),
so sql_gen_v1/v2.txt and sql_interpret_v1/v2.txt can be toggled for eval/regression.
"""

import json
from pathlib import Path
from typing import Optional
from openai import OpenAI
from datetime import datetime, timezone

from backend.config import LLM_CONFIG, RUNS_DIR
from backend.llm.observability import get_langfuse, make_session_id
from backend.agents.text_to_sql.schema import get_full_schema
from backend.agents.text_to_sql.sql_executor import (
    execute_sql,
    format_result_as_markdown,
)
from backend.agents.text_to_sql.db_writer import get_db_schema, get_sample_rows
from backend.storage.s3_runs import s3_enabled, download_file as s3_download_file

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

MAX_SQL_RETRIES = 2


def _prompt_file(role: str, version: str) -> str:
    """Resolve prompt filename. role: 'gen' or 'interpret'."""
    return f"sql_{role}_{version}.txt"


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


def _client() -> OpenAI:
    return OpenAI(api_key=LLM_CONFIG["openai_api_key"])


def _build_report_context(dashboard_data: dict) -> str:
    """
    Slim summary of the latest report to inject as context.
    Gives the agent awareness of what the report already concluded.
    """
    ps = dashboard_data.get("portfolio_summary", {})
    tops = dashboard_data.get("top_concerns", [])
    opp = dashboard_data.get("top_opportunity", {})
    notes = dashboard_data.get("analyst_notes", "")

    lines = [
        f"Report week: {ps.get('report_week', 'unknown')}",
        f"Portfolio vs Plan: {ps.get('portfolio_ytd_gwp_ratio', 0):.1%}",
        f"YTD Actual GWP: £{ps.get('total_ytd_actual_gwp', 0):,.0f}",
        "",
        "TOP CONCERNS FLAGGED IN THIS REPORT:",
    ]
    for c in tops:
        lines.append(
            f"  #{c.get('rank')} [{c.get('signal_id')}] {c.get('lob')} — {c.get('signal_name')}"
        )
        lines.append(f"     {c.get('one_line_rationale', '')}")

    if opp:
        lines += [
            "",
            "TOP OPPORTUNITY:",
            f"  [{opp.get('signal_id')}] {opp.get('lob')} — {opp.get('signal_name')}",
            f"  {opp.get('one_line_rationale', '')}",
        ]

    if notes:
        lines += ["", f"ANALYST NOTES: {notes}"]

    return "\n".join(lines)


def _ensure_run_files_local(run_id: str) -> None:
    """
    SQLite can only query a file that physically exists on this container's
    disk — it can't open merged_metrics.db directly out of S3. On AWS,
    Fargate's disk doesn't survive a restart/redeploy, so a run generated
    by an earlier container instance may have its files in S3 but not on
    THIS container's disk. This downloads merged_metrics.db and
    dashboard_data.json into the local runs/{run_id}/ path (creating it if
    needed) if they're missing locally — a one-time cost per run, per
    container instance, not per question asked.

    No-op when S3 isn't configured (local dev / Docker Compose), since
    local files are simply already there in that case.
    """
    if not s3_enabled():
        return

    run_dir = RUNS_DIR / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    for fname in ("merged_metrics.db", "dashboard_data.json"):
        local_path = run_dir / fname
        if local_path.exists():
            continue
        try:
            s3_download_file(run_id, fname, local_path)
        except FileNotFoundError as e:
            # merged_metrics.db missing is fatal (caught by the .exists()
            # check right after this runs, in _get_latest_run_data);
            # dashboard_data.json missing is survivable — _build_report_context
            # just gets an empty dict and the agent answers with less report
            # context, not an error.
            print(f"[Agent] Could not fetch {fname} for run {run_id} from S3: {e}")


def _get_latest_run_data(run_id: Optional[str] = None) -> tuple:
    """
    Find the latest run's db path and dashboard_data.
    If run_id given, use that specific run. Otherwise use the most recent.
    Returns (db_path, dashboard_data) or (None, {}) if no runs exist.
    """
    if run_id:
        _ensure_run_files_local(run_id)
        run_dir = RUNS_DIR / run_id
    else:
        # "Latest" without an explicit run_id only makes sense in terms of
        # what's on local disk — on AWS, this is just whatever the CURRENT
        # container instance has generated itself, which may not be the
        # true latest report if another container instance generated a
        # newer one. This is an existing, known characteristic of the
        # "no run_id given" path rather than something this S3 change
        # needs to solve: the frontend always passes the specific run_id
        # the dashboard is currently showing (see ChatPanelContent.tsx),
        # so this branch is a fallback, not the common path.
        run_dirs = [d for d in RUNS_DIR.iterdir() if d.is_dir()] if RUNS_DIR.exists() else []
        if not run_dirs:
            return None, {}
        run_dir = max(run_dirs, key=lambda d: d.stat().st_mtime)

    db_path = run_dir / "merged_metrics.db"
    dashboard_file = run_dir / "dashboard_data.json"

    if not db_path.exists():
        return None, {}

    dashboard_data = {}
    if dashboard_file.exists():
        dashboard_data = json.loads(dashboard_file.read_text())

    return db_path, dashboard_data


def generate_sql(
    question: str,
    report_context: str,
    db_path: Path,
    error_context: Optional[str] = None,
    prompt_version: str = "v1",
    trace=None,
) -> str:
    """
    Generate SQL from natural language question.
    error_context is set on retries to include the previous error.
    """
    prompt_file   = _prompt_file("gen", prompt_version)
    system_prompt = _load_prompt(prompt_file)
    schema        = get_full_schema()
    samples       = get_sample_rows(db_path, n=2)

    user_parts = [
        "## DATABASE SCHEMA",
        schema,
        "",
        "## SAMPLE ROWS (for column value reference)",
        json.dumps(samples, indent=2, default=str),
        "",
        "## REPORT CONTEXT (latest weekly report findings)",
        report_context,
        "",
        "## USER QUESTION",
        question,
    ]

    if error_context:
        user_parts += [
            "",
            "## PREVIOUS ATTEMPT FAILED",
            f"The previous SQL failed with this error: {error_context}",
            "Please generate a corrected query.",
        ]

    span = None
    if trace:
        span = trace.span(
            name="sql_generation",
            input={"question": question, "retry": error_context is not None},
            metadata={
                "model": LLM_CONFIG["llm1_model"],
                "prompt_file": prompt_file,
                "prompt_version": prompt_version,
            },
        )

    resp = _client().chat.completions.create(
        model=LLM_CONFIG["llm1_model"],  # gpt-4o-mini — fast for SQL gen
        temperature=0.0,  # deterministic SQL
        max_tokens=500,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n".join(user_parts)},
        ],
    )

    sql = resp.choices[0].message.content.strip()
    # Strip any markdown fences the model might wrap around SQL
    if sql.startswith("```"):
        sql = sql.split("```")[1]
        if sql.startswith("sql"):
            sql = sql[3:]
        sql = sql.strip()

    usage = {
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
    }

    if span:
        span.end(output={"sql": sql}, metadata={"usage": usage})

    return sql


def interpret_result(
    question: str,
    sql: str,
    result: dict,
    report_context: str,
    prompt_version: str = "v1",
    trace=None,
) -> str:
    """Interpret SQL result in business language."""
    prompt_file   = _prompt_file("interpret", prompt_version)
    system_prompt = _load_prompt(prompt_file)

    result_summary = (
        format_result_as_markdown(result)
        if result["success"]
        else f"Error: {result['error']}"
    )

    user = (
        f"## USER QUESTION\n{question}\n\n"
        f"## REPORT CONTEXT\n{report_context}\n\n"
        f"## SQL EXECUTED\n```sql\n{sql}\n```\n\n"
        f"## SQL RESULT ({result['row_count']} rows)\n{result_summary}"
    )

    span = None
    if trace:
        span = trace.span(
            name="sql_interpretation",
            input={"question": question, "row_count": result.get("row_count", 0)},
            metadata={
                "model": LLM_CONFIG["llm2_model"],
                "prompt_file": prompt_file,
                "prompt_version": prompt_version,
            },
        )

    resp = _client().chat.completions.create(
        model=LLM_CONFIG["llm2_model"],  # gpt-4o — quality interpretation
        temperature=0.1,
        max_tokens=600,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user},
        ],
    )

    answer = resp.choices[0].message.content.strip()

    usage = {
        "prompt_tokens": resp.usage.prompt_tokens,
        "completion_tokens": resp.usage.completion_tokens,
    }

    if span:
        span.end(output={"answer": answer}, metadata={"usage": usage})

    return answer


def run_agent(
    question: str,
    run_id: Optional[str] = None,
    session_id: Optional[str] = None,
    prompt_version: str = "v1",
) -> dict:
    """
    Main agent entry point.

    Args:
        question      : Natural language question from the CUO
        run_id        : Specific report run to query (None = latest)
        session_id    : Langfuse session ID to link to the report trace
        prompt_version: Which sql_gen/sql_interpret prompt version to use

    Returns dict with: answer, sql, result, report_context, error, attempts
    """
    db_path, dashboard_data = _get_latest_run_data(run_id)

    if db_path is None:
        return {
            "answer": "No report data available yet. Please generate a report first.",
            "sql": None,
            "result": None,
            "report_context": None,
            "error": "no_data",
            "attempts": 0,
        }

    report_context = _build_report_context(dashboard_data)

    ps = dashboard_data.get("portfolio_summary", {})
    if not session_id:
        session_id = dashboard_data.get("session_id") or make_session_id(
            ps.get("report_week")
        )

    langfuse = get_langfuse()
    trace = None
    if langfuse:
        trace = langfuse.trace(
            name="text_to_sql_agent",
            session_id=session_id,
            input={"question": question},
            metadata={
                "report_week": ps.get("report_week"),
                "run_id": str(run_id) if run_id else "latest",
                "user_role": "CUO",
                "prompt_version": prompt_version,
            },
            tags=["interactive-chat", "text-to-sql", f"prompt_{prompt_version}"],
        )

    # ── SQL generation + execution with retry ─────────────────────────────────
    sql = None
    result = None
    error_context = None
    attempts = 0

    for attempt in range(MAX_SQL_RETRIES + 1):
        attempts += 1
        sql = generate_sql(
            question=question,
            report_context=report_context,
            db_path=db_path,
            error_context=error_context,
            prompt_version=prompt_version,
            trace=trace,
        )

        result = execute_sql(db_path, sql)

        if result["success"]:
            break

        error_context = result["error"]
        if attempt < MAX_SQL_RETRIES:
            print(
                f"[Agent] SQL attempt {attempt + 1} failed: {error_context} — retrying..."
            )

    # ── Interpretation ────────────────────────────────────────────────────────
    answer = interpret_result(
        question=question,
        sql=sql,
        result=result,
        report_context=report_context,
        prompt_version=prompt_version,
        trace=trace,
    )

    if trace:
        trace.update(
            output={"answer": answer, "sql_success": result.get("success", False)},
            metadata={
                "sql_attempts": attempts,
                "row_count": result.get("row_count", 0),
                "session_id": session_id,
                "prompt_version": prompt_version,
            },
        )
        langfuse.flush()

    return {
        "answer": answer,
        "sql": sql,
        "result": result,
        "report_context": report_context,
        "session_id": session_id,
        "error": None if result.get("success") else result.get("error"),
        "attempts": attempts,
    }
