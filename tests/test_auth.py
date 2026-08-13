"""
Security primitive tests — hashing and JWT. No database required.

Endpoint-level tests (lockout counting, org scoping, audit writes) need a
throwaway Postgres and are not here yet; see the note at the bottom of the
file for what still needs covering.
"""

from __future__ import annotations

import time
import uuid
from datetime import timedelta

import jwt
import pytest

from app.core.config import settings
from app.core.security import (
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)


# --- password hashing ------------------------------------------------------

def test_hash_is_argon2id_and_not_reversible():
    hashed = hash_password("correct horse battery staple")
    assert hashed.startswith("$argon2id$")
    assert "correct horse" not in hashed


def test_verify_accepts_the_right_password():
    hashed = hash_password("s3cure-passphrase-2026")
    assert verify_password("s3cure-passphrase-2026", hashed)


def test_verify_rejects_the_wrong_password():
    hashed = hash_password("s3cure-passphrase-2026")
    assert not verify_password("s3cure-passphrase-2025", hashed)


def test_same_password_hashes_differently_each_time():
    """Per-hash salt — identical passwords must not produce identical hashes."""
    a = hash_password("same-password-here")
    b = hash_password("same-password-here")
    assert a != b
    assert verify_password("same-password-here", a)
    assert verify_password("same-password-here", b)


def test_long_password_is_not_truncated():
    """bcrypt silently truncates at 72 bytes; Argon2 does not. Two passwords
    sharing a 72-byte prefix must not be interchangeable."""
    base = "x" * 72
    hashed = hash_password(base + "AAAA")
    assert not verify_password(base + "BBBB", hashed)


def test_verify_rejects_a_malformed_hash_without_raising():
    assert not verify_password("anything", "not-a-real-hash")


# --- JWT -------------------------------------------------------------------

def test_access_token_roundtrip_carries_claims():
    uid = str(uuid.uuid4())
    token = create_token(uid, TokenType.ACCESS,
                         {"role": "ADMIN", "org": "Bodhi Hub"})
    claims = decode_token(token, TokenType.ACCESS)
    assert claims["sub"] == uid
    assert claims["role"] == "ADMIN"
    assert claims["org"] == "Bodhi Hub"


def test_refresh_token_cannot_be_used_as_an_access_token():
    """Token-type confusion: a long-lived refresh token must never be accepted
    where a short-lived access token is expected."""
    token = create_token(str(uuid.uuid4()), TokenType.REFRESH)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, TokenType.ACCESS)


def test_access_token_cannot_be_used_as_a_refresh_token():
    token = create_token(str(uuid.uuid4()), TokenType.ACCESS)
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, TokenType.REFRESH)


def test_token_signed_with_another_key_is_rejected():
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access"},
        "an-attacker-supplied-key-that-is-long-enough",
        algorithm="HS256")
    with pytest.raises(jwt.PyJWTError):
        decode_token(forged, TokenType.ACCESS)


def test_alg_none_token_is_rejected():
    """The classic JWT bypass: unsigned token claiming alg=none."""
    forged = jwt.encode({"sub": str(uuid.uuid4()), "type": "access"},
                        key="", algorithm="none")
    with pytest.raises(jwt.PyJWTError):
        decode_token(forged, TokenType.ACCESS)


def test_expired_token_is_rejected():
    now = int(time.time())
    expired = jwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access",
         "iat": now - 7200, "exp": now - 3600},
        settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired, TokenType.ACCESS)


def test_tokens_carry_a_unique_jti():
    a = decode_token(create_token("u", TokenType.ACCESS), TokenType.ACCESS)
    b = decode_token(create_token("u", TokenType.ACCESS), TokenType.ACCESS)
    assert a["jti"] != b["jti"]


def test_refresh_token_outlives_the_access_token():
    uid = str(uuid.uuid4())
    access = decode_token(create_token(uid, TokenType.ACCESS), TokenType.ACCESS)
    refresh = decode_token(create_token(uid, TokenType.REFRESH), TokenType.REFRESH)
    assert refresh["exp"] > access["exp"]


def test_access_token_lifetime_matches_configuration():
    claims = decode_token(create_token("u", TokenType.ACCESS), TokenType.ACCESS)
    lifetime = claims["exp"] - claims["iat"]
    expected = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES).total_seconds()
    assert lifetime == pytest.approx(expected, abs=2)


# --- STILL TO COVER (needs a throwaway Postgres) ---------------------------
# - failed_login_count increments and locks at MAX_FAILED_LOGINS
# - locked and inactive accounts are refused
# - login failure message is identical for unknown email and bad password
# - every login attempt writes an audit row, success and failure alike
# - admin routes reject AUDITOR and PROJECT_MANAGER
# - admin cannot read or modify users in another organization
# - an admin cannot deactivate their own account
# - must_change_password blocks work routes but not /auth/change-password
