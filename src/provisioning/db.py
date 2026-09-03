"""SQLite mock for 2009 provisioning system.

Deliberately uses cryptic column names to simulate undocumented schema.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "provisioning.db"

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

SEED = [
    ("S123", "SITE_A", "ONT-001", "HomeWiFi-A", "s3cretP@ss123", "UP", "OLT-1"),
    ("S124", "SITE_B", "ONT-002", "HomeWiFi-B", "bLueSky99!", "DOWN", "OLT-1"),
    ("S999", "SITE_X", "ONT-999", "TestSSID", "test1234", "UP", "OLT-9"),
]


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path | None = None) -> None:
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
