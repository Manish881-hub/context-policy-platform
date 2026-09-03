"""TDD seam: PolicyEngine.evaluate — public boundary.

Tests at pre-agreed seam per Matt TDD skill. No internal mocking.
"""
from src.context.models import Identity, RequestContext, Resource, Action, QueueOrigin
from src.policy.engine import PolicyEngine

engine = PolicyEngine()

def ctx(queue, gps=False, checkin=False, site="SITE_A", subs_site="SITE_A", ticket=None, action=Action.GET_WIFI_CREDENTIALS):
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

def test_onsite_field_tech_allowed():
    c = ctx(QueueOrigin.FIELD_APP, gps=True, checkin=True)
    d = engine.evaluate(c)
    assert d.allowed is True
    assert d.policy_id == "wifi-allow-field-onsite"

def test_unauthorized_queue_denied_even_if_same_tech():
    # Same tech T42, same subscriber, but different queue — must deny
    c = ctx(QueueOrigin.SUPPORT_UNAUTHORIZED, gps=True, checkin=True)
    d = engine.evaluate(c)
    assert d.allowed is False
    assert "SUPPORT_UNAUTHORIZED" in d.reason or "unauthorized" in d.reason.lower()

def test_field_app_no_gps_denied():
    c = ctx(QueueOrigin.FIELD_APP, gps=False, checkin=True)
    assert engine.evaluate(c).allowed is False

def test_field_app_no_checkin_denied():
    c = ctx(QueueOrigin.FIELD_APP, gps=True, checkin=False)
    assert engine.evaluate(c).allowed is False

def test_site_mismatch_denied():
    c = ctx(QueueOrigin.FIELD_APP, gps=True, checkin=True, site="SITE_A", subs_site="SITE_B")
    assert engine.evaluate(c).allowed is False

def test_authorized_support_with_ticket_allowed():
    c = ctx(QueueOrigin.SUPPORT_AUTHORIZED, ticket="TICK-1")
    assert engine.evaluate(c).allowed is True

def test_authorized_support_without_ticket_denied():
    c = ctx(QueueOrigin.SUPPORT_AUTHORIZED, ticket=None)
    assert engine.evaluate(c).allowed is False

def test_line_status_unauthorized_denied():
    c = ctx(QueueOrigin.SUPPORT_UNAUTHORIZED, action=Action.GET_LINE_STATUS)
    assert engine.evaluate(c).allowed is False

def test_line_status_field_allowed():
    c = ctx(QueueOrigin.FIELD_APP, gps=True, checkin=True, action=Action.GET_LINE_STATUS)
    assert engine.evaluate(c).allowed is True
