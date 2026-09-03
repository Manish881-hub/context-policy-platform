"""Semantic layer over undocumented schema.

You can't hand LLM raw schema dump and expect good SQL. Needs:
- introspect PRAGMA table_info + sampling data
- human-annotated mapping: what cryptic columns actually mean
- used to ground Text-to-SQL generation + validation
"""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path
from pydantic import BaseModel

from ..provisioning.db import get_connection, DB_PATH

# Human-annotated pass — the one expensive step nobody wants to do but makes accuracy jump.
# In prod, this JSON is maintained by senior engineer who reverse-engineered 2009 system.
HUMAN_ANNOTATED = {
    "SUBS_TBL": {
        "SUBS_ID": {"semantic": "subscriber_id", "description": "Subscriber primary key, e.g. S123", "sensitive": False},
        "SITE_CD": {"semantic": "site_code", "description": "Site where CPE installed, e.g. SITE_A", "sensitive": False},
        "ONT_SN": {"semantic": "ont_serial", "description": "ONT serial number", "sensitive": False},
        "WIFI_SSID": {"semantic": "wifi_ssid", "description": "WiFi SSID", "sensitive": False},
        "WIFI_PSK": {"semantic": "wifi_password", "description": "WiFi PSK — SENSITIVE, policy-gated", "sensitive": True, "policy_action": "get_wifi_credentials"},
        "LINE_STAT": {"semantic": "line_status", "description": "Line status UP/DOWN", "sensitive": False},
        "OLT_ID": {"semantic": "olt_id", "description": "OLT identifier", "sensitive": False},
    },
    "TICK_TBL": {
        "TICK_ID": {"semantic": "ticket_id", "description": "Ticket primary key", "sensitive": False},
        "SUBS_ID": {"semantic": "subscriber_id", "description": "FK to SUBS_TBL", "sensitive": False},
        "TECH_ID": {"semantic": "technician_id", "description": "Technician", "sensitive": False},
        "SITE_CD": {"semantic": "site_code", "description": "Site", "sensitive": False},
        "STATUS": {"semantic": "ticket_status", "description": "OPEN/CLOSED", "sensitive": False},
    },
}

class ColumnInfo(BaseModel):
    table: str
    cryptic: str
    semantic: str
    description: str
    sensitive: bool
    samples: list[str] = []

class SemanticLayer:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or DB_PATH

    def introspect(self) -> dict:
        """Return schema + samples + human mapping — what LLM should actually see."""
        conn = get_connection(self.db_path)
        try:
            # ensure DB exists
            conn.execute("SELECT 1 FROM SUBS_TBL LIMIT 1")
        except Exception:
            conn.close()
            from ..provisioning.db import init_db
            init_db(self.db_path)
            conn = get_connection(self.db_path)

        result: dict = {}
        for table in ["SUBS_TBL", "TICK_TBL"]:
            cur = conn.execute(f"PRAGMA table_info({table})")
            cols = cur.fetchall()
            # sample 2 rows
            try:
                sample_cur = conn.execute(f"SELECT * FROM {table} LIMIT 2")
                rows = sample_cur.fetchall()
            except Exception:
                rows = []
            table_info = {}
            for col in cols:
                name = col["name"]
                human = HUMAN_ANNOTATED.get(table, {}).get(name, {"semantic": name.lower(), "description": "", "sensitive": False})
                samples = []
                for r in rows:
                    v = r[name]
                    samples.append(str(v)[:20] if v is not None else "NULL")
                table_info[name] = {
                    "semantic": human["semantic"],
                    "description": human["description"],
                    "sensitive": human.get("sensitive", False),
                    "samples": samples,
                }
            result[table] = table_info
        conn.close()
        return result

    def columns_for_prompt(self) -> str:
        """Compact prompt snippet — semantic names LLM should generate with cryptic mapping."""
        info = self.introspect()
        lines = ["You must generate SQL using these exact legacy tables/columns (cryptic names):"]
        for table, cols in info.items():
            lines.append(f"Table {table}:")
            for cryptic, meta in cols.items():
                lines.append(f"  {cryptic} ({meta['semantic']}): {meta['description']} samples={meta['samples']}")
        lines.append("Rules: use cryptic names in SQL, not semantic; sensitive columns need policy note.")
        return "\n".join(lines)

    def is_sensitive(self, column_cryptic: str) -> bool:
        for table_cols in HUMAN_ANNOTATED.values():
            if column_cryptic in table_cols and table_cols[column_cryptic].get("sensitive"):
                return True
        return False
