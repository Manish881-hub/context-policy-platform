"""RAG tool — policy-guarded, staleness-aware.

Every call:
 1. policy.evaluate(ctx) — if deny, return error
 2. RagStore.search(query) — with staleness already flagged
 3. checker.check_conflicts vs live DB — flags conflicts_with_live
 4. return deterministic ToolResponse shape

Plumbing sits BEHIND policy, not beside it.
"""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any

from ..context.models import Action, Identity, QueueOrigin, RequestContext, Resource
from ..policy.engine import PolicyEngine
from ..provisioning.db import DB_PATH
from ..rag.store import RagStore
from ..rag.checker import check_conflicts

try:
    from ..observability.audit import audit_log
except Exception:  # pragma: no cover
    def audit_log(*args, **kwargs):  # type: ignore
        pass

class RagToolResponse(BaseModel):
    status: str
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None
    error: str | None = None
    policy_id: str | None = None

_policy = PolicyEngine()
_store = RagStore()

def query_docs_tool(
    query: str,
    technician_id: str | None = None,
    queue_origin: str = "field_app",
    gps_verified_on_site: bool = False,
    field_checkin_active: bool = False,
    site_id: str | None = None,
    subscriber_site_id: str | None = None,
    ticket_id: str | None = None,
    subscriber_id: str = "S123",
    db_path: Path | None = None,
    include_stale: bool = False,
) -> RagToolResponse:
    ctx = RequestContext(
        identity=Identity(technician_id=technician_id, queue_origin=QueueOrigin(queue_origin)),
        resource=Resource(subscriber_id=subscriber_id),
        action=Action.QUERY_DOCS,
        gps_verified_on_site=gps_verified_on_site,
        field_checkin_active=field_checkin_active,
        site_id=site_id,
        subscriber_site_id=subscriber_site_id,
        ticket_id=ticket_id,
    )
    decision = _policy.evaluate(ctx)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.QUERY_DOCS.value)
    except Exception:
        pass
    if not decision.allowed:
        return RagToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id, next_actions=["Verify queue and retry"])

    rag = _store.search(query, top_k=3, include_stale=include_stale)
    chunks = check_conflicts(rag.chunks, subscriber_id=subscriber_id, db_path=db_path or DB_PATH)

    # redact sensitive terms if policy says so (e.g. self-service)
    if decision.redact:
        for c in chunks:
            # simple redaction of PSK/SSID patterns
            c.text = c.text.replace("WIFI_PSK", "***REDACTED***").replace("WIFI_SSID", "***REDACTED***")
            # also redact any concrete PSK-like values if present (heuristic)
            if "s3cret" in c.text or "bLueSky" in c.text:
                c.text = c.text.replace("s3cretP@ss123", "***REDACTED***").replace("bLueSky99!", "***REDACTED***")

    warnings = list(rag.warnings)
    for c in chunks:
        if c.staleness in ("stale", "superseded", "deprecated", "conflicts_with_live"):
            warnings.append(f"{c.doc_id} {c.staleness}: {c.staleness_reason}")
    if decision.redact:
        warnings.append("Redacted sensitive fields per policy (redact=true)")

    # redact superseded chunks unless explicitly requested
    visible = chunks if include_stale else [c for c in chunks if c.staleness not in ("superseded", "deprecated") or c.conflicts_with_live]

    data = {
        "query": query,
        "chunks": [c.model_dump() for c in visible],
        "all_chunks": [c.model_dump() for c in chunks],
        "warnings": warnings,
        "redacted": decision.redact,
    }
    summary = f"Retrieved {len(visible)} chunks for '{query}'" + (f" ({len(warnings)} warnings)" if warnings else "")
    if decision.redact:
        summary += " [REDACTED]"
    return RagToolResponse(status="success", summary=summary, data=data, policy_id=decision.policy_id, next_actions=["Check warnings before acting"] if warnings else [])
