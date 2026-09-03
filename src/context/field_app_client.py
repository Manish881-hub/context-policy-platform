"""Field app GPS/check-in ingestion — trusted signal, not LLM inference.

In prod: field app (Android/iOS) posts GPS + site check-in to Cloud Run/Cloud Functions,
which verifies via: (1) signed JWT with technician_id + site_id + timestamp, (2) GPS fence check
against subscriber SITE_CD geofence, (3) active session lookup in Firestore/Cloud SQL.

If agent decided authorization from what user *says* (\"I'm at SITE_A\"), a bad actor spoofs it.
This module shows the correct ingestion path: context comes from systems, not conversation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pydantic import BaseModel

class FieldCheckIn(BaseModel):
    technician_id: str
    site_id: str
    gps_verified_on_site: bool
    field_checkin_active: bool
    checked_in_at: datetime
    expires_at: datetime
    verified_by: str = "field_app_service"  # which system vouched

# In-memory mock store — prod would query Firestore
_MOCK_CHECKINS: dict[str, FieldCheckIn] = {
    "T42": FieldCheckIn(
        technician_id="T42",
        site_id="SITE_A",
        gps_verified_on_site=True,
        field_checkin_active=True,
        checked_in_at=datetime.now(timezone.utc) - timedelta(minutes=10),
        expires_at=datetime.now(timezone.utc) + timedelta(hours=2),
    ),
    "T99-expired": FieldCheckIn(
        technician_id="T99",
        site_id="SITE_B",
        gps_verified_on_site=False,
        field_checkin_active=False,
        checked_in_at=datetime.now(timezone.utc) - timedelta(hours=5),
        expires_at=datetime.now(timezone.utc) - timedelta(hours=1),
    ),
}

def get_field_checkin(technician_id: str) -> FieldCheckIn | None:
    """Fetch verified check-in — returns None if no active session or expired."""
    ci = _MOCK_CHECKINS.get(technician_id)
    if not ci:
        return None
    if datetime.now(timezone.utc) > ci.expires_at:
        return None
    return ci

def verify_gps(site_id: str, subscriber_site_id: str) -> bool:
    """Geofence check — in prod, compare GPS coords against site polygon via Maps API."""
    return site_id == subscriber_site_id
