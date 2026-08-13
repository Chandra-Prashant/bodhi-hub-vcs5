"""Audit trail writer.

Append-only by design. There is no update or delete helper in this module and
none should be added: `audit_logs` is the evidence a VVB inspects, and a
system that can rewrite its own trail cannot support a compliance claim.
Retention is handled by archival outside the application.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.user import AuditLog


class Action:
    LOGIN = "auth.login"
    LOGOUT = "auth.logout"
    TOKEN_REFRESH = "auth.token_refresh"
    PASSWORD_CHANGE = "auth.password_change"
    ACCOUNT_LOCKED = "auth.account_locked"
    USER_CREATED = "admin.user_created"
    USER_DEACTIVATED = "admin.user_deactivated"
    USER_UNLOCKED = "admin.user_unlocked"
    CLASSIFICATION_RUN = "module1.classification_evaluated"


SUCCESS = "SUCCESS"
FAILURE = "FAILURE"


def client_ip(request: Request | None) -> str | None:
    if request is None:
        return None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


def record(
    db: Session,
    *,
    action: str,
    outcome: str,
    actor_email: str,
    organization: str,
    user_id: uuid.UUID | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request: Request | None = None,
    detail: dict[str, Any] | None = None,
    note: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user_id,
        actor_email=actor_email,
        organization=organization,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        outcome=outcome,
        ip_address=client_ip(request),
        detail=detail,
        note=note,
    )
    db.add(entry)
    db.flush()
    return entry
