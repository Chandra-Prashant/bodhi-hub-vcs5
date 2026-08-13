"""Password hashing and JWT issuance.

Argon2id rather than bcrypt: bcrypt silently truncates passwords at 72 bytes
and the passlib/bcrypt version handshake is a recurring source of startup
errors. Argon2 is the current OWASP recommendation.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.core.config import settings

_hasher = PasswordHasher()


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


def hash_password(plain: str) -> str:
    return _hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    # InvalidHashError is NOT a subclass of VerificationError, so a corrupt or
    # truncated hash column would propagate a 500 instead of failing the login.
    try:
        _hasher.verify(hashed, plain)
        return True
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return False


def create_token(
    subject: str,
    token_type: TokenType,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    lifetime = (
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        if token_type is TokenType.ACCESS
        else timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type.value,
        "iat": now,
        "exp": now + lifetime,
        "jti": str(uuid.uuid4()),
        **(extra_claims or {}),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    """Raises jwt.PyJWTError on any problem — caller maps to HTTP 401."""
    payload = jwt.decode(
        token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
    )
    if payload.get("type") != expected_type.value:
        raise jwt.InvalidTokenError(
            f"Expected a {expected_type.value} token, got {payload.get('type')!r}"
        )
    return payload
