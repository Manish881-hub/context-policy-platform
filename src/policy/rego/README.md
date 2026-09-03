# OPA/Rego Spike — same policy, declarative

`policy.rego` mirrors `src/policy/engine.py` Python predicate.
Swap via same interface: `policy.evaluate(ctx)` could call `opa eval -d policy.rego` or use `opa-python` instead of Python predicate.

**Why Rego:** audit, git history, and non-engineers can review allow/deny rules.

**Try:**
```bash
# install OPA: https://www.openpolicyagent.org/docs/latest/#running-opa
opa eval -d src/policy/rego/policy.rego -i input.json "data.isp.policy.allow"
# input.json = {"identity":{"queue_origin":"field_app","technician_id":"T42"},"resource":{"subscriber_id":"S123"},"action":"get_wifi_credentials","gps_verified_on_site":true,"field_checkin_active":true,"site_id":"SITE_A","subscriber_site_id":"SITE_A"}
```

Current spike keeps Python as primary (no sidecar latency); Rego is proof we can migrate without changing `evaluate()` call sites.
