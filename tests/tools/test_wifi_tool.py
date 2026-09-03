"""Seam: agent-callable tools — micro-tools with deterministic output shapes per harness skill."""
from src.tools.wifi_tool import get_wifi_credentials_tool

def test_tool_onsite_allow(tmp_db):
    resp = get_wifi_credentials_tool(
        subscriber_id="S123",
        technician_id="T42",
        queue_origin="field_app",
        gps_verified_on_site=True,
        field_checkin_active=True,
        site_id="SITE_A",
        subscriber_site_id="SITE_A",
        db_path=tmp_db,
    )
    assert resp.status == "success"
    assert resp.data["psk"] == "s3cretP@ss123"
    assert resp.policy_id == "wifi-allow-field-onsite"

def test_tool_unauthorized_deny(tmp_db):
    resp = get_wifi_credentials_tool(
        subscriber_id="S123",
        technician_id="T42",
        queue_origin="support_unauthorized",
        gps_verified_on_site=True,
        field_checkin_active=True,
        site_id="SITE_A",
        subscriber_site_id="SITE_A",
        db_path=tmp_db,
    )
    assert resp.status == "error"
    assert "DENIED" in resp.summary
    assert resp.data is None

def test_tool_observation_shape(tmp_db):
    resp = get_wifi_credentials_tool(subscriber_id="S123", queue_origin="support_unauthorized", db_path=tmp_db)
    # Must have harness-required fields
    assert hasattr(resp, "status")
    assert hasattr(resp, "summary")
    assert hasattr(resp, "next_actions")
    assert hasattr(resp, "artifacts")
