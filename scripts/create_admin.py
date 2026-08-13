#!/usr/bin/env python
"""
Create the first ADMIN user.

There is no self-registration endpoint, so the initial account is created here,
out of band. Run once after `alembic upgrade head`:

    python scripts/create_admin.py

The password is read from a prompt, never from argv — command-line arguments
land in shell history and process listings.
"""

from __future__ import annotations

import getpass
import sys

from sqlalchemy import select

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.user import Role, User


def main() -> int:
    email = input("Admin email: ").strip().lower()
    if not email or "@" not in email:
        print("A valid email address is required.", file=sys.stderr)
        return 1

    full_name = input("Full name: ").strip()
    organization = input("Organization: ").strip()
    if not full_name or not organization:
        print("Full name and organization are required.", file=sys.stderr)
        return 1

    password = getpass.getpass("Password (min 12 chars): ")
    if len(password) < 12:
        print("Password must be at least 12 characters.", file=sys.stderr)
        return 1
    if password != getpass.getpass("Confirm password: "):
        print("Passwords do not match.", file=sys.stderr)
        return 1

    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == email)):
            print(f"A user with email {email} already exists.", file=sys.stderr)
            return 1

        db.add(User(
            email=email,
            full_name=full_name,
            hashed_password=hash_password(password),
            role=Role.ADMIN,
            organization=organization,
            must_change_password=False,
        ))
        db.commit()

    print(f"\nAdmin created: {email} ({organization})")
    print("Log in at POST /api/v1/auth/login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
