"""Text-to-SQL tool — policy-guarded + guardrails double-check.

Flow (every call):
 1. policy.evaluate(ctx) — per-tool-call
 2. generator.generate(nl) -> sql
 3. guardrails.validate_sql(sql) — only SELECT, deny DROP etc, LIMIT 100
 4. execute_readonly(sql) on read-only connection if allowed
"""
from __future__ import annotations

from pathlib import Path
from pydantic import BaseModel, Field
from typing import Any

from ..context.models import Action, Identity, QueueOrigin, RequestContext, Resource
from ..policy.engine import PolicyEngine
from ..provisioning.db import DB_PATH
from ..sql.generator import SqlGenerator
from ..sql.guardrails import validate_sql, execute_readonly, ensure_limit

class SqlToolResponse(BaseModel):
    status: str
    summary: str
    next_actions: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    data: dict[str, Any] | None = None
    error: str | None = None
    policy_id: str | None = None

_policy = PolicyEngine()

def query_sql_tool(
    nl_query: str,
    technician_id: str | None = None,
    queue_origin: str = "field_app",
    gps_verified_on_site: bool = False,
    field_checkin_active: bool = False,
    site_id: str | None = None,
    subscriber_site_id: str | None = None,
    ticket_id: str | None = None,
    subscriber_id: str | None = None,
    db_path: Path | None = None,
    dry_run: bool = False,
) -> SqlToolResponse:
    # subscriber_id may be inside nl_query; fallback to Resource dummy
    res_sub = subscriber_id or "S123"
    ctx = RequestContext(
        identity=Identity(technician_id=technician_id, queue_origin=QueueOrigin(queue_origin)),
        resource=Resource(subscriber_id=res_sub),
        action=Action.QUERY_SQL,
        gps_verified_on_site=gps_verified_on_site,
        field_checkin_active=field_checkin_active,
        site_id=site_id,
        subscriber_site_id=subscriber_site_id,
        ticket_id=ticket_id,
    )
    decision = _policy.evaluate(ctx)
    if not decision.allowed:
        return SqlToolResponse(status="error", summary=f"DENIED: {decision.reason}", error=decision.reason, policy_id=decision.policy_id)

    gen = SqlGenerator(db_path=db_path or DB_PATH)
    gen_res = gen.generate(nl_query, subscriber_id=subscriber_id)
    if gen_res["status"] != "success":
        return SqlToolResponse(status="error", summary=gen_res["error"], error=gen_res["error"], policy_id=decision.policy_id, next_actions=["Rephrase query", "Include subscriber_id"])

    sql = gen_res["sql"]
    ok, reason = validate_sql(sql)
    if not ok:
        return SqlToolResponse(status="error", summary=f"Guardrail blocked: {reason}", error=reason, policy_id=decision.policy_id)

    if dry_run:
        return SqlToolResponse(status="success", summary=f"Dry-run ok: {sql}", data={"sql": sql, "dry_run": True}, policy_id=decision.policy_id)

    exec_res = execute_readonly(sql, db_path=db_path or DB_PATH)
    if exec_res["status"] != "success":
        return SqlToolResponse(status="error", summary=f"Execution failed: {exec_res['error']}", error=exec_res["error"], policy_id=decision.policy_id)

    return SqlToolResponse(status="success", summary=f"Executed: {sql} -> {len(exec_res['rows'])} rows", data={"sql": sql, "columns": exec_res["columns"], "rows": exec_res["rows"], "truncated": exec_res.get("truncated", False)}, policy_id=decision.policy_id)
