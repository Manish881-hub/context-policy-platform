"""Context builder — assembles RequestContext from trusted systems, not conversation.

This is the seam the agent must call. It takes technician_id + subscriber_id + ticket_id + channel
and pulls verified signals from field_app_client + queue_router + subscriber DB.
LLM never decides queue_origin or gps_verified — those are looked up.
"""
from __future__ import annotations

from pathlib import Path

from ..provisioning.db import get_connection, run
from .field_app_client import get_field_checkin, verify_gps
from .queue_router import get_queue_origin, verify_queue_header
from .models import Identity, RequestContext, Resource, Action, QueueOrigin

def build_context(
    technician_id: str | None,
    subscriber_id: str,
    action: Action,
    ticket_id: str | None = None,
    channel: str | None = None,
    db_path: Path | None = None,
    field_token: str | None = None,
    queue_token: str | None = None,
) -> RequestContext:
    # 1. Queue origin from routing system (not LLM). Signed token wins over hints.
    queue_origin = get_queue_origin(ticket_id, channel)
    if queue_token:
        claims = verify_queue_header(queue_token)
        if claims and claims.get("queue_origin"):
            queue_origin = claims["queue_origin"]
            if claims.get("ticket_id"):
                ticket_id = claims["ticket_id"]
        else:
            # Tampered/invalid signed header -> fail closed
            queue_origin = "support_unauthorized"

    # 2. Field check-in: signed JWT wins over mock store when provided.
    # ECC security-review fail closed: invalid token -> NO fallback to mock.
    checkin = None
    field_token_invalid = False
    if field_token:
        try:
            from .field_app_client import get_checkin_from_token

            checkin = get_checkin_from_token(field_token)
        except Exception:
            checkin = None
        if checkin is None:
            field_token_invalid = True
    if checkin is None and not field_token_invalid:
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
        cur = run(conn, "SELECT SITE_CD FROM SUBS_TBL WHERE SUBS_ID=?", (subscriber_id,))
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
