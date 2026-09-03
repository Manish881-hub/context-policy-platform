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
    if not decision.allowed:
        return RagToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id, next_actions=["Verify queue and retry"])

    rag = _store.search(query, top_k=3, include_stale=include_stale)
    chunks = check_conflicts(rag.chunks, subscriber_id=subscriber_id, db_path=db_path or DB_PATH)

    warnings = list(rag.warnings)
    for c in chunks:
        if c.staleness in ("superseded", "deprecated", "conflicts_with_live"):
            warnings.append(f"{c.doc_id} {c.staleness}: {c.staleness_reason}")

    # redact superseded chunks unless explicitly requested
    visible = chunks if include_stale else [c for c in chunks if c.staleness not in ("superseded", "deprecated") or c.conflicts_with_live]

    data = {
        "query": query,
        "chunks": [c.model_dump() for c in visible],
        "all_chunks": [c.model_dump() for c in chunks],
        "warnings": warnings,
    }
    summary = f"Retrieved {len(visible)} chunks for '{query}'" + (f" ({len(warnings)} warnings)" if warnings else "")
    return RagToolResponse(status="success", summary=summary, data=data, policy_id=decision.policy_id, next_actions=["Check warnings before acting"] if warnings else [])
