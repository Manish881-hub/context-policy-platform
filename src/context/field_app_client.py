"""Field app GPS/check-in ingestion — trusted signal, not LLM inference.

ECC security-review + fastapi-patterns: signed JWT (HS256, env secret, expiry),
haversine geofence vs site coords, fail closed. Mock store kept for CI.
"""
from __future__ import annotations

import math
import os
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
    """Legacy site-code match (kept for backward compat)."""
    return site_id == subscriber_site_id


# Production geofence: site coords (Bhubaneswar area demo) + 500m radius.
SITE_COORDS: dict[str, tuple[float, float]] = {
    "SITE_A": (20.2961, 85.8245),
    "SITE_B": (20.3010, 85.8300),
    "SITE_X": (20.3100, 85.8400),
}
GEOFENCE_RADIUS_M = float(os.getenv("GEOFENCE_RADIUS_M", "500"))


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def verify_gps_coords(lat: float, lon: float, site_id: str) -> bool:
    """True if (lat,lon) within GEOFENCE_RADIUS_M of site center."""
    center = SITE_COORDS.get(site_id)
    if not center:
        return False
    try:
        return haversine_m(lat, lon, center[0], center[1]) <= GEOFENCE_RADIUS_M
    except Exception:
        return False


def get_checkin_from_token(field_token: str | None) -> FieldCheckIn | None:
    """Verify signed field JWT -> FieldCheckIn. Returns None on any failure (fail closed)."""
    if not field_token:
        return None
    try:
        from .tokens import verify_field_token

        claims = verify_field_token(field_token)
        tech = str(claims.get("technician_id", ""))
        site = str(claims.get("site_id", ""))
        lat = float(claims.get("lat", 0.0))
        lon = float(claims.get("lon", 0.0))
        if not tech or not site:
            return None
        gps_ok = verify_gps_coords(lat, lon, site)
        now = datetime.now(timezone.utc)
        return FieldCheckIn(
            technician_id=tech,
            site_id=site,
            gps_verified_on_site=gps_ok,
            field_checkin_active=gps_ok,  # active only if inside fence
            checked_in_at=now,
            expires_at=datetime.fromtimestamp(float(claims.get("exp", 0)), tz=timezone.utc),
            verified_by="field_jwt",
        )
    except Exception:
        return None
