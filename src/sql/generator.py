"""Text-to-SQL generator — semantic layer + guardrails + pluggable LLM.

ECC python-patterns (Protocol duck-typing, EAFP):
- LLMProvider protocol: Vertex LLM in prod, templates in CI/zero-cost.
- generate() tries LLM when SQL_LLM_BACKEND=vertex and creds exist, else templates.
  Same return shape so evals stay deterministic.

Guardrails enforced here + again at execution (defense in depth).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Protocol

from .semantic_layer import SemanticLayer
from .guardrails import validate_sql, ensure_limit


class LLMProvider(Protocol):
    def text_to_sql(self, nl_query: str, schema_hint: str) -> str | None:
        """Return raw SQL or None if cannot handle."""
        ...

TEMPLATES: list[tuple[str, str]] = [
    (r"line\s*status.*(S\d+)", "SELECT SUBS_ID, LINE_STAT, OLT_ID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"line.*(S\d+)", "SELECT SUBS_ID, LINE_STAT, OLT_ID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"wifi.*ssid.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"wifi.*password|wifi.*psk.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID, WIFI_PSK FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"ssid.*(S\d+)", "SELECT SUBS_ID, WIFI_SSID FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"olt.*(S\d+)", "SELECT SUBS_ID, OLT_ID, ONT_SN FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
    (r"subscriber.*(S\d+)", "SELECT * FROM SUBS_TBL WHERE SUBS_ID='{sid}'"),
]

class VertexProvider:
    """GCP Vertex AI provider — only used when SQL_LLM_BACKEND=vertex.

    EAFP: missing creds/libs -> return None so caller falls back to templates.
    No billing incurred in CI because backend defaults to templates.
    """

    def text_to_sql(self, nl_query: str, schema_hint: str) -> str | None:
        if os.getenv("SQL_LLM_BACKEND") != "vertex":
            return None
        try:
            import vertexai  # type: ignore
            from vertexai.generative_models import GenerativeModel  # type: ignore

            project = os.getenv("GCP_PROJECT")
            location = os.getenv("GCP_LOCATION", "asia-south1")
            if not project:
                return None
            vertexai.init(project=project, location=location)
            model = GenerativeModel(os.getenv("SQL_LLM_MODEL", "gemini-1.5-flash"))
            prompt = f"Generate ONE read-only SELECT for legacy schema.\n{schema_hint}\nNL: {nl_query}\nSQL:"
            resp = model.generate_content(prompt)
            text = (resp.text or "").strip()
            m = re.search(r"SELECT[\s\S]+?;", text, re.IGNORECASE)
            return m.group(0) if m else (text if text.upper().startswith("SELECT") else None)
        except Exception:
            return None


class SqlGenerator:
    def __init__(self, db_path: Path | None = None, semantic: SemanticLayer | None = None, llm: LLMProvider | None = None):
        self.semantic = semantic or SemanticLayer(db_path=db_path)
        self.db_path = db_path
        self.llm = llm or VertexProvider()

    def generate(self, nl_query: str, subscriber_id: str | None = None) -> dict:
        q = nl_query.lower()
        # extract subscriber id if not given
        if not subscriber_id:
            m = re.search(r"S\d{3,}", nl_query)
            subscriber_id = m.group(0) if m else None
        if not subscriber_id:
            return {"status": "error", "error": "Missing subscriber_id for SQL", "sql": None}

        # 1. Try pluggable LLM first (prod), fall back to templates (CI/zero-cost)
        try:
            llm_sql = self.llm.text_to_sql(nl_query, self.semantic.columns_for_prompt())
        except Exception:
            llm_sql = None
        if llm_sql:
            ok, reason = validate_sql(llm_sql)
            if ok:
                return {"status": "success", "sql": ensure_limit(llm_sql), "backend": "llm"}
            # fall through to templates if LLM output rejected

        for pat, tmpl in TEMPLATES:
            if re.search(pat, q, re.IGNORECASE):
                sql = tmpl.format(sid=subscriber_id)
                # validate before returning
                ok, reason = validate_sql(sql)
                if not ok:
                    return {"status": "error", "error": f"Generated SQL rejected: {reason}", "sql": sql}
                sql = ensure_limit(sql)
                return {"status": "success", "sql": sql, "backend": "templates", "semantic_hint": self.semantic.columns_for_prompt()[:500]}

        # fallback: minimal introspected schema prompt would go to LLM here; for MVP return error with hint
        hint = self.semantic.columns_for_prompt()
        return {"status": "error", "error": f"No template matched. Schema hint: {hint[:400]}", "sql": None}

    def dry_run(self, sql: str) -> dict:
        # reuse guardrails validate only
        ok, reason = validate_sql(sql)
        return {"allowed": ok, "reason": reason}
