"""Seam: build_context — trusted ingestion, not LLM inference."""
from pathlib import Path
import tempfile
from src.provisioning.db import init_db
from src.context.builder import build_context
from src.context.models import Action
from src.policy.engine import PolicyEngine

def test_builder_allows_verified_field_app(tmp_db):
    ctx = build_context(technician_id="T42", subscriber_id="S123", action=Action.GET_WIFI_CREDENTIALS, channel="field_app", db_path=tmp_db)
    assert ctx.gps_verified_on_site is True
    assert ctx.field_checkin_active is True
    assert PolicyEngine().evaluate(ctx).allowed is True

def test_builder_denies_spoofed_queue():
    tmp = Path(tempfile.mktemp(suffix=".db"))
    init_db(tmp)
    # ticket says support_unauthorized, even if channel says field_app, router wins -> deny
    ctx = build_context(technician_id="T42", subscriber_id="S123", action=Action.GET_WIFI_CREDENTIALS, ticket_id="TICK-999", channel="field_app", db_path=tmp)
    assert ctx.identity.queue_origin.value == "support_unauthorized"
    assert PolicyEngine().evaluate(ctx).allowed is False

def test_builder_expired_checkin_denied():
    tmp = Path(tempfile.mktemp(suffix=".db"))
    init_db(tmp)
    ctx = build_context(technician_id="T99-expired", subscriber_id="S123", action=Action.GET_WIFI_CREDENTIALS, channel="field_app", db_path=tmp)
    assert ctx.field_checkin_active is False or ctx.gps_verified_on_site is False
