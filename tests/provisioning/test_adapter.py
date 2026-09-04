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

def _ctx5(queue, gps=True, checkin=True, ticket="TICK-1", action=Action.GET_SUBSCRIBER_PROFILE, olt=None):
    from src.context.models import Resource
    return RequestContext(
        identity=Identity(technician_id="T42", queue_origin=queue),
        resource=Resource(subscriber_id="S123", olt_id=olt),
        action=action,
        gps_verified_on_site=gps,
        field_checkin_active=checkin,
        site_id="SITE_A",
        subscriber_site_id="SITE_A",
        ticket_id=ticket,
    )

def test_profile_allows_onsite(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = _ctx5(QueueOrigin.FIELD_APP, action=Action.GET_SUBSCRIBER_PROFILE)
    p = adapter.get_subscriber_profile(ctx)
    assert p.subscriber_id == "S123"
    assert p.olt_id == "OLT-1"
    assert "HomeWiFi" in p.wifi_ssid

def test_profile_denies_unauthorized(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = _ctx5(QueueOrigin.SUPPORT_UNAUTHORIZED, action=Action.GET_SUBSCRIBER_PROFILE)
    try:
        adapter.get_subscriber_profile(ctx)
        assert False
    except PermissionError as e:
        assert "DENIED" in str(e)

def test_reset_requires_ticket(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx_no_ticket = _ctx5(QueueOrigin.FIELD_APP, ticket=None, action=Action.RESET_ONT)
    try:
        adapter.reset_ont(ctx_no_ticket)
        assert False
    except PermissionError as e:
        assert "ticket" in str(e).lower()
    ctx_ok = _ctx5(QueueOrigin.FIELD_APP, ticket="TICK-42", action=Action.RESET_ONT)
    r = adapter.reset_ont(ctx_ok)
    assert r.result == "RESET_INITIATED"
    assert r.ont_serial == "ONT-001"

def test_reset_denies_unauthorized(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = _ctx5(QueueOrigin.SUPPORT_UNAUTHORIZED, action=Action.RESET_ONT)
    try:
        adapter.reset_ont(ctx)
        assert False
    except PermissionError:
        pass

def test_olt_subscribers(tmp_db):
    adapter = ProvisioningAdapter(db_path=tmp_db, policy=PolicyEngine())
    ctx = _ctx5(QueueOrigin.FIELD_APP, action=Action.GET_OLT_SUBSCRIBERS, olt="OLT-1")
    o = adapter.get_olt_subscribers(ctx)
    assert o.olt_id == "OLT-1"
    assert o.count == 2
    assert any(s["subscriber_id"] == "S123" for s in o.subscribers)
