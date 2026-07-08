"""
One-off script to create the mosaic database.
Connect via DATABASE_URL pointing to 'postgres' database.
"""
import sys, os
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import psycopg2

def create_database():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("[Error] DATABASE_URL not set")
        sys.exit(1)
    clean = url.replace("postgresql+psycopg2://", "postgresql://")
    print(f"[Create DB] Connecting to: {clean.split('@')[1]}")
    conn = psycopg2.connect(clean)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM pg_database WHERE datname = 'mosaic'")
    exists = cur.fetchone()
    if exists:
        print("[Create DB] Database mosaic already exists.")
    else:
        cur.execute("CREATE DATABASE mosaic")
        print("[Create DB] Database mosaic created successfully.")
    cur.close()
    conn.close()

if __name__ == "__main__":
    create_database()
