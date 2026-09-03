"""Trusted context/identity ingestion — from real systems, not LLM inference.

Sources (mocked for now, wired to real field app + queue router later):
- field app GPS/check-in service
- queue routing metadata
- ticket/subscriber system
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from pydantic import BaseModel, Field


class QueueOrigin(str, Enum):
    FIELD_APP = "field_app"          # technician mobile app, GPS-verified
    SUPPORT_AUTHORIZED = "support_authorized"
    SUPPORT_UNAUTHORIZED = "support_unauthorized"
    SELF_SERVICE = "self_service"


class Action(str, Enum):
    GET_WIFI_CREDENTIALS = "get_wifi_credentials"
    GET_LINE_STATUS = "get_line_status"
    GET_SUBSCRIBER_PROFILE = "get_subscriber_profile"
    RESET_ONT = "reset_ont"


class Resource(BaseModel):
    subscriber_id: str = Field(description="Subscriber whose resource is requested")
    # extensible: add olt_id, ont_serial later


class Identity(BaseModel):
    """Who is asking — ingested from auth, not conversation."""
    technician_id: str | None = None
    user_id: str | None = None  # for self-service
    role: str = "technician"  # technician, support, subscriber
    queue_origin: QueueOrigin


class RequestContext(BaseModel):
    """Context at request time — all from trusted systems."""
    identity: Identity
    resource: Resource
    action: Action
    # Trusted signals — MUST come from systems, not LLM-extracted.
    gps_verified_on_site: bool = False
    field_checkin_active: bool = False
    ticket_id: str | None = None
    site_id: str | None = None  # which site technician claims to be at
    subscriber_site_id: str | None = None  # where subscriber lives (for match)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    # For eval harness: raw channel metadata
    channel_metadata: dict = Field(default_factory=dict)
