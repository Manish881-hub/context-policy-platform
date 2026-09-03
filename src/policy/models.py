from __future__ import annotations

from pydantic import BaseModel


class Decision(BaseModel):
    allowed: bool
    reason: str
    policy_id: str  # which rule fired, for audit
    redact: bool = False  # if true, caller should redact sensitive fields
