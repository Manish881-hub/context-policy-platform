"""Clean adapter — hides awkward protocol, exposes 4-5 named functions.

Per ADR 0001: adapter does SECOND auth check (defense in depth).
The policy engine is primary; adapter re-validates so prompt bypass alone insufficient.

Seam for TDD: these public methods (test at this layer, not wrapper).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..context.models import RequestContext, Action
from ..policy.engine import PolicyEngine, Decision
from .db import DB_PATH
from .legacy_wrapper import LegacyProtocolWrapper, LegacyProtocolError


@dataclass
class WifiCredentials:
    ssid: str
    psk: str  # sensitive
    subscriber_id: str


@dataclass
class LineStatus:
    status: str
    olt_id: str
    ont_serial: str
    subscriber_id: str


class ProvisioningAdapter:
    """Thin service exposing typed functions over legacy wrapper."""

    def __init__(self, db_path: Path | None = None, policy: PolicyEngine | None = None):
        self.db_path = db_path or DB_PATH
        self.policy = policy or PolicyEngine()
        self._wrapper = LegacyProtocolWrapper(db_path=self.db_path)

    def _ensure_session(self, ctx: RequestContext) -> bytes:
        tech = ctx.identity.technician_id or ctx.identity.user_id or "ANON"
        return self._wrapper.open_session(f"SESSION:{tech}".encode())

    def get_wifi_credentials(self, ctx: RequestContext) -> WifiCredentials:
        """Fetch wifi creds — policy checked HERE, not in prompt."""
        # ---- Gate 1: primary policy check ----
        decision: Decision = self.policy.evaluate(ctx)
        if not decision.allowed:
            raise PermissionError(f"DENIED: {decision.reason} [policy={decision.policy_id}]")
        if ctx.action != Action.GET_WIFI_CREDENTIALS:
            raise ValueError(f"Adapter action mismatch: ctx.action={ctx.action}")

        # ---- Gate 2: adapter-level re-check (defense in depth) ----
        # Re-evaluate via same engine to ensure no bypass if caller mocks policy once.
        # In production this could be a sidecar/OPA call with same inputs.
        second = self.policy.evaluate(ctx)
        if not second.allowed:
            raise PermissionError(f"DENIED at adapter re-check: {second.reason}")

        # ---- Actual legacy call ----
        token = self._ensure_session(ctx)
        raw = f"GET_WIFI|{ctx.resource.subscriber_id}|{token.decode()}".encode()
        resp = self._wrapper.execute(raw)
        text = resp.decode()
        if text.startswith("ERR"):
            raise RuntimeError(f"Legacy error: {text}")
        # OK|SSID|PSK
        _, ssid, psk = text.split("|", 2)
        return WifiCredentials(ssid=ssid, psk=psk, subscriber_id=ctx.resource.subscriber_id)

    def get_line_status(self, ctx: RequestContext) -> LineStatus:
        decision = self.policy.evaluate(ctx)
        if not decision.allowed:
            raise PermissionError(f"DENIED: {decision.reason}")
        if ctx.action != Action.GET_LINE_STATUS:
            raise ValueError(f"Action mismatch: {ctx.action}")
        second = self.policy.evaluate(ctx)
        if not second.allowed:
            raise PermissionError(f"DENIED at adapter re-check: {second.reason}")
        token = self._ensure_session(ctx)
        raw = f"GET_LINE|{ctx.resource.subscriber_id}|{token.decode()}".encode()
        resp = self._wrapper.execute(raw)
        text = resp.decode()
        if text.startswith("ERR"):
            raise RuntimeError(f"Legacy error: {text}")
        _, status, olt_id, ont_sn = text.split("|", 3)
        return LineStatus(status=status, olt_id=olt_id, ont_serial=ont_sn, subscriber_id=ctx.resource.subscriber_id)
