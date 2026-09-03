"""Metrics — for Cloud Monitoring / Prometheus.

Every policy decision, staleness warning, guardrail block is a metric, not just a log.
On GCP: expose /metrics for Cloud Monitoring to scrape, or push to Cloud Monitoring API.
"""
from __future__ import annotations

from collections import Counter
from typing import Dict

_counters: Counter = Counter()
# In prod, use prometheus_client.Counter or OpenTelemetry

def inc(metric: str, labels: Dict[str, str] | None = None, value: int = 1) -> None:
    key = metric
    if labels:
        key += "{" + ",".join(f'{k}="{v}"' for k, v in sorted(labels.items())) + "}"
    _counters[key] += value

def get_metrics() -> dict[str, int]:
    return dict(_counters)

def reset() -> None:
    _counters.clear()

# Convenience helpers
def record_policy(policy_id: str, allowed: bool) -> None:
    inc("policy_decisions_total", {"policy_id": policy_id, "allowed": str(allowed).lower()})

def record_staleness(staleness: str) -> None:
    inc("rag_staleness_total", {"staleness": staleness})

def record_guardrail(blocked: bool) -> None:
    inc("sql_guardrail_total", {"blocked": str(blocked).lower()})
