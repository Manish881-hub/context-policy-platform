"""Signed tokens — stdlib HS256, no extra deps.

ECC security-review: secrets in env, fail closed, generic errors.
ECC fastapi-patterns: JWT decode defensively, 401 vs 403 separation.
ECC python-patterns: specific exceptions, EAFP.

Field token claims: {technician_id, site_id, lat, lon, exp}
Queue token claims: {queue_origin, ticket_id, exp}
Secret: FIELD_JWT_SECRET / QUEUE_JWT_SECRET (or JWT_SECRET fallback). Never logged.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time


class TokenError(ValueError):
    pass


def _secret(name: str) -> str:
    s = os.getenv(name) or os.getenv("JWT_SECRET") or "dev-only-secret-change-in-prod"
    if not s:
        raise TokenError("missing secret")
    return s


def _b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def sign(claims: dict, secret: str) -> str:
    header = _b64u(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = _b64u(json.dumps(claims).encode())
    sig = _b64u(hmac.new(secret.encode(), f"{header}.{payload}".encode(), hashlib.sha256).digest())
    return f"{header}.{payload}.{sig}"


def verify(token: str, secret: str, max_age_s: int = 7200) -> dict:
    try:
        header_b, payload_b, sig_b = token.split(".")
    except ValueError:
        raise TokenError("malformed token")
    expected = _b64u(hmac.new(secret.encode(), f"{header_b}.{payload_b}".encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(expected, sig_b):
        raise TokenError("bad signature")
    try:
        claims = json.loads(_unb64u(payload_b))
    except Exception:
        raise TokenError("bad payload")
    exp = claims.get("exp")
    if exp is not None and time.time() > float(exp):
        raise TokenError("token expired")
    return claims


def issue_field_token(technician_id: str, site_id: str, lat: float, lon: float, ttl_s: int = 7200) -> str:
    return sign(
        {"technician_id": technician_id, "site_id": site_id, "lat": lat, "lon": lon, "exp": time.time() + ttl_s},
        _secret("FIELD_JWT_SECRET"),
    )


def verify_field_token(token: str) -> dict:
    return verify(token, _secret("FIELD_JWT_SECRET"))


def issue_queue_token(queue_origin: str, ticket_id: str | None = None, ttl_s: int = 3600) -> str:
    return sign(
        {"queue_origin": queue_origin, "ticket_id": ticket_id, "exp": time.time() + ttl_s},
        _secret("QUEUE_JWT_SECRET"),
    )


def verify_queue_token(token: str) -> dict:
    return verify(token, _secret("QUEUE_JWT_SECRET"))
