"""Router / agent layer — fun 20%, smallest layer.

Classifies intent, picks tool, calls it, formats answer.
Does NOT decide authorization — that is policy engine's job.

Hybrid ReAct + typed tool execution per agent-harness-construction.
"""
from __future__ import annotations

import re
from typing import Any

from ..tools.wifi_tool import get_wifi_credentials_tool, get_line_status_tool, ToolResponse


class AgentRouter:
    """Minimal router for demo. LLM would replace keyword classifier later."""

    def __init__(self):
        self.tools = {
            "get_wifi_credentials": get_wifi_credentials_tool,
            "get_line_status": get_line_status_tool,
        }

    def classify(self, user_query: str) -> str:
        q = user_query.lower()
        if "wifi" in q or "password" in q or "psk" in q or "ssid" in q:
            return "get_wifi_credentials"
        if "line" in q or "status" in q or "ont" in q or "olt" in q:
            return "get_line_status"
        return "unknown"

    def handle(
        self,
        user_query: str,
        context_kwargs: dict[str, Any],
    ) -> ToolResponse:
        """Entry that LLM agent would call — context_kwargs are TRUSTED, not from query parsing."""
        intent = self.classify(user_query)
        if intent == "unknown":
            return ToolResponse(
                status="error",
                summary="Could not classify intent",
                next_actions=["Rephrase: ask for wifi password or line status"],
                error="unknown intent",
            )
        tool = self.tools[intent]
        # subscriber_id extraction — in real system from ticket/subscriber lookup, not regex on user text alone
        # Here we support explicit subscriber_id in context_kwargs or crude regex fallback for demo
        subscriber_id = context_kwargs.get("subscriber_id")
        if not subscriber_id:
            m = re.search(r"S\d{3,}", user_query)
            subscriber_id = m.group(0) if m else None
        if not subscriber_id:
            return ToolResponse(status="error", summary="Missing subscriber_id", error="subscriber_id required")
        # Merge — context_kwargs wins for trusted signals
        return tool(subscriber_id=subscriber_id, **{k: v for k, v in context_kwargs.items() if k != "subscriber_id"})
