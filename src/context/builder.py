"""Context builder — assembles RequestContext from trusted systems, not conversation.

This is the seam the agent must call. It takes technician_id + subscriber_id + ticket_id + channel
and pulls verified signals from field_app_client + queue_router + subscriber DB.
LLM never decides queue_origin or gps_verified — those are looked up.
"""
from __future__ import annotations

from pathlib import Path

from ..provisioning.db import get_connection
from .field_app_client import get_field_checkin, verify_gps
from .queue_router import get_queue_origin
from .models import Identity, RequestContext, Resource, Action, QueueOrigin

def build_context(
    technician_id: str | None,
    subscriber_id: str,
    action: Action,
    ticket_id: str | None = None,
    channel: str | None = None,
    db_path: Path | None = None,
) -> RequestContext:
    # 1. Queue origin from routing system (not LLM)
    queue_origin = get_queue_origin(ticket_id, channel)

    # 2. Field check-in from field app service
    checkin = get_field_checkin(technician_id or "") if technician_id else None
    gps_verified = False
    field_active = False
    site_id = None
    if checkin:
        gps_verified = checkin.gps_verified_on_site
        field_active = checkin.field_checkin_active
        site_id = checkin.site_id

    # 3. Subscriber site from provisioning DB (authoritative)
    subscriber_site_id = None
    try:
        conn = get_connection(db_path)
        cur = conn.execute("SELECT SITE_CD FROM SUBS_TBL WHERE SUBS_ID=?", (subscriber_id,))
        row = cur.fetchone()
        conn.close()
        if row:
            subscriber_site_id = row["SITE_CD"]
    except Exception:
        pass

    # 4. GPS geofence re-check (if both sites known)
    if site_id and subscriber_site_id:
        gps_verified = verify_gps(site_id, subscriber_site_id) and gps_verified

    return RequestContext(
        identity=Identity(technician_id=technician_id, queue_origin=QueueOrigin(queue_origin)),
        resource=Resource(subscriber_id=subscriber_id),
        action=action,
        gps_verified_on_site=gps_verified,
        field_checkin_active=field_active,
        site_id=site_id,
        subscriber_site_id=subscriber_site_id,
        ticket_id=ticket_id,
    )
