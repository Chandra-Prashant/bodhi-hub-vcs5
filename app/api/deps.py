"""Shared FastAPI dependencies.

Every non-public route depends on `get_current_user`. There is no route in this
codebase that touches project data without one — that was the single worst
defect in the prototype.
"""

from __future__ import annotations

import uuid

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import TokenType, decode_token
from app.models.user import Role, User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    try:
        payload = decode_token(token, TokenType.ACCESS)
        user_id = uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError, TypeError):
        raise _CREDENTIALS_ERROR

    user = db.get(User, user_id)
    if user is None or not user.is_active or user.is_locked:
        raise _CREDENTIALS_ERROR
    return user


def require_password_current(
    user: User = Depends(get_current_user),
) -> User:
    """Blocks work routes until a provisioned initial password is replaced.

    Deliberately not applied to /auth/me or /auth/change-password, or the user
    would have no way to clear the flag.
    """
    if user.must_change_password:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Password change required before using this endpoint")
    return user


def require_roles(*roles: Role):
    """Route guard: `Depends(require_roles(Role.ADMIN))`."""

    def _guard(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions for this operation",
            )
        return user

    return _guard
