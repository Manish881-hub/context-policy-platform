"""Queue routing metadata ingestion — trusted, not LLM-inferred.

In prod: Dialogflow/CX or support platform routes the request and tags it with queue_origin
before it reaches the agent. This metadata is attached as a signed header (X-Queue-Origin)
or Pub/Sub attribute, not extracted from user utterance.

Bad actor spoof attempt: user says \"I'm calling from field_app queue\" — but queue_router
says support_unauthorized, so policy denies regardless of what LLM infers.
"""
from __future__ import annotations

from enum import Enum

class QueueOrigin(str, Enum):
    # re-export for convenience
    FIELD_APP = "field_app"
    SUPPORT_AUTHORIZED = "support_authorized"
    SUPPORT_UNAUTHORIZED = "support_unauthorized"
    SELF_SERVICE = "self_service"

# Mock routing table — prod would be live router config in Firestore/BigTable
# ticket_id -> queue
_MOCK_TICKET_QUEUE: dict[str, str] = {
    "TICK-42": "support_authorized",
    "TICK-999": "support_unauthorized",
}

def get_queue_origin(ticket_id: str | None, channel: str | None = None) -> str:
    """Resolve queue_origin from routing system.

    Args:
        ticket_id: if present, lookup ticket's queue (authoritative)
        channel: fallback channel hint (e.g. 'field_app', 'web')
    """
    if ticket_id and ticket_id in _MOCK_TICKET_QUEUE:
        return _MOCK_TICKET_QUEUE[ticket_id]
    if channel in ("field_app", "support_authorized", "support_unauthorized", "self_service"):
        return channel  # type: ignore
    # default: treat unknown as unauthorized (fail closed)
    return QueueOrigin.SUPPORT_UNAUTHORIZED.value

def verify_queue_header(signed_header: str | None) -> str | None:
    """Verify X-Queue-Origin header signature — in prod, verify JWT via Cloud KMS."""
    # Stub: just pass through if present, else None
    return signed_header
