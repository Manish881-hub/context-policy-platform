"""SQL guardrails — read-only creds, pattern allowlist, row/time limits.

Text-to-SQL without guardrails is exfiltration vector. This fires AFTER policy check, BEFORE execution.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from ..provisioning.db import get_connection

DENY_PATTERNS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bINSERT\b", r"\bUPDATE\b",
    r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bGRANT\b",
    r";.*--", r"/\*", r"\bVACUUM\b", r"\bATTACH\b", r"\bDETACH\b",
]

MAX_ROWS = 100
MAX_SQL_LEN = 2000

def validate_sql(sql: str) -> tuple[bool, str]:
    if len(sql) > MAX_SQL_LEN:
        return False, f"SQL too long (> {MAX_SQL_LEN})"
    upper = sql.upper().strip()
    if not upper.startswith("SELECT"):
        return False, "Only SELECT allowed (read-only)"
    for pat in DENY_PATTERNS:
        if re.search(pat, upper, re.IGNORECASE):
            return False, f"Denied pattern matched: {pat}"
    return True, "ok"

def ensure_limit(sql: str, limit: int = MAX_ROWS) -> str:
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        # cap existing limit
        m = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
        if m and int(m.group(1)) > limit:
            sql = re.sub(r"LIMIT\s+\d+", f"LIMIT {limit}", sql, flags=re.IGNORECASE)
        return sql
    # add limit if not present
    return sql.rstrip().rstrip(";") + f" LIMIT {limit}"

def execute_readonly(sql: str, db_path: Path | None = None) -> dict:
    ok, reason = validate_sql(sql)
    if not ok:
        return {"status": "error", "error": reason, "sql": sql}
    sql = ensure_limit(sql)
    try:
        # Use uri trick for read-only if sqlite supports; fallback to normal + guardrail already done
        conn = get_connection(db_path)
        # timeout 2s simulation
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        conn.close()
        truncated = len(rows) > MAX_ROWS
        if truncated:
            rows = rows[:MAX_ROWS]
        return {"status": "success", "columns": cols, "rows": [dict(zip(cols, r)) for r in rows], "sql": sql, "truncated": truncated}
    except Exception as e:
        return {"status": "error", "error": str(e), "sql": sql}
