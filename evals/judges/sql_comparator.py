"""
SQL Result Comparator
Deterministic, loose comparison between the agent's SQL result and a
hand-written reference query's result. "Loose" means: compare the actual
data values returned, not SQL text, column order, or column naming —
two stylistically different but equivalent queries should compare equal.
"""

import sqlite3
from pathlib import Path
from typing import Optional


def _run_reference_sql(db_path: Path, reference_sql: str) -> dict:
    """Execute the hand-written reference query directly (bypasses agent validation)."""
    try:
        conn = sqlite3.connect(str(db_path))
        cursor = conn.execute(reference_sql)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        conn.close()
        return {
            "success": True,
            "columns": columns,
            "rows": [dict(zip(columns, row)) for row in rows],
            "row_count": len(rows),
        }
    except sqlite3.Error as e:
        return {"success": False, "error": str(e), "columns": [], "rows": [], "row_count": 0}


def _normalize_value(v, tolerance: float = 1e-3):
    """Round floats for tolerant comparison; pass through other types."""
    if isinstance(v, float):
        return round(v, 3)
    return v


def _row_to_value_set(row: dict) -> frozenset:
    """
    Convert a row dict to a comparable set of (normalized) values,
    ignoring column names — so {"lob": "Cyber", "hit_rate": 0.125} and
    {"line_of_business": "Cyber", "rate": 0.125} compare equal.
    """
    return frozenset(_normalize_value(v) for v in row.values())


def compare_sql_results(
    db_path: Path,
    reference_sql: Optional[str],
    agent_result: dict,
) -> dict:
    """
    Loosely compare agent_result (from sql_executor.execute_sql) against
    the result of running reference_sql directly.

    Returns a dict with:
      comparable        : whether a reference_sql was even provided
      reference_success : did the reference query run
      values_match       : bool — loose value-set comparison passed
      row_count_match    : bool — same number of rows
      missing_rows        : reference rows not found (as value sets) in agent result
      extra_rows           : agent rows not found in reference result
      reference_row_count / agent_row_count
    """
    if not reference_sql:
        return {
            "comparable": False,
            "reference_success": None,
            "values_match": None,
            "row_count_match": None,
            "reference_row_count": None,
            "agent_row_count": agent_result.get("row_count"),
            "missing_rows": [],
            "extra_rows": [],
        }

    ref = _run_reference_sql(db_path, reference_sql)

    if not ref["success"]:
        return {
            "comparable": True,
            "reference_success": False,
            "reference_error": ref.get("error"),
            "values_match": False,
            "row_count_match": False,
            "reference_row_count": 0,
            "agent_row_count": agent_result.get("row_count"),
            "missing_rows": [],
            "extra_rows": [],
        }

    if not agent_result.get("success"):
        return {
            "comparable": True,
            "reference_success": True,
            "values_match": False,
            "row_count_match": False,
            "reference_row_count": ref["row_count"],
            "agent_row_count": 0,
            "missing_rows": [_row_to_value_set(r) for r in ref["rows"]],
            "extra_rows": [],
        }

    ref_sets   = [_row_to_value_set(r) for r in ref["rows"]]
    agent_sets = [_row_to_value_set(r) for r in agent_result["rows"]]

    # Loose comparison: every reference row's value-set should appear
    # somewhere in the agent's rows (order and column naming irrelevant).
    missing = [s for s in ref_sets if s not in agent_sets]
    extra   = [s for s in agent_sets if s not in ref_sets]

    row_count_match = ref["row_count"] == agent_result["row_count"]
    values_match    = len(missing) == 0   # agent must contain everything reference found

    return {
        "comparable": True,
        "reference_success": True,
        "values_match": values_match,
        "row_count_match": row_count_match,
        "reference_row_count": ref["row_count"],
        "agent_row_count": agent_result["row_count"],
        "missing_rows": [list(s) for s in missing],
        "extra_rows": [list(s) for s in extra],
    }


def check_schema_adherence(sql: str, allowed_columns: list) -> dict:
    """
    Deterministic check: does the SQL reference only columns we know are real?
    Crude but effective — looks for any of a small set of known-hallucinated
    column names that commonly get invented for this kind of schema.
    """
    KNOWN_HALLUCINATION_TRAPS = [
        "underwriter", "broker", "policy_number", "claim_id", "region",
        "underwriter_name", "underwriter_id", "assigned_to", "agent_name",
        "currency", "usd", "fx_rate", "exchange_rate",
    ]
    sql_lower = sql.lower()
    found_traps = [trap for trap in KNOWN_HALLUCINATION_TRAPS if trap in sql_lower]

    return {
        "adherent": len(found_traps) == 0,
        "hallucinated_terms_found": found_traps,
    }
