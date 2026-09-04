"""OPA enforcement — ECC safety-guard (deny by default, explicit allow).

Tries `opa eval` binary when OPA_ENABLED=1, else falls back to Python predicate.
Same input/output as PolicyEngine.evaluate() so call sites don't change.
No billing, no sidecar required in CI — parity is tested, enforcement is opt-in.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

REGO_PATH = Path(__file__).parent / "rego" / "policy.rego"


def _ctx_to_input(ctx) -> dict:  # RequestContext -> OPA input
    return {
        "action": ctx.action.value,
        "identity": {"technician_id": ctx.identity.technician_id, "queue_origin": ctx.identity.queue_origin.value},
        "resource": {"subscriber_id": ctx.resource.subscriber_id, "olt_id": ctx.resource.olt_id},
        "gps_verified_on_site": ctx.gps_verified_on_site,
        "field_checkin_active": ctx.field_checkin_active,
        "site_id": ctx.site_id,
        "subscriber_site_id": ctx.subscriber_site_id,
        "ticket_id": ctx.ticket_id,
    }


def opa_available() -> bool:
    if os.getenv("OPA_ENABLED") != "1":
        return False
    return shutil.which("opa") is not None and REGO_PATH.exists()


def evaluate_via_opa(ctx, timeout_s: float = 2.0):
    """Returns Decision or None if OPA not available/failed (caller falls back).

    ECC safety-guard: any OPA error -> deny (fail closed), never allow.
    """
    from .models import Decision

    if not opa_available():
        return None
    try:
        inp = _ctx_to_input(ctx)
        proc = subprocess.run(
            ["opa", "eval", "-d", str(REGO_PATH), "--input", "/dev/stdin", "--format", "json",
             "data.isp.policy.allow", "data.isp.policy.redact", "data.isp.policy.policy_id"],
            input=json.dumps(inp).encode(),
            capture_output=True,
            timeout=timeout_s,
        )
        if proc.returncode != 0:
            return Decision(allowed=False, reason=f"OPA error: {proc.stderr.decode()[:200]}", policy_id="opa-error-deny")
        data = json.loads(proc.stdout.decode())
        rs = data.get("result", [])
        if not rs:
            return Decision(allowed=False, reason="OPA empty result", policy_id="opa-empty-deny")
        exprs = rs[0].get("expressions", [])
        allow = bool(exprs[0].get("value")) if len(exprs) > 0 else False
        redact = bool(exprs[1].get("value")) if len(exprs) > 1 else False
        pid = exprs[2].get("value") if len(exprs) > 2 else "opa-decision"
        return Decision(allowed=allow, reason=f"OPA decision ({pid})", policy_id=str(pid), redact=redact)
    except Exception as e:
        return Decision(allowed=False, reason=f"OPA exception (fail closed): {e}", policy_id="opa-exception-deny")
