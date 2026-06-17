"""
Safe SQL Executor
Validates and executes SQL against merged_metrics.db.
Only SELECT statements permitted — no mutations.
"""

import re
import sqlite3
from pathlib import Path
from typing import Optional


# Blocked SQL keywords — prevent any data modification
BLOCKED_KEYWORDS = [
    "INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER",
    "TRUNCATE", "REPLACE", "ATTACH", "DETACH", "PRAGMA",
]

MAX_ROWS = 500   # Hard cap — prevent accidental full-table dumps


class SQLValidationError(Exception):
    pass


def validate_sql(sql: str) -> str:
    """
    Validate SQL is a safe SELECT statement.
    Returns cleaned SQL or raises SQLValidationError.
    """
    sql_clean = sql.strip().rstrip(";")

    # Must start with SELECT
    if not re.match(r"^\s*SELECT\b", sql_clean, re.IGNORECASE):
        raise SQLValidationError(
            f"Only SELECT statements are permitted. Got: {sql_clean[:50]}..."
        )

    # Check for blocked keywords
    sql_upper = sql_clean.upper()
    for kw in BLOCKED_KEYWORDS:
        # Use word boundary to avoid false positives
        if re.search(rf"\b{kw}\b", sql_upper):
            raise SQLValidationError(
                f"Blocked keyword '{kw}' found in SQL. Only read-only queries are permitted."
            )

    # Must reference merged_metrics table
    if "merged_metrics" not in sql_clean.lower():
        raise SQLValidationError(
            "Query must reference the 'merged_metrics' table."
        )

    return sql_clean


def execute_sql(db_path: Path, sql: str) -> dict:
    """
    Validate and execute SQL. Returns result dict with columns, rows, and metadata.
    """
    try:
        sql_clean = validate_sql(sql)
    except SQLValidationError as e:
        return {
            "success":    False,
            "error":      str(e),
            "error_type": "validation",
            "sql":        sql,
            "columns":    [],
            "rows":       [],
            "row_count":  0,
        }

    # Add LIMIT if not present to prevent runaway queries
    if "LIMIT" not in sql_clean.upper():
        sql_clean = f"{sql_clean} LIMIT {MAX_ROWS}"

    try:
        conn   = sqlite3.connect(str(db_path))
        cursor = conn.execute(sql_clean)
        columns = [d[0] for d in cursor.description]
        rows    = cursor.fetchall()
        conn.close()

        return {
            "success":    True,
            "error":      None,
            "error_type": None,
            "sql":        sql_clean,
            "columns":    columns,
            "rows":       [dict(zip(columns, row)) for row in rows],
            "row_count":  len(rows),
            "truncated":  len(rows) == MAX_ROWS,
        }

    except sqlite3.Error as e:
        return {
            "success":    False,
            "error":      str(e),
            "error_type": "execution",
            "sql":        sql_clean,
            "columns":    [],
            "rows":       [],
            "row_count":  0,
        }


def format_result_as_markdown(result: dict) -> str:
    """Format SQL result as a markdown table for display."""
    if not result["success"]:
        return f"**SQL Error ({result['error_type']}):** {result['error']}"

    if result["row_count"] == 0:
        return "_No rows returned._"

    cols = result["columns"]
    rows = result["rows"]

    header    = "| " + " | ".join(cols) + " |"
    separator = "| " + " | ".join(["---"] * len(cols)) + " |"
    data_rows = []
    for row in rows:
        data_rows.append("| " + " | ".join(str(row.get(c, "")) for c in cols) + " |")

    table = "\n".join([header, separator] + data_rows)

    if result.get("truncated"):
        table += f"\n\n_Results truncated at {MAX_ROWS} rows._"

    return table
