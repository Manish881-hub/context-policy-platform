"""Router / agent layer — fun 20%, smallest layer.

Classifies intent, picks tool, calls it, formats answer.
Does NOT decide authorization — that is policy engine's job.

Hybrid ReAct + typed tool execution per agent-harness-construction.
"""
from __future__ import annotations

import re
from typing import Any

from ..tools.wifi_tool import get_wifi_credentials_tool, get_line_status_tool, ToolResponse
from ..tools.rag_tool import query_docs_tool
from ..tools.sql_tool import query_sql_tool
from ..tools.provisioning_tools import get_subscriber_profile_tool, reset_ont_tool, get_olt_subscribers_tool


class AgentRouter:
    """Minimal router for demo. LLM would replace keyword classifier later."""

    def __init__(self):
        self.tools = {
            "get_wifi_credentials": get_wifi_credentials_tool,
            "get_line_status": get_line_status_tool,
            "get_subscriber_profile": get_subscriber_profile_tool,
            "reset_ont": reset_ont_tool,
            "get_olt_subscribers": get_olt_subscribers_tool,
            "query_docs": query_docs_tool,
            "query_sql": query_sql_tool,
        }

    def classify(self, user_query: str) -> str:
        q = user_query.lower()
        if "reset" in q and "ont" in q:
            return "reset_ont"
        if "olt" in q and any(k in q for k in ["subscriber", "how many", "list", "count"]):
            return "get_olt_subscribers"
        if any(k in q for k in ["profile", "subscriber info", "customer info"]):
            return "get_subscriber_profile"
        if any(k in q for k in ["wifi password", "wifi psk", "get wifi", "ssid for"]):
            # sql path via semantic layer also handles wifi via DB; but direct tool is more sensitive
            if "select" in q or "sql" in q or "database" in q:
                return "query_sql"
            return "get_wifi_credentials"
        if "wifi" in q or "password" in q or "psk" in q or "ssid" in q:
            if "doc" in q or "procedure" in q or "manual" in q or "how to" in q:
                return "query_docs"
            if "select" in q or "sql" in q:
                return "query_sql"
            return "get_wifi_credentials"
        if "line" in q or "ont" in q or "olt" in q:
            if "doc" in q or "procedure" in q:
                return "query_docs"
            if "select" in q or "sql" in q:
                return "query_sql"
            return "get_line_status"
        if "doc" in q or "procedure" in q or "manual" in q or "pdf" in q:
            return "query_docs"
        if "select" in q or "sql" in q or "database" in q or "table" in q:
            return "query_sql"
        return "unknown"

    def handle(
        self,
        user_query: str,
        context_kwargs: dict[str, Any],
    ) -> Any:
        """Entry that LLM agent would call — context_kwargs are TRUSTED, not from query parsing."""
        intent = self.classify(user_query)
        if intent == "unknown":
            return ToolResponse(
                status="error",
                summary="Could not classify intent",
                next_actions=["Rephrase: ask for wifi, line, docs, or sql"],
                error="unknown intent",
            )
        tool = self.tools[intent]
        # docs/sql/olt can work without subscriber_id, but wifi/line/profile/reset need it
        if intent in ("get_wifi_credentials", "get_line_status", "get_subscriber_profile", "reset_ont"):
            subscriber_id = context_kwargs.get("subscriber_id")
            if not subscriber_id:
                m = re.search(r"S\d{3,}", user_query)
                subscriber_id = m.group(0) if m else None
            if not subscriber_id:
                return ToolResponse(status="error", summary="Missing subscriber_id", error="subscriber_id required")
            return tool(subscriber_id=subscriber_id, **{k: v for k, v in context_kwargs.items() if k != "subscriber_id"})
        if intent == "get_olt_subscribers":
            m = re.search(r"OLT-\d+", user_query)
            olt_id = context_kwargs.get("olt_id") or (m.group(0) if m else "OLT-1")
            kwargs = {k: v for k, v in context_kwargs.items() if k not in ("olt_id",)}
            return tool(olt_id=olt_id, **kwargs)
        # docs / sql path: pass through all kwargs
        if intent == "query_docs":
            return tool(query=user_query, **context_kwargs)
        if intent == "query_sql":
            return tool(nl_query=user_query, **context_kwargs)
        return tool(**context_kwargs)
