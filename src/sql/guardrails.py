"""SQL guardrails — read-only creds, pattern allowlist, row/time limits.

ECC python-patterns (EAFP, specific exceptions, timer) + postgres-patterns
(statement_timeout) + security-review (parameterized, no concatenation):
fires AFTER policy check, BEFORE execution. Defense in depth with generator.
"""
from __future__ import annotations

import concurrent.futures
import re
import sqlite3
import time
from pathlib import Path

from ..provisioning.db import get_connection

DENY_PATTERNS = [
    r"\bDROP\b", r"\bDELETE\b", r"\bINSERT\b", r"\bUPDATE\b",
    r"\bALTER\b", r"\bCREATE\b", r"\bTRUNCATE\b", r"\bGRANT\b",
    r";.*--", r"/\*", r"\bVACUUM\b", r"\bATTACH\b", r"\bDETACH\b",
]

MAX_ROWS = 100
MAX_SQL_LEN = 2000
STATEMENT_TIMEOUT_S = 2.0


class SqlGuardrailError(ValueError):
    pass


def _sqlglot_check(sql: str) -> tuple[bool, str]:
    """EAFP: use sqlglot AST when installed, else fall back to regex.

    Enforces single-statement SELECT-only (postgres-patterns: statement_timeout
    is enforced separately at execution).
    """
    try:
        import sqlglot  # type: ignore
        from sqlglot import exp  # type: ignore

        parsed = sqlglot.parse(sql)
        if not parsed or len(parsed) != 1:
            return False, "Only single-statement queries allowed"
        stmt = parsed[0]
        if not isinstance(stmt, exp.Select):
            return False, "Only SELECT allowed (read-only, sqlglot AST)"
        # Forbid dangerous sub-structures even inside SELECT
        forbidden = (exp.Drop, exp.Delete, exp.Insert, exp.Update, exp.Alter, exp.Create, exp.Grant, exp.TruncateTable if hasattr(exp, "TruncateTable") else ())
        for node in stmt.walk():
            if isinstance(node, tuple):
                node = node[0]
            if forbidden and isinstance(node, forbidden):
                return False, f"Denied AST node: {type(node).__name__}"
        return True, "ok (sqlglot)"
    except ImportError:
        return True, "ok (regex fallback)"
    except Exception as e:
        return False, f"SQL parse failed: {e}"

def _record(blocked: bool) -> None:
    try:
        from ..observability.metrics import record_guardrail

        record_guardrail(blocked)
    except Exception:
        pass


def validate_sql(sql: str) -> tuple[bool, str]:
    if len(sql) > MAX_SQL_LEN:
        _record(True)
        return False, f"SQL too long (> {MAX_SQL_LEN})"
    upper = sql.upper().strip()
    if not upper.startswith("SELECT"):
        _record(True)
        return False, "Only SELECT allowed (read-only)"
    for pat in DENY_PATTERNS:
        if re.search(pat, upper, re.IGNORECASE):
            _record(True)
            return False, f"Denied pattern matched: {pat}"
    ok, reason = _sqlglot_check(sql)
    _record(not ok)
    return ok, reason

def ensure_limit(sql: str, limit: int = MAX_ROWS) -> str:
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        # cap existing limit
        m = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
        if m and int(m.group(1)) > limit:
            sql = re.sub(r"LIMIT\s+\d+", f"LIMIT {limit}", sql, flags=re.IGNORECASE)
        return sql
    # add limit if not present
    return sql.rstrip().rstrip(";") + f" LIMIT {limit}"

def _run_query(sql: str, db_path: Path | None) -> dict:
    # Specific exceptions per python-patterns (no bare except at call site)
    conn = get_connection(db_path)
    try:
        conn.execute("PRAGMA query_only = ON")
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
        cols = [d[0] for d in cur.description] if cur.description else []
        truncated = len(rows) > MAX_ROWS
        if truncated:
            rows = rows[:MAX_ROWS]
        return {"status": "success", "columns": cols, "rows": [dict(zip(cols, r)) for r in rows], "sql": sql, "truncated": truncated}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def execute_readonly(sql: str, db_path: Path | None = None, timeout_s: float = STATEMENT_TIMEOUT_S) -> dict:
    ok, reason = validate_sql(sql)
    if not ok:
        return {"status": "error", "error": reason, "sql": sql}
    sql = ensure_limit(sql)
    start = time.perf_counter()
    try:
        # postgres-patterns statement_timeout equivalent: hard wall-clock guard
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            fut = pool.submit(_run_query, sql, db_path)
            try:
                res = fut.result(timeout=timeout_s)
            except concurrent.futures.TimeoutError:
                return {"status": "error", "error": f"Statement timeout after {timeout_s}s", "sql": sql}
        res["elapsed_s"] = round(time.perf_counter() - start, 4)
        return res
    except SqlGuardrailError as e:
        return {"status": "error", "error": str(e), "sql": sql}
    except Exception as e:
        return {"status": "error", "error": str(e), "sql": sql}
