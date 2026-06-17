"""
SQLite DB Writer
Writes the merged metrics DataFrame to a SQLite file in the run snapshot.
This is the database the Text-to-SQL agent queries.

Single table: merged_metrics
All computed columns included — hit_rate, gwp_vs_plan_ratio,
combined_ratio_ytd, loss_ratio_velocity, etc.
"""

import sqlite3
import pandas as pd
from pathlib import Path


def write_metrics_db(df: pd.DataFrame, run_dir: Path) -> str:
    """
    Write merged metrics DataFrame to SQLite.
    Returns the filename written.
    """
    db_path = run_dir / "merged_metrics.db"

    # Convert week_ending to string for SQLite compatibility
    df_out = df.copy()
    df_out["week_ending"] = df_out["week_ending"].dt.strftime("%Y-%m-%d")

    conn = sqlite3.connect(str(db_path))
    df_out.to_sql("merged_metrics", conn, if_exists="replace", index=False)

    # Create useful indexes for fast agent queries
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lob         ON merged_metrics(lob)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_week_ending ON merged_metrics(week_ending)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lob_week    ON merged_metrics(lob, week_ending)")
    conn.commit()
    conn.close()

    return "merged_metrics.db"


def get_db_schema(db_path: Path) -> str:
    """
    Return the CREATE TABLE statement + column descriptions.
    Used as context in the SQL generation prompt.
    """
    conn   = sqlite3.connect(str(db_path))
    cursor = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='merged_metrics'")
    schema = cursor.fetchone()[0]
    conn.close()
    return schema


def get_sample_rows(db_path: Path, n: int = 3) -> list:
    """Return n sample rows as list of dicts — for prompt context."""
    conn    = sqlite3.connect(str(db_path))
    cursor  = conn.execute(f"SELECT * FROM merged_metrics LIMIT {n}")
    cols    = [d[0] for d in cursor.description]
    rows    = [dict(zip(cols, row)) for row in cursor.fetchall()]
    conn.close()
    return rows
