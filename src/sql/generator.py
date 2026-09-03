"""Text-to-SQL generator — semantic layer + guardrails.

MVP: rule-based templates grounded in semantic layer. Swap to LLM (GCP Vertex) behind same interface:
  generator.generate(nl_query, subscriber_id) -> sql string

Why not hand raw schema dump? Accuracy collapses on undocumented cryptic names. Semantic layer
provides sampling + human-annotated meaning, which we feed to generator.

Guardrails enforced here + again at execution (defense in depth).
"""
from __future__ import annotations

import re
from pathlib import Path

from .semantic_layer import SemanticLayer
from .guardrails import validate_sql, ensure_limit

TEMPLATES: list[tuple[str, str]] = [
    (r"line\s*status.*(S\d+)", "SELECT SUBS_ID, LINE_STAT, OLT_ID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"line.*(S\d+)", "SELECT SUBS_ID, LINE_STAT, OLT_ID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"wifi.*ssid.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"wifi.*password|wifi.*psk.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID, WIFI_PSK FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"ssid.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"olt.*(S\d+)", "SELECT SUBS_ID, OLT_ID, ONT_SN FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"subscriber.*(S\d+)", "SELECT * FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
]

class SqlGenerator:
    def __init__(self, db_path: Path | None = None, semantic: SemanticLayer | None = None):
        self.semantic = semantic or SemanticLayer(db_path=db_path)
        self.db_path = db_path

    def generate(self, nl_query: str, subscriber_id: str | None = None) -> dict:
        q = nl_query.lower()
        # extract subscriber id if not given
        if not subscriber_id:
            m = re.search(r"S\d{3,}", nl_query)
            subscriber_id = m.group(0) if m else None
        if not subscriber_id:
            return {"status": "error", "error": "Missing subscriber_id for SQL", "sql": None}

        for pat, tmpl in TEMPLATES:
            if re.search(pat, q, re.IGNORECASE):
                sql = tmpl.format(sid=subscriber_id)
                # validate before returning
                ok, reason = validate_sql(sql)
                if not ok:
                    return {"status": "error", "error": f"Generated SQL rejected: {reason}", "sql": sql}
                sql = ensure_limit(sql)
                return {"status": "success", "sql": sql, "semantic_hint": self.semantic.columns_for_prompt()[:500]}

        # fallback: minimal introspected schema prompt would go to LLM here; for MVP return error with hint
        hint = self.semantic.columns_for_prompt()
        return {"status": "error", "error": f"No template matched. Schema hint: {hint[:400]}", "sql": None}

    def dry_run(self, sql: str) -> dict:
        # reuse guardrails validate only
        ok, reason = validate_sql(sql)
        return {"allowed": ok, "reason": reason}
