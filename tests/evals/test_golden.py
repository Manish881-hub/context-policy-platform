"""Eval harness in CI — per eval-harness skill.

Golden set: (context, query, expected) pairs.
Auth cases must be pass^3 = 100% (all must pass, not average).
A prompt change that flips one auth decision fails build like broken unit test.
"""
import json
from pathlib import Path
import pytest

from src.context.models import Identity, RequestContext, Resource, Action, QueueOrigin
from src.policy.engine import PolicyEngine

GOLDEN_PATH = Path(__file__).parents[2] / "evals" / "golden.jsonl"
engine = PolicyEngine()

def load_golden():
    cases = []
    for line in GOLDEN_PATH.read_text().splitlines():
        if line.strip():
            cases.append(json.loads(line))
    return cases

@pytest.mark.parametrize("case", load_golden(), ids=lambda c: c["id"])
def test_golden_case(case):
    ctx_kwargs = case["context"]
    # Map json context to RequestContext
    identity = Identity(
        technician_id=ctx_kwargs.get("technician_id"),
        queue_origin=QueueOrigin(ctx_kwargs["queue_origin"]),
    )
    resource = Resource(subscriber_id=ctx_kwargs.get("subscriber_id", "S123"), olt_id=ctx_kwargs.get("olt_id"))
    action = Action(case["action"])
    req = RequestContext(
        identity=identity,
        resource=resource,
        action=action,
        gps_verified_on_site=ctx_kwargs.get("gps_verified_on_site", False),
        field_checkin_active=ctx_kwargs.get("field_checkin_active", False),
        site_id=ctx_kwargs.get("site_id"),
        subscriber_site_id=ctx_kwargs.get("subscriber_site_id"),
        ticket_id=ctx_kwargs.get("ticket_id"),
    )
    decision = engine.evaluate(req)
    expected_allow = case["expected"] == "allow"
    assert decision.allowed is expected_allow, f"Case {case['id']}: expected {case['expected']} but got {'allow' if decision.allowed else 'deny'} ({decision.reason}) [{decision.policy_id}]"

def test_auth_golden_100_percent_required():
    """Meta-test: ensures harness itself is strict — no partial credit for auth."""
    cases = load_golden()
    # Count how many are auth-sensitive (wifi)
    wifi_cases = [c for c in cases if c["action"] == "get_wifi_credentials"]
    assert len(wifi_cases) >= 2, "Need at least allow+deny wifi cases"
    # Run all and collect — this test documents the CI gate requirement
    failures = []
    for c in wifi_cases:
        identity = Identity(technician_id=c["context"].get("technician_id"), queue_origin=QueueOrigin(c["context"]["queue_origin"]))
        req = RequestContext(
            identity=identity,
            resource=Resource(subscriber_id=c["context"]["subscriber_id"]),
            action=Action(c["action"]),
            gps_verified_on_site=c["context"].get("gps_verified_on_site", False),
            field_checkin_active=c["context"].get("field_checkin_active", False),
            site_id=c["context"].get("site_id"),
            subscriber_site_id=c["context"].get("subscriber_site_id"),
            ticket_id=c["context"].get("ticket_id"),
        )
        d = engine.evaluate(req)
        if (d.allowed != (c["expected"] == "allow")):
            failures.append(c["id"])
    assert not failures, f"Auth golden 100% gate failed for: {failures} — build must fail"
