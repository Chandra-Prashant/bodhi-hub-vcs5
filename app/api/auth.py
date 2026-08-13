"""
Authentication and user administration.

Design notes:
- No self-registration. Users are provisioned by an ADMIN; the first admin is
  created out of band via scripts/create_admin.py.
- Login failures return one generic message regardless of cause, so the
  endpoint cannot be used to enumerate valid email addresses.
- Every authentication event is written to the audit trail, successes and
  failures alike. A trail that records only successes is not a trail.
- Failed attempts increment a counter and lock the account at the configured
  threshold. Unlock is an admin action and is itself audited.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_roles
from app.core.config import settings
from app.core.database import get_db
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
)
from app.models.user import AuditLog, Role, User
from app.schemas.auth import (
    AccessToken,
    AuditLogOut,
    LoginIn,
    PasswordChangeIn,
    RefreshIn,
    TokenPair,
    UserCreateIn,
    UserOut,
)
from app.services import audit

router = APIRouter(prefix="/auth", tags=["Authentication"])
admin_router = APIRouter(prefix="/admin", tags=["Administration"])

_GENERIC_LOGIN_FAILURE = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Incorrect email or password",
    headers={"WWW-Authenticate": "Bearer"},
)


def _issue_pair(user: User) -> TokenPair:
    claims = {"role": user.role.value, "org": user.organization}
    return TokenPair(
        access_token=create_token(str(user.id), TokenType.ACCESS, claims),
        refresh_token=create_token(str(user.id), TokenType.REFRESH),
        must_change_password=user.must_change_password,
    )


@router.post("/login", response_model=TokenPair)
def login(
    payload: LoginIn,
    request: Request,
    db: Session = Depends(get_db),
) -> TokenPair:
    user = db.scalar(select(User).where(User.email == payload.email.lower()))

    if user is None:
        # Still audited: repeated failures against unknown addresses are the
        # signature of a credential-stuffing attempt.
        audit.record(
            db, action=audit.Action.LOGIN, outcome=audit.FAILURE,
            actor_email=payload.email.lower(), organization="-",
            request=request, note="No such user")
        raise _GENERIC_LOGIN_FAILURE

    if user.is_locked or not user.is_active:
        audit.record(
            db, action=audit.Action.LOGIN, outcome=audit.FAILURE,
            actor_email=user.email, organization=user.organization,
            user_id=user.id, request=request,
            note="Account locked" if user.is_locked else "Account inactive")
        raise _GENERIC_LOGIN_FAILURE

    if not verify_password(payload.password, user.hashed_password):
        user.failed_login_count += 1
        note = f"Bad password (attempt {user.failed_login_count})"
        if user.failed_login_count >= settings.MAX_FAILED_LOGINS:
            user.is_locked = True
            audit.record(
                db, action=audit.Action.ACCOUNT_LOCKED, outcome=audit.SUCCESS,
                actor_email=user.email, organization=user.organization,
                user_id=user.id, request=request,
                note=f"Locked after {user.failed_login_count} failed attempts")
        audit.record(
            db, action=audit.Action.LOGIN, outcome=audit.FAILURE,
            actor_email=user.email, organization=user.organization,
            user_id=user.id, request=request, note=note)
        raise _GENERIC_LOGIN_FAILURE

    # Transparent upgrade if Argon2 parameters have been hardened since signup.
    if needs_rehash(user.hashed_password):
        user.hashed_password = hash_password(payload.password)

    user.failed_login_count = 0
    user.last_login_at = datetime.now(timezone.utc)
    audit.record(
        db, action=audit.Action.LOGIN, outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, request=request)

    return _issue_pair(user)


@router.post("/refresh", response_model=AccessToken)
def refresh(
    payload: RefreshIn,
    request: Request,
    db: Session = Depends(get_db),
) -> AccessToken:
    try:
        claims = decode_token(payload.refresh_token, TokenType.REFRESH)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token")

    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active or user.is_locked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token")

    audit.record(
        db, action=audit.Action.TOKEN_REFRESH, outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, request=request)

    return AccessToken(access_token=create_token(
        str(user.id), TokenType.ACCESS,
        {"role": user.role.value, "org": user.organization}))


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)) -> User:
    return user


@router.post("/change-password", response_model=UserOut)
def change_password(
    payload: PasswordChangeIn,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> User:
    if not verify_password(payload.current_password, user.hashed_password):
        audit.record(
            db, action=audit.Action.PASSWORD_CHANGE, outcome=audit.FAILURE,
            actor_email=user.email, organization=user.organization,
            user_id=user.id, request=request, note="Current password incorrect")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect")

    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must differ from the current one")

    user.hashed_password = hash_password(payload.new_password)
    user.must_change_password = False
    audit.record(
        db, action=audit.Action.PASSWORD_CHANGE, outcome=audit.SUCCESS,
        actor_email=user.email, organization=user.organization,
        user_id=user.id, request=request)
    return user


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

@admin_router.post("/users", response_model=UserOut,
                   status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreateIn,
    request: Request,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    if db.scalar(select(User).where(User.email == payload.email.lower())):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A user with that email already exists")

    user = User(
        email=payload.email.lower(),
        full_name=payload.full_name,
        hashed_password=hash_password(payload.initial_password),
        role=payload.role,
        organization=payload.organization,
        must_change_password=True,
    )
    db.add(user)
    db.flush()

    audit.record(
        db, action=audit.Action.USER_CREATED, outcome=audit.SUCCESS,
        actor_email=admin.email, organization=admin.organization,
        user_id=admin.id, resource_type="user", resource_id=str(user.id),
        request=request,
        detail={"role": user.role.value, "organization": user.organization})
    return user


@admin_router.get("/users", response_model=list[UserOut])
def list_users(
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> list[User]:
    return list(db.scalars(
        select(User)
        .where(User.organization == admin.organization)
        .order_by(User.email)))


@admin_router.post("/users/{user_id}/unlock", response_model=UserOut)
def unlock_user(
    user_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None or user.organization != admin.organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")

    user.is_locked = False
    user.failed_login_count = 0
    audit.record(
        db, action=audit.Action.USER_UNLOCKED, outcome=audit.SUCCESS,
        actor_email=admin.email, organization=admin.organization,
        user_id=admin.id, resource_type="user", resource_id=str(user.id),
        request=request)
    return user


@admin_router.post("/users/{user_id}/deactivate", response_model=UserOut)
def deactivate_user(
    user_id: uuid.UUID,
    request: Request,
    admin: User = Depends(require_roles(Role.ADMIN)),
    db: Session = Depends(get_db),
) -> User:
    user = db.get(User, user_id)
    if user is None or user.organization != admin.organization:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                            detail="User not found")
    if user.id == admin.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="You cannot deactivate your own account")

    user.is_active = False
    audit.record(
        db, action=audit.Action.USER_DEACTIVATED, outcome=audit.SUCCESS,
        actor_email=admin.email, organization=admin.organization,
        user_id=admin.id, resource_type="user", resource_id=str(user.id),
        request=request)
    return user


@admin_router.get("/audit-logs", response_model=list[AuditLogOut])
def read_audit_logs(
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(require_roles(Role.ADMIN, Role.AUDITOR)),
    db: Session = Depends(get_db),
) -> list[AuditLog]:
    """Read-only. There is deliberately no delete or export-and-purge route."""
    return list(db.scalars(
        select(AuditLog)
        .where(AuditLog.organization == user.organization)
        .order_by(AuditLog.created_at.desc())
        .limit(min(limit, 1000))
        .offset(offset)))
