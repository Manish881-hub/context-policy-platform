"""Agent-callable tools — micro-tools with stable names, narrow schemas, deterministic output.

Per agent-harness-construction:
- stable explicit name
- schema-first narrow input
- deterministic shape: {status, summary, next_actions, artifacts, data/error}
- error recovery hints + stop condition

These tools are what the LLM actually calls. Policy check lives INSIDE, not in prompt.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from ..context.models import Action, Identity, QueueOrigin, RequestContext, Resource
from ..policy.engine import PolicyEngine
from ..provisioning.adapter import ProvisioningAdapter
from ..provisioning.db import DB_PATH

try:
    from ..observability.audit import audit_log
except Exception:  # pragma: no cover
    def audit_log(*args, **kwargs):  # type: ignore
        pass


class ToolResponse(BaseModel):
    status: str = Field(description="success|warning|error")
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None
    error: str | None = None
    policy_id: str | None = None


# Global singletons for demo — in production inject via DI / GCP
_policy = PolicyEngine()
_adapter = ProvisioningAdapter(db_path=DB_PATH, policy=_policy)


def _build_context(
    technician_id: str | None,
    queue_origin: str,
    subscriber_id: str,
    gps_verified: bool,
    checkin_active: bool,
    site_id: str | None,
    subscriber_site_id: str | None,
    ticket_id: str | None,
    action: Action,
) -> RequestContext:
    return RequestContext(
        identity=Identity(
            technician_id=technician_id,
            queue_origin=QueueOrigin(queue_origin),
        ),
        resource=Resource(subscriber_id=subscriber_id),
        action=action,
        gps_verified_on_site=gps_verified,
        field_checkin_active=checkin_active,
        site_id=site_id,
        subscriber_site_id=subscriber_site_id,
        ticket_id=ticket_id,
    )


def get_wifi_credentials_tool(
    subscriber_id: str,
    technician_id: str | None = None,
    queue_origin: str = "field_app",
    gps_verified_on_site: bool = False,
    field_checkin_active: bool = False,
    site_id: str | None = None,
    subscriber_site_id: str | None = None,
    ticket_id: str | None = None,
    db_path: Path | None = None,
) -> ToolResponse:
    """Micro-tool: get wifi credentials. Policy enforced inside.

    All context args are TRUSTED ingestion (field app, router), not LLM-extracted chat text.
    """
    ctx = _build_context(
        technician_id, queue_origin, subscriber_id,
        gps_verified_on_site, field_checkin_active,
        site_id, subscriber_site_id, ticket_id,
        Action.GET_WIFI_CREDENTIALS,
    )
    # Use injected db_path if test wants isolated DB
    adapter = _adapter if db_path is None else ProvisioningAdapter(db_path=db_path, policy=_policy)
    policy = _policy
    decision = policy.evaluate(ctx)
    # audit tool call (policy already audited, this is tool-layer)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.GET_WIFI_CREDENTIALS.value)
    except Exception:
        pass
    if not decision.allowed:
        return ToolResponse(
            status="error",
            summary=f"DENIED: {decision.reason}",
            next_actions=["Do not retry without changing context — check-in on site or provide ticket"],
            error=decision.reason,
            policy_id=decision.policy_id,
        )
    try:
        # Adapter does second check — even if this tool's check were bypassed, adapter would still deny.
        creds = adapter.get_wifi_credentials(ctx)
        psk = creds.psk
        ssid = creds.ssid
        if decision.redact:
            psk = "***REDACTED***"
            ssid = "***REDACTED***"
        summary = f"Retrieved wifi for {subscriber_id}" + (" [REDACTED]" if decision.redact else "")
        return ToolResponse(
            status="success",
            summary=summary,
            next_actions=[],
            artifacts=[],
            data={"subscriber_id": creds.subscriber_id, "ssid": ssid, "psk": psk, "redacted": decision.redact},
            policy_id=decision.policy_id,
        )
    except PermissionError as e:
        return ToolResponse(status="error", summary=str(e), next_actions=["Verify context and retry"], error=str(e), policy_id=decision.policy_id)
    except Exception as e:
        return ToolResponse(
            status="error",
            summary=f"Legacy system error: {e}",
            next_actions=["Check subscriber_id exists", "Retry once", "Escalate if persists"],
            error=str(e),
        )


def get_line_status_tool(
    subscriber_id: str,
    technician_id: str | None = None,
    queue_origin: str = "field_app",
    gps_verified_on_site: bool = False,
    field_checkin_active: bool = False,
    site_id: str | None = None,
    subscriber_site_id: str | None = None,
    ticket_id: str | None = None,
    db_path: Path | None = None,
) -> ToolResponse:
    ctx = _build_context(
        technician_id, queue_origin, subscriber_id,
        gps_verified, field_checkin_active,
        site_id, subscriber_site_id, ticket_id,
        Action.GET_LINE_STATUS,
    )
    adapter = _adapter if db_path is None else ProvisioningAdapter(db_path=db_path, policy=_policy)
    decision = _policy.evaluate(ctx)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.GET_LINE_STATUS.value)
    except Exception:
        pass
    if not decision.allowed:
        return ToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id)
    try:
        line = adapter.get_line_status(ctx)
        return ToolResponse(
            status="success",
            summary=f"Line {line.status} for {subscriber_id}",
            data={"subscriber_id": line.subscriber_id, "status": line.status, "olt_id": line.olt_id, "ont_serial": line.ont_serial},
            policy_id=decision.policy_id,
        )
    except Exception as e:
        return ToolResponse(status="error", summary=str(e), error=str(e))
