"""FastAPI auth dependencies — ECC fastapi-patterns + security-review.

- X-Field-Token (signed field JWT) and X-Queue-Token (signed queue JWT) headers.
- 401 for bad/expired identity tokens, 403 left to policy engine for authorization.
- Thin deps; business logic stays in builder/policy (service layer).
"""
from __future__ import annotations

from fastapi import Header, HTTPException, status


async def get_field_token_claims(
    x_field_token: str | None = Header(default=None, alias="X-Field-Token"),
) -> dict | None:
    if not x_field_token:
        return None
    try:
        from .tokens import verify_field_token

        return verify_field_token(x_field_token)
    except Exception:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid field token")


async def get_queue_claims(
    x_queue_token: str | None = Header(default=None, alias="X-Queue-Token"),
) -> dict | None:
    if not x_queue_token:
        return None
    try:
        from .queue_router import verify_queue_header

        claims = verify_queue_header(x_queue_token)
    except Exception:
        claims = None
    if x_queue_token and "." in x_queue_token and not claims:
        # Signed but invalid -> 401 (identity layer), not 403
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid queue token")
    return claims
