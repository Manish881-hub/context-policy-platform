"""Policy engine — fresh evaluation on EVERY tool call.

Inputs: identity + context + action + resource (all trusted ingestion).
NOT from LLM prompt. LLM decides *which* tool to call; policy decides *whether* it runs.

Start as Python predicate. Swap to OPA/Rego later behind same interface:
  policy.evaluate(ctx) -> Decision

Design per eval-harness: golden evals must be 100% (pass^3=1.0) for auth.
"""
from __future__ import annotations

from ..context.models import RequestContext, Action, QueueOrigin
from .models import Decision


# Lazy import to avoid circular
def _audit(decision: Decision, ctx: RequestContext, event: str = "policy_decision") -> Decision:
    try:
        from ..observability.audit import audit_log

        audit_log(
            event=event,
            policy_id=decision.policy_id,
            allowed=decision.allowed,
            reason=decision.reason,
            technician_id=ctx.identity.technician_id,
            queue_origin=ctx.identity.queue_origin.value,
            subscriber_id=ctx.resource.subscriber_id,
            action=ctx.action.value,
        )
    except Exception:
        pass
    return decision


class PolicyEngine:
    """Simple predicate engine — declarative enough to evolve to Rego."""

    def evaluate(self, ctx: RequestContext) -> Decision:
        """Evaluate fresh — no caching across calls, context may have changed."""
        action = ctx.action
        q = ctx.identity.queue_origin

        # --- Sensitive actions: wifi credentials ---
        if action == Action.GET_WIFI_CREDENTIALS:
            return _audit(self._wifi_policy(ctx, q), ctx)
        if action == Action.GET_LINE_STATUS:
            return _audit(self._line_status_policy(ctx, q), ctx)
        if action == Action.QUERY_DOCS:
            return _audit(self._docs_policy(ctx, q), ctx)
        if action == Action.QUERY_SQL:
            return _audit(self._sql_policy(ctx, q), ctx)

        # Default deny for unknown sensitive actions
        return _audit(
            Decision(
                allowed=False,
                reason=f"Unknown or unconfigured action: {action}",
                policy_id="default-deny",
            ),
            ctx,
        )

    def _wifi_policy(self, ctx: RequestContext, q: QueueOrigin) -> Decision:
        # Rule 1: unauthorized queue — always deny, no matter who
        if q == QueueOrigin.SUPPORT_UNAUTHORIZED:
            return Decision(
                allowed=False,
                reason="Queue origin SUPPORT_UNAUTHORIZED never allowed for wifi credentials",
                policy_id="wifi-deny-unauthorized-queue",
            )

        # Rule 2: field app — allow only if on-site verified + active check-in + site match
        if q == QueueOrigin.FIELD_APP:
            if not ctx.field_checkin_active:
                return Decision(
                    allowed=False,
                    reason="Field check-in not active",
                    policy_id="wifi-deny-no-checkin",
                )
            if not ctx.gps_verified_on_site:
                return Decision(
                    allowed=False,
                    reason="GPS not verified on site",
                    policy_id="wifi-deny-gps",
                )
            # If both sites known, they must match — prevents site-hopping
            if ctx.site_id and ctx.subscriber_site_id and ctx.site_id != ctx.subscriber_site_id:
                return Decision(
                    allowed=False,
                    reason=f"Site mismatch: tech at {ctx.site_id} but subscriber at {ctx.subscriber_site_id}",
                    policy_id="wifi-deny-site-mismatch",
                )
            return Decision(
                allowed=True,
                reason="Field technician verified on-site with active check-in",
                policy_id="wifi-allow-field-onsite",
            )

        # Rule 3: authorized support — allow only with ticket + maybe other checks
        # Stricter for now: require ticket_id
        if q == QueueOrigin.SUPPORT_AUTHORIZED:
            if not ctx.ticket_id:
                return Decision(
                    allowed=False,
                    reason="Authorized support requires ticket_id for wifi access",
                    policy_id="wifi-deny-no-ticket",
                )
            # Could add: require subscriber consent flag, time-bound, etc.
            return Decision(
                allowed=True,
                reason="Authorized support with ticket",
                policy_id="wifi-allow-support-ticket",
            )

        # Rule 4: self-service — subscriber can get own wifi? For demo, deny wifi via tool (use separate flow)
        if q == QueueOrigin.SELF_SERVICE:
            return Decision(
                allowed=False,
                reason="Self-service wifi via this tool not allowed — use subscriber portal",
                policy_id="wifi-deny-self-service",
            )

        return Decision(allowed=False, reason=f"Unhandled queue {q}", policy_id="wifi-default-deny")

    def _line_status_policy(self, ctx: RequestContext, q: QueueOrigin) -> Decision:
        # Line status is less sensitive — allow broader, but still block unauthorized queue without ticket
        if q == QueueOrigin.SUPPORT_UNAUTHORIZED:
            return Decision(
                allowed=False,
                reason="Unauthorized queue cannot query line status",
                policy_id="line-deny-unauthorized",
            )
        # All other queues allowed for line status if technician or ticket context exists
        return Decision(
            allowed=True,
            reason="Line status allowed for verified queue",
            policy_id="line-allow",
        )

    def _docs_policy(self, ctx: RequestContext, q: QueueOrigin) -> Decision:
        # RAG: docs are informational, but still block unauthorized queue without context
        if q == QueueOrigin.SUPPORT_UNAUTHORIZED:
            return Decision(allowed=False, reason="Unauthorized queue cannot query docs", policy_id="docs-deny-unauthorized")
        # Self-service: allow but redact sensitive chunks (WIFI_PSK etc.)
        if q == QueueOrigin.SELF_SERVICE:
            return Decision(allowed=True, reason="Docs query allowed with redaction for self-service", policy_id="docs-allow-redact", redact=True)
        return Decision(allowed=True, reason="Docs query allowed", policy_id="docs-allow")

    def _sql_policy(self, ctx: RequestContext, q: QueueOrigin) -> Decision:
        # SQL: sensitive — same strictness as wifi because it can exfiltrate PSK etc.
        if q == QueueOrigin.SUPPORT_UNAUTHORIZED:
            return Decision(allowed=False, reason="Unauthorized queue cannot query database", policy_id="sql-deny-unauthorized-queue")
        if q == QueueOrigin.FIELD_APP:
            if not ctx.field_checkin_active or not ctx.gps_verified_on_site:
                return Decision(allowed=False, reason="Field app needs active check-in + GPS for SQL", policy_id="sql-deny-no-checkin")
            if ctx.site_id and ctx.subscriber_site_id and ctx.site_id != ctx.subscriber_site_id:
                return Decision(allowed=False, reason="Site mismatch for SQL", policy_id="sql-deny-site-mismatch")
            return Decision(allowed=True, reason="Field SQL allowed", policy_id="sql-allow-field-onsite")
        if q == QueueOrigin.SUPPORT_AUTHORIZED:
            if not ctx.ticket_id:
                return Decision(allowed=False, reason="Authorized support needs ticket for SQL", policy_id="sql-deny-no-ticket")
            return Decision(allowed=True, reason="Support SQL with ticket", policy_id="sql-allow-support-ticket")
        if q == QueueOrigin.SELF_SERVICE:
            # Self-service can query own non-sensitive data, but redact sensitive columns
            return Decision(allowed=True, reason="Self-service SQL allowed with redaction", policy_id="sql-allow-redact", redact=True)
        return Decision(allowed=False, reason=f"Unhandled queue {q} for SQL", policy_id="sql-default-deny")
