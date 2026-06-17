"""
One-time / as-needed user seeding script.

Reads plaintext usernames+passwords from a LOCAL, GITIGNORED file
(scripts/seed_users.local.json — never commit this file) and writes
bcrypt-hashed credentials into the users table. Plaintext passwords are
never stored anywhere, never logged, and never appear in code — they
exist only transiently in memory while this script runs, and in
seed_users.local.json on your own machine.

Usage:
    1. Copy scripts/seed_users.example.json to scripts/seed_users.local.json
    2. Fill in real username/password/display_name entries
    3. python -m scripts.seed_users
    4. (optional) delete scripts/seed_users.local.json once seeding is done —
       it's only needed at seed time, not at runtime.

Re-running is safe: existing usernames get their password/display_name
updated (in case you need to rotate a password), new usernames get
inserted. Nothing is ever deleted.

Works against either backend (SQLite locally, Postgres on AWS) — set
DATABASE_URL before running this against AWS's RDS instance to seed real
user accounts there, the same way you seeded the local SQLite file.
"""

import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.db.database import get_connection, init_db
from backend.auth.passwords import hash_password

SEED_FILE = Path(__file__).resolve().parent / "seed_users.local.json"


def load_seed_users() -> list:
    if not SEED_FILE.exists():
        print(f"[Seed] No seed file found at {SEED_FILE}")
        print("[Seed] Create it from scripts/seed_users.example.json first.")
        sys.exit(1)
    data = json.loads(SEED_FILE.read_text())
    if not isinstance(data, list):
        print("[Seed] seed_users.local.json must be a JSON array of {username, password, display_name}.")
        sys.exit(1)
    return data


def seed_users():
    init_db()
    users = load_seed_users()

    conn = get_connection()

    for entry in users:
        username     = entry["username"].strip().lower()
        password     = entry["password"]
        display_name = entry.get("display_name", username)

        pw_hash = hash_password(password)

        conn.execute(
            text(
                """INSERT INTO users (username, password_hash, display_name)
                   VALUES (:username, :password_hash, :display_name)
                   ON CONFLICT (username) DO UPDATE SET
                     password_hash = excluded.password_hash,
                     display_name  = excluded.display_name"""
            ),
            {"username": username, "password_hash": pw_hash, "display_name": display_name},
        )
        print(f"[Seed] Upserted user: {username} ({display_name})")

    conn.commit()
    conn.close()
    print(f"[Seed] Done — {len(users)} user(s) processed.")


if __name__ == "__main__":
    seed_users()
