"""Cloud Run entry — FastAPI over same policy-guarded tools.

Same guarantee as local: policy.evaluate() inside every tool, adapter double-check.
This is just an HTTP wrapper for GCP — no new auth logic here.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel

from .context.models import Action, Identity, QueueOrigin, RequestContext, Resource
from .policy.engine import PolicyEngine
from .tools.wifi_tool import get_wifi_credentials_tool, get_line_status_tool
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

@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "version": "0.1.0", "policy": "per-tool-call", "db": str(_effective_db)}


@app.get("/metrics")
def metrics() -> dict[str, Any]:
    from .observability.metrics import get_metrics

    return {"metrics": get_metrics()}

@app.post("/tool/wifi")
def tool_wifi(req: WifiRequest) -> dict[str, Any]:
    resp = get_wifi_credentials_tool(
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
