"""Structured audit log — every policy decision is recorded for forensics.

Hiring bar: grep for policy_id, technician_id, queue_origin to debug why S123 was allowed/denied.
Cloud Run: logs go to stdout as JSON, picked up by Cloud Logging.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("audit")
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False

def audit_log(
    event: str,
    policy_id: str,
    allowed: bool,
    reason: str,
    technician_id: str | None,
    queue_origin: str,
    subscriber_id: str,
    action: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,  # policy_decision | tool_call | adapter_check
        "policy_id": policy_id,
        "allowed": allowed,
        "reason": reason,
        "technician_id": technician_id,
        "queue_origin": queue_origin,
        "subscriber_id": subscriber_id,
        "action": action,
    }
    if extra:
        payload.update(extra)
    # JSON to stdout — Cloud Logging parses it
    logger.info(json.dumps(payload))
