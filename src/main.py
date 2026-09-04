"""Cloud Run entry — FastAPI over same policy-guarded tools.

ECC fastapi-patterns (thin routes, service layer in tools/*) +
security-review (401 identity vs 403 policy, secrets in env):
- X-Field-Token / X-Queue-Token headers verified when present (401 on tamper).
- Body fields kept for CI/backward compat; verified tokens override them via builder.
Same guarantee: policy.evaluate() inside every tool, adapter double-check.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Header
from pydantic import BaseModel

from .context.auth_deps import get_field_token_claims, get_queue_claims

from .context.models import Action, Identity, QueueOrigin, RequestContext, Resource
from .policy.engine import PolicyEngine
from .tools.wifi_tool import get_wifi_credentials_tool, get_line_status_tool
from .tools.provisioning_tools import get_subscriber_profile_tool, reset_ont_tool, get_olt_subscribers_tool
from .tools.rag_tool import query_docs_tool
from .tools.sql_tool import query_sql_tool
from .provisioning.db import DB_PATH, init_db

app = FastAPI(title="ISP Context-Aware Policy Platform", version="0.1.0")
_policy = PolicyEngine()

# Ensure SQLite exists on container start (for demo; prod would use Cloud SQL via DB_PATH env)
try:
    if not DB_PATH.exists():
        init_db()
except Exception:
    pass

# Allow Cloud SQL override via env (e.g. /cloudsql/... or GCS mount)
DB_PATH_ENV = os.getenv("PROVISIONING_DB_PATH")
_effective_db = Path(DB_PATH_ENV) if DB_PATH_ENV else DB_PATH

class WifiRequest(BaseModel):
    subscriber_id: str
    technician_id: str | None = None
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None

class RagRequest(BaseModel):
    query: str
    subscriber_id: str = "S123"
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None

class SqlRequest(BaseModel):
    nl_query: str
    subscriber_id: str | None = None
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None


class ProfileRequest(BaseModel):
    subscriber_id: str
    technician_id: str | None = None
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None


class ResetRequest(BaseModel):
    subscriber_id: str
    technician_id: str | None = None
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None


class OltRequest(BaseModel):
    olt_id: str = "OLT-1"
    subscriber_id: str = "S123"
    technician_id: str | None = None
    queue_origin: str = "field_app"
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    site_id: str | None = None
    subscriber_site_id: str | None = None
    ticket_id: str | None = None

@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": "0.1.0", "policy": "per-tool-call", "db": str(_effective_db)}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    from .observability.metrics import get_metrics

    return {"metrics": get_metrics()}

def _trusted_overrides(
    req_technician: str | None,
    req_queue: str,
    req_gps: bool,
    req_checkin: bool,
    req_site: str | None,
    req_subs_site: str | None,
    req_ticket: str | None,
    subscriber_id: str,
    action,
    field_claims: dict | None,
    queue_claims: dict | None,
    raw_field_token: str | None = None,
    raw_queue_token: str | None = None,
) -> dict:
    """If signed tokens present, derive trusted context via builder (not body).

    Body values are CI/backward-compat only. Verified JWT claims override them.
    """
    if not raw_field_token and not raw_queue_token:
        return {
            "technician_id": req_technician,
            "queue_origin": req_queue,
            "gps_verified_on_site": req_gps,
            "field_checkin_active": req_checkin,
            "site_id": req_site,
            "subscriber_site_id": req_subs_site,
            "ticket_id": req_ticket,
        }
    from .context.builder import build_context

    ctx = build_context(
        technician_id=(field_claims or {}).get("technician_id", req_technician) if field_claims else req_technician,
        subscriber_id=subscriber_id,
        action=action,
        ticket_id=(queue_claims or {}).get("ticket_id", req_ticket) if queue_claims else req_ticket,
        channel=req_queue,
        db_path=_effective_db,
        field_token=raw_field_token,
        queue_token=raw_queue_token,
    )
    return {
        "technician_id": ctx.identity.technician_id,
        "queue_origin": ctx.identity.queue_origin.value,
        "gps_verified_on_site": ctx.gps_verified_on_site,
        "field_checkin_active": ctx.field_checkin_active,
        "site_id": ctx.site_id,
        "subscriber_site_id": ctx.subscriber_site_id,
        "ticket_id": ctx.ticket_id,
    }


@app.post("/tool/wifi")
def tool_wifi(
    req: WifiRequest,
    field_claims: dict | None = Depends(get_field_token_claims),
    queue_claims: dict | None = Depends(get_queue_claims),
    x_field_token: str | None = Header(default=None, alias="X-Field-Token"),
    x_queue_token: str | None = Header(default=None, alias="X-Queue-Token"),
) -> dict[str, Any]:
    from .context.models import Action as _Action

    t = _trusted_overrides(
        req.technician_id, req.queue_origin, req.gps_verified_on_site, req.field_checkin_active,
        req.site_id, req.subscriber_site_id, req.ticket_id, req.subscriber_id, _Action.GET_WIFI_CREDENTIALS,
        field_claims, queue_claims, x_field_token, x_queue_token,
    )
    resp = get_wifi_credentials_tool(subscriber_id=req.subscriber_id, db_path=_effective_db, **t)
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()

@app.post("/tool/line-status")
def tool_line(req: WifiRequest) -> dict[str, Any]:
    resp = get_line_status_tool(
        subscriber_id=req.subscriber_id,
        technician_id=req.technician_id,
        queue_origin=req.queue_origin,
        gps_verified_on_site=req.gps_verified_on_site,
        field_checkin_active=req.field_checkin_active,
        site_id=req.site_id,
        subscriber_site_id=req.subscriber_site_id,
        ticket_id=req.ticket_id,
        db_path=_effective_db,
    )
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()

@app.post("/tool/profile")
def tool_profile(req: ProfileRequest) -> dict[str, Any]:
    resp = get_subscriber_profile_tool(**req.model_dump(), db_path=_effective_db)
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()


@app.post("/tool/reset-ont")
def tool_reset(req: ResetRequest) -> dict[str, Any]:
    resp = reset_ont_tool(**req.model_dump(), db_path=_effective_db)
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()


@app.post("/tool/olt-subscribers")
def tool_olt(req: OltRequest) -> dict[str, Any]:
    resp = get_olt_subscribers_tool(**req.model_dump(), db_path=_effective_db)
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()


@app.post("/tool/docs")
def tool_docs(req: RagRequest) -> dict[str, Any]:
    resp = query_docs_tool(
        query=req.query,
        queue_origin=req.queue_origin,
        gps_verified_on_site=req.gps_verified_on_site,
        field_checkin_active=req.field_checkin_active,
        site_id=req.site_id,
        subscriber_site_id=req.subscriber_site_id,
        ticket_id=req.ticket_id,
        subscriber_id=req.subscriber_id,
        db_path=_effective_db,
    )
    if resp.status == "error":
        raise HTTPException(status_code=403 if "DENIED" in resp.summary else 400, detail=resp.model_dump())
    return resp.model_dump()

@app.post("/tool/sql")
def tool_sql(req: SqlRequest) -> dict[str, Any]:
    resp = query_sql_tool(
        nl_query=req.nl_query,
        queue_origin=req.queue_origin,
        gps_verified_on_site=req.gps_verified_on_site,
        field_checkin_active=req.field_checkin_active,
        site_id=req.site_id,
        subscriber_site_id=req.subscriber_site_id,
        ticket_id=req.ticket_id,
        subscriber_id=req.subscriber_id,
        db_path=_effective_db,
    )
    if resp.status == "error":
        # 403 for policy deny, 400 for guardrail
        code = 403 if "DENIED" in (resp.summary or "") else 400
        raise HTTPException(status_code=code, detail=resp.model_dump())
    return resp.model_dump()

# Local: uvicorn src.main:app --reload --port 8080
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
