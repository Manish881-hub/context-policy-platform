"""Provisioning tools 3-5 — same harness shape, policy inside, adapter double-check."""
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


_policy = PolicyEngine()


def _ctx(technician_id, queue_origin, subscriber_id, olt_id, gps, checkin, site_id, subs_site, ticket_id, action) -> RequestContext:
    return RequestContext(
        identity=Identity(technician_id=technician_id, queue_origin=QueueOrigin(queue_origin)),
        resource=Resource(subscriber_id=subscriber_id, olt_id=olt_id),
        action=action,
        gps_verified_on_site=gps,
        field_checkin_active=checkin,
        site_id=site_id,
        subscriber_site_id=subs_site,
        ticket_id=ticket_id,
    )


def _adapter(db_path: Path | None) -> ProvisioningAdapter:
    return ProvisioningAdapter(db_path=db_path or DB_PATH, policy=_policy)


def get_subscriber_profile_tool(
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
    ctx = _ctx(technician_id, queue_origin, subscriber_id, None, gps_verified_on_site, field_checkin_active, site_id, subscriber_site_id, ticket_id, Action.GET_SUBSCRIBER_PROFILE)
    decision = _policy.evaluate(ctx)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.GET_SUBSCRIBER_PROFILE.value)
    except Exception:
        pass
    if not decision.allowed:
        return ToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id)
    try:
        p = _adapter(db_path).get_subscriber_profile(ctx)
        ssid = "***REDACTED***" if decision.redact else p.wifi_ssid
        return ToolResponse(
            status="success",
            summary=f"Profile for {subscriber_id}" + (" [REDACTED]" if decision.redact else ""),
            data={"subscriber_id": p.subscriber_id, "site_code": p.site_code, "ont_serial": p.ont_serial, "wifi_ssid": ssid, "line_status": p.line_status, "olt_id": p.olt_id, "redacted": decision.redact},
            policy_id=decision.policy_id,
        )
    except Exception as e:
        return ToolResponse(status="error", summary=str(e), error=str(e), policy_id=decision.policy_id)


def reset_ont_tool(
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
    ctx = _ctx(technician_id, queue_origin, subscriber_id, None, gps_verified_on_site, field_checkin_active, site_id, subscriber_site_id, ticket_id, Action.RESET_ONT)
    decision = _policy.evaluate(ctx)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.RESET_ONT.value)
    except Exception:
        pass
    if not decision.allowed:
        return ToolResponse(
            status="error",
            summary=f"DENIED: {decision.reason}",
            next_actions=["Provide ticket_id and verify on-site check-in"],
            error=decision.reason,
            policy_id=decision.policy_id,
        )
    try:
        r = _adapter(db_path).reset_ont(ctx)
        return ToolResponse(
            status="success",
            summary=f"ONT {r.ont_serial} reset for {subscriber_id}",
            next_actions=["Verify line status via get_line_status"],
            data={"subscriber_id": r.subscriber_id, "ont_serial": r.ont_serial, "result": r.result},
            policy_id=decision.policy_id,
        )
    except Exception as e:
        return ToolResponse(status="error", summary=str(e), error=str(e), policy_id=decision.policy_id)


def get_olt_subscribers_tool(
    olt_id: str = "OLT-1",
    technician_id: str | None = None,
    queue_origin: str = "field_app",
    gps_verified_on_site: bool = False,
    field_checkin_active: bool = False,
    site_id: str | None = None,
    subscriber_site_id: str | None = None,
    ticket_id: str | None = None,
    subscriber_id: str = "S123",
    db_path: Path | None = None,
) -> ToolResponse:
    ctx = _ctx(technician_id, queue_origin, subscriber_id, olt_id, gps_verified_on_site, field_checkin_active, site_id, subscriber_site_id, ticket_id, Action.GET_OLT_SUBSCRIBERS)
    decision = _policy.evaluate(ctx)
    try:
        audit_log(event="tool_call", policy_id=decision.policy_id, allowed=decision.allowed, reason=decision.reason, technician_id=technician_id, queue_origin=queue_origin, subscriber_id=subscriber_id, action=Action.GET_OLT_SUBSCRIBERS.value, extra={"olt_id": olt_id})
    except Exception:
        pass
    if not decision.allowed:
        return ToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id)
    try:
        o = _adapter(db_path).get_olt_subscribers(ctx)
        return ToolResponse(
            status="success",
            summary=f"OLT {olt_id}: {o.count} subscribers",
            data={"olt_id": o.olt_id, "count": o.count, "subscribers": o.subscribers},
            policy_id=decision.policy_id,
        )
    except Exception as e:
        return ToolResponse(status="error", summary=str(e), error=str(e), policy_id=decision.policy_id)
