"""Seam: ProvisioningAdapter public fns — not wrapper internals."""
from src.context.models import Identity, RequestContext, Resource, Action, QueueOrigin
from src.provisioning.adapter import ProvisioningAdapter
from src.policy.engine import PolicyEngine

def make_ctx(queue, gps, checkin, site="SITE_A", subs_site="SITE_A", ticket=None, action=Action.GET_WIFI_CREDENTIALS):
    return RequestContext(
        identity=Identity(technician_id="T42", queue_origin=queue),
        resource=Resource(subscriber_id="S123"),
        action=action,
        gps_verified_on_site=gps,
        field_checkin_active=checkin,
        site_id=site,
        subscriber_site_id=subs_site,
        ticket_id=ticket,
    )

def test_adapter_allows_onsite(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = make_ctx(QueueOrigin.FIELD_APP, gps=True, checkin=True)
    creds = adapter.get_wifi_credentials(ctx)
    assert creds.ssid == "HomeWiFi-A"
    assert creds.psk == "s3cretP@ss123"

def test_adapter_denies_unauthorized(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = make_ctx(QueueOrigin.SUPPORT_UNAUTHORIZED, gps=True, checkin=True)
    try:
        adapter.get_wifi_credentials(ctx)
        assert False, "should have raised PermissionError"
    except PermissionError as e:
        assert "DENIED" in str(e)

def test_adapter_double_check_cannot_be_bypassed(tmp_db):
    # Even if caller somehow flips policy once, adapter re-checks
    # Simulate by passing a ctx that would be denied — both checks must fail consistently
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = make_ctx(QueueOrigin.FIELD_APP, gps=False, checkin=True)
    try:
        adapter.get_wifi_credentials(ctx)
        assert False
    except PermissionError:
        pass

def test_line_status(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db)
    ctx = make_ctx(QueueOrigin.FIELD_APP, gps=True, checkin=True, action=Action.GET_LINE_STATUS)
    line = adapter.get_line_status(ctx)
    assert line.status in ("UP", "DOWN")
