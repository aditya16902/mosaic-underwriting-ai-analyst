"""
Database setup — SQLAlchemy Core, runs against SQLite locally and
Postgres on AWS with the SAME SQL. Tables: users, reports, schedule_config.

Why SQLAlchemy Core (not an ORM, not raw sqlite3/psycopg2):
SQLite and Postgres disagree on several things this app actually uses —
parameter placeholders (? vs %s), autoincrement syntax, upsert syntax
(INSERT OR REPLACE vs ON CONFLICT), and schema introspection (PRAGMA vs
information_schema). Writing raw SQL strings per-backend would mean two
parallel implementations to keep in sync. SQLAlchemy Core's text()/table
constructs handle the placeholder and dialect differences while staying
close to plain SQL — there are no ORM models, no migration framework,
since this app's three tables don't need that weight.

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
    conn.commit() after writes and conn.close() when done — this mirrors
    the sqlite3 connection lifecycle the rest of the app was written
    against, so call sites barely changed when this moved off sqlite3.

    Row access: a fetched row supports both row["column"] (via
    SQLAlchemy's Row.__getitem__ on string keys, available since 1.4)
    and dict(row._mapping) for converting a whole row to a plain dict —
    the same two access patterns routes.py already relies on.
    """
    return _engine.connect()


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


def _migrate(conn):
    """
    Lightweight in-place migrations for columns added after the original
    CREATE TABLE was written. CREATE TABLE IF NOT EXISTS won't retroactively
    alter a table that already exists, so new columns need an explicit
    ALTER TABLE guarded by an existence check, on either backend.
    """
    if not _column_exists(conn, "reports", "source"):
        # 'manual'    — triggered via the dashboard's Generate Report action
        # 'automated' — triggered by the scheduled job (APScheduler locally, EventBridge on AWS)
        conn.execute(text("ALTER TABLE reports ADD COLUMN source TEXT DEFAULT 'manual'"))
        print("[DB] Migration: added reports.source column")

    if not _column_exists(conn, "users", "display_name"):
        # Shown in the UI (e.g. "Signed in as Shambavi") instead of the
        # full email address used as the login username.
        conn.execute(text("ALTER TABLE users ADD COLUMN display_name TEXT"))
        print("[DB] Migration: added users.display_name column")


def _create_tables_sql() -> str:
    """
    Returns the CREATE TABLE statements for whichever backend is active.
    The two versions differ only in the autoincrement/identity syntax and
    the default-timestamp function — everything else is shared SQL valid
    on both SQLite and Postgres.
    """
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
    """


def init_db():
    """Create tables if they don't exist and run migrations. Does NOT seed any user."""
    with _engine.begin() as conn:
        # executescript-equivalent: SQLAlchemy's text() runs one statement
        # at a time, so split on ';' rather than relying on a multi-statement
        # execute (which psycopg2/Postgres won't accept the way sqlite3 did).
        for statement in _create_tables_sql().split(";"):
            statement = statement.strip()
            if statement:
                conn.execute(text(statement))

        _migrate(conn)

        # Seed default schedule row (single-row config table, id always 1).
        # ON CONFLICT DO NOTHING is valid on both SQLite (3.24+) and Postgres —
        # this is the one upsert-shaped statement that didn't need a
        # backend-specific branch.
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
