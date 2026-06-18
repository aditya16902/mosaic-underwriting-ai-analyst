"""
Database setup — SQLAlchemy Core, runs against SQLite locally and
Postgres on AWS with the SAME SQL. Tables: users, reports, schedule_config,
raw_metrics.

Why SQLAlchemy Core (not an ORM, not raw sqlite3/psycopg2):
SQLite and Postgres disagree on several things this app actually uses —
parameter placeholders (? vs %s), autoincrement syntax, upsert syntax
(INSERT OR REPLACE vs ON CONFLICT), and schema introspection (PRAGMA vs
information_schema). Writing raw SQL strings per-backend would mean two
parallel implementations to keep in sync. SQLAlchemy Core's text()/table
constructs handle the placeholder and dialect differences while staying
close to plain SQL — there are no ORM models, no migration framework,
since this app's tables don't need that weight.

User accounts are NOT seeded here. There is no hardcoded username/password
anywhere in this file or in code — accounts are created via
scripts/seed_users.py, which reads plaintext credentials from a local,
gitignored file and writes bcrypt hashes to this table. See that script
for details.
"""

from sqlalchemy import create_engine, text
from backend.config import DATABASE_URL

# echo=False keeps SQL statements out of stdout in normal operation;
# flip to True locally if you need to debug a query.
_engine = create_engine(DATABASE_URL, echo=False, future=True)

IS_SQLITE = DATABASE_URL.startswith("sqlite")


def get_connection():
    """
    Returns a live SQLAlchemy connection. Caller is responsible for
    conn.commit() after writes and conn.close() when done.
    """
    return _engine.connect()


def get_engine():
    """Expose the engine for pd.read_sql() calls in the pipeline."""
    return _engine


def _column_exists(conn, table: str, column: str) -> bool:
    if IS_SQLITE:
        rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
        return any(row[1] == column for row in rows)
    else:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :column"
            ),
            {"table": table, "column": column},
        ).fetchone()
        return result is not None


def _table_exists(conn, table: str) -> bool:
    if IS_SQLITE:
        result = conn.execute(
            text("SELECT 1 FROM sqlite_master WHERE type='table' AND name=:table"),
            {"table": table},
        ).fetchone()
    else:
        result = conn.execute(
            text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = :table"
            ),
            {"table": table},
        ).fetchone()
    return result is not None


def _migrate(conn):
    """
    Lightweight in-place migrations for columns added after the original
    CREATE TABLE was written.
    """
    if not _column_exists(conn, "reports", "source"):
        conn.execute(text("ALTER TABLE reports ADD COLUMN source TEXT DEFAULT 'manual'"))
        print("[DB] Migration: added reports.source column")

    if not _column_exists(conn, "users", "display_name"):
        conn.execute(text("ALTER TABLE users ADD COLUMN display_name TEXT"))
        print("[DB] Migration: added users.display_name column")


def _create_tables_sql() -> str:
    if IS_SQLITE:
        id_col      = "INTEGER PRIMARY KEY AUTOINCREMENT"
        now_default = "DEFAULT (datetime('now'))"
    else:
        id_col      = "INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY"
        now_default = "DEFAULT now()"

    return f"""
        CREATE TABLE IF NOT EXISTS users (
            id            {id_col},
            username      TEXT    UNIQUE NOT NULL,
            password_hash TEXT    NOT NULL,
            display_name  TEXT,
            created_at    TIMESTAMP {now_default}
        );

        CREATE TABLE IF NOT EXISTS reports (
            id              {id_col},
            run_id          TEXT    UNIQUE NOT NULL,
            created_at      TIMESTAMP {now_default},
            week_start      TEXT,
            week_end        TEXT,
            total_weeks     INTEGER,
            status          TEXT    DEFAULT 'pending',
            source          TEXT    DEFAULT 'manual',
            signals_json    TEXT,
            concerns_json   TEXT,
            opportunities_json TEXT,
            anomalies_json  TEXT,
            narrative_html  TEXT,
            snapshot_path   TEXT
        );

        CREATE TABLE IF NOT EXISTS schedule_config (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            enabled     INTEGER NOT NULL DEFAULT 1,
            day_of_week TEXT    NOT NULL DEFAULT 'mon',
            hour        INTEGER NOT NULL DEFAULT 6,
            minute      INTEGER NOT NULL DEFAULT 0,
            updated_at  TIMESTAMP {now_default}
        );

        CREATE TABLE IF NOT EXISTS raw_metrics (
            week_ending                 DATE        NOT NULL,
            lob                         TEXT        NOT NULL,
            actual_gwp                  REAL,
            plan_gwp                    REAL,
            ytd_actual                  REAL,
            ytd_plan                    REAL,
            submissions_count           INTEGER,
            quoted_count                INTEGER,
            bound_count                 INTEGER,
            declined_count              INTEGER,
            ntu_count                   INTEGER,
            open_quotes_count           INTEGER,
            open_quotes_gwp_est         REAL,
            avg_days_in_pipeline        REAL,
            new_claims_count            INTEGER,
            new_claims_incurred_est     REAL,
            attritional_loss_ratio_ytd  REAL,
            PRIMARY KEY (week_ending, lob)
        );
    """


def init_db():
    """Create tables if they don't exist and run migrations."""
    with _engine.begin() as conn:
        for statement in _create_tables_sql().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))

        _migrate(conn)

        conn.execute(
            text(
                "INSERT INTO schedule_config (id, enabled, day_of_week, hour, minute) "
                "VALUES (1, 1, 'mon', 6, 0) "
                "ON CONFLICT (id) DO NOTHING"
            )
        )

    print(f"[DB] Initialised ({'SQLite' if IS_SQLITE else 'Postgres'})")


if __name__ == "__main__":
    init_db()
