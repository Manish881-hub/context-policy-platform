"""Provisioning DB — SQLite default (zero-cost CI), Postgres optional (prod).

ECC postgres-patterns: statement_timeout, indexes, timestamptz where relevant.
ECC deployment-patterns: env validation at startup, fail fast.
Cryptic 2009 column names preserved to simulate undocumented schema.

Env:
  DATABASE_URL — if postgresql://... use Postgres (requires psycopg[binary]);
                 else SQLite at DB_PATH / PROVISIONING_DB_PATH.
  STATEMENT_TIMEOUT_MS — default 2000.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(os.getenv("PROVISIONING_DB_PATH", str(Path(__file__).parent / "provisioning.db")))
DATABASE_URL = os.getenv("DATABASE_URL", "")
STATEMENT_TIMEOUT_MS = int(os.getenv("STATEMENT_TIMEOUT_MS", "2000"))

# Cryptic 2009 schema — simulates real legacy naming
DDL = """
CREATE TABLE IF NOT EXISTS SUBS_TBL (
    SUBS_ID    TEXT PRIMARY KEY,  -- subscriber id, e.g. S123
    SITE_CD    TEXT,              -- site code where CPE installed
    ONT_SN     TEXT,              -- ONT serial
    WIFI_SSID  TEXT,
    WIFI_PSK   TEXT,              -- the sensitive field!
    LINE_STAT  TEXT,              -- UP/DOWN
    OLT_ID     TEXT
);
CREATE TABLE IF NOT EXISTS TICK_TBL (
    TICK_ID    TEXT PRIMARY KEY,
    SUBS_ID    TEXT,
    TECH_ID    TEXT,
    SITE_CD    TEXT,
    STATUS     TEXT
);
"""

# Postgres production DDL: same cryptic names (compat) + indexes + timeouts.
# per postgres-patterns: equality-first composite, partial for active, RLS-ready.
PG_DDL = """
CREATE TABLE IF NOT EXISTS SUBS_TBL (
    SUBS_ID    TEXT PRIMARY KEY,
    SITE_CD    TEXT,
    ONT_SN     TEXT,
    WIFI_SSID  TEXT,
    WIFI_PSK   TEXT,
    LINE_STAT  TEXT,
    OLT_ID     TEXT
);
CREATE TABLE IF NOT EXISTS TICK_TBL (
    TICK_ID    TEXT PRIMARY KEY,
    SUBS_ID    TEXT,
    TECH_ID    TEXT,
    SITE_CD    TEXT,
    STATUS     TEXT
);
CREATE INDEX IF NOT EXISTS idx_subs_olt_stat ON SUBS_TBL (OLT_ID, LINE_STAT);
CREATE INDEX IF NOT EXISTS idx_subs_site ON SUBS_TBL (SITE_CD);
CREATE INDEX IF NOT EXISTS idx_tick_subs ON TICK_TBL (SUBS_ID) WHERE STATUS <> 'CLOSED';
"""

SEED = [
    ("S123", "SITE_A", "ONT-001", "HomeWiFi-A", "s3cretP@ss123", "UP", "OLT-1"),
    ("S124", "SITE_B", "ONT-002", "HomeWiFi-B", "bLueSky99!", "DOWN", "OLT-1"),
    ("S999", "SITE_X", "ONT-999", "TestSSID", "test1234", "UP", "OLT-9"),
]


def is_postgres() -> bool:
    url = os.getenv("DATABASE_URL", DATABASE_URL)
    return url.startswith("postgresql://") or url.startswith("postgres://")


def run(conn, sql: str, params: tuple = ()):
    """DB-agnostic execute: ? for SQLite, %s for Postgres (security-review: always parameterized)."""
    if is_postgres():
        sql = sql.replace("?", "%s")
    return conn.execute(sql, params)


def get_connection(db_path: Path | None = None):
    # Production Postgres when DATABASE_URL set (EAFP per python-patterns)
    if is_postgres():
        try:
            import psycopg  # type: ignore
            from psycopg.rows import dict_row  # type: ignore

            conn = psycopg.connect(os.getenv("DATABASE_URL", DATABASE_URL), row_factory=dict_row)
            try:
                conn.execute(f"SET statement_timeout = {STATEMENT_TIMEOUT_MS}")
            except Exception:
                pass
            return conn
        except Exception as e:
            raise RuntimeError(f"Postgres requested but unavailable: {e}")
    path = Path(db_path) if db_path else DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
    if is_postgres():
        conn = get_connection()
        try:
            conn.execute(PG_DDL)
            for row in SEED:
                try:
                    conn.execute(
                        "INSERT INTO SUBS_TBL (SUBS_ID,SITE_CD,ONT_SN,WIFI_SSID,WIFI_PSK,LINE_STAT,OLT_ID) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (SUBS_ID) DO NOTHING",
                        row,
                    )
                except Exception:
                    # SQLite-style fallback if driver differs
                    pass
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:
                pass
        return
    path = db_path or DB_PATH
    conn = get_connection(path)
    try:
        conn.executescript(DDL)
        for row in SEED:
            conn.execute(
                "INSERT OR IGNORE INTO SUBS_TBL (SUBS_ID,SITE_CD,ONT_SN,WIFI_SSID,WIFI_PSK,LINE_STAT,OLT_ID) VALUES (?,?,?,?,?,?,?)",
                row,
            )
        conn.commit()
    finally:
        conn.close()


if __name__ == "__main__":
    init_db()
    print(f"Initialized {DB_PATH}")
