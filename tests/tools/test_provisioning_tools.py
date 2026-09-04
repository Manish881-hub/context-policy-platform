"""Tools 3-5 — policy inside, deterministic shape."""
from src.tools.provisioning_tools import get_subscriber_profile_tool, reset_ont_tool, get_olt_subscribers_tool

def test_profile_tool_allow(tmp_db):
    r = get_subscriber_profile_tool(subscriber_id="S123", technician_id="T42", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, site_id="SITE_A", subscriber_site_id="SITE_A", db_path=tmp_db)
    assert r.status == "success"
    assert r.data["olt_id"] == "OLT-1"

def test_reset_tool_needs_ticket(tmp_db):
    r = reset_ont_tool(subscriber_id="S123", technician_id="T42", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, site_id="SITE_A", subscriber_site_id="SITE_A", db_path=tmp_db)
    assert r.status == "error"
    assert "DENIED" in r.summary
    r2 = reset_ont_tool(subscriber_id="S123", technician_id="T42", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, site_id="SITE_A", subscriber_site_id="SITE_A", ticket_id="TICK-42", db_path=tmp_db)
    assert r2.status == "success"
    assert r2.data["result"] == "RESET_INITIATED"

def test_olt_tool(tmp_db):
    r = get_olt_subscribers_tool(olt_id="OLT-1", technician_id="T42", queue_origin="field_app", gps_verified_on_site=True, field_checkin_active=True, db_path=tmp_db)
    assert r.status == "success"
    assert r.data["count"] == 2
