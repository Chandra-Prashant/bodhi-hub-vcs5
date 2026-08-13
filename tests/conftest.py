"""
Test fixtures for endpoint tests.

Requires a running Postgres. By default it reuses the Docker instance from
docker-compose and creates a separate throwaway database alongside the
development one, so a test run can never touch real data.

    docker compose up -d
    pytest

Override the server with BODHI_TEST_DB_URL if you keep Postgres elsewhere:

    BODHI_TEST_DB_URL=postgresql+psycopg://postgres:pw@localhost:5432/postgres pytest

Endpoint tests are skipped, not failed, when no server is reachable — a
developer without Docker running still gets a useful signal from the 240 pure
domain tests.

TRANSACTION MODEL
-----------------
Each test runs inside an outer transaction on a single connection, and the
session joins it with `join_transaction_mode="create_savepoint"`. That matters:
route handlers call `db.commit()`, and those commits must genuinely take effect
so that behaviour depending on persistence — the failed-login audit trail and
the lockout counter — is exercised for real. The outer transaction is rolled
back at teardown, so tests stay isolated without anyone having to remember to
clean up.

The bug that motivated this file was invisible to the domain suite: audit rows
for failed logins were written and then discarded by `get_db()`'s rollback, so
account lockout silently never engaged. Every test passed.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import sessionmaker

TEST_DB_NAME = "bodhi_vcs5_test"


def _base_url() -> URL:
    """Parse with SQLAlchemy rather than string surgery.

    Naive rsplit("/") corrupts any URL carrying query parameters — a unix
    socket host, an sslmode, a connect_timeout — because the last slash is not
    necessarily the one before the database name.
    """
    explicit = os.getenv("BODHI_TEST_DB_URL")
    if explicit:
        return make_url(explicit)
    from app.core.config import settings
    return make_url(settings.database_url)


def _admin_url() -> URL:
    return _base_url().set(database="postgres")


def _test_url() -> URL:
    return _base_url().set(database=TEST_DB_NAME)


@pytest.fixture(scope="session")
def db_engine():
    try:
        admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"No Postgres available for endpoint tests: {exc}")

    engine = create_engine(_test_url())

    from app.core.database import Base
    from app.models import user as _user  # noqa: F401  registers tables

    Base.metadata.create_all(engine)
    yield engine

    engine.dispose()
    with admin.connect() as conn:
        conn.execute(text(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = :name"), {"name": TEST_DB_NAME})
        conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}"'))
    admin.dispose()


@pytest.fixture
def db_session(db_engine):
    connection = db_engine.connect()
    transaction = connection.begin()
    Session = sessionmaker(
        bind=connection,
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    session = Session()
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def client(db_session):
    from fastapi.testclient import TestClient

    from app.core.database import get_db
    from app.main import app

    def _override():
        # Must mirror get_db()'s transaction semantics exactly — commit on
        # success, rollback on exception. An override that merely yields the
        # session removes the very code path where transaction bugs live, and
        # the suite then passes against broken code. That is not hypothetical:
        # the first version of this fixture did exactly that, and the audit
        # rollback bug it was written to catch sailed through it.
        try:
            yield db_session
            db_session.commit()
        except Exception:
            db_session.rollback()
            raise

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def make_user(db_session):
    """Create a user directly, bypassing the API."""
    from app.core.security import hash_password
    from app.models.user import Role, User

    created: list[User] = []

    def _make(email="user@example.com", password="correct-horse-battery",
              role=Role.PROJECT_MANAGER, organization="Bodhi Hub", **kw):
        user = User(
            email=email.lower(),
            full_name=kw.pop("full_name", "Test User"),
            hashed_password=hash_password(password),
            role=role,
            organization=organization,
            **kw,
        )
        db_session.add(user)
        db_session.flush()
        created.append(user)
        return user

    return _make


@pytest.fixture
def login(client):
    def _login(email: str, password: str):
        return client.post("/api/v1/auth/login",
                           json={"email": email, "password": password})
    return _login


@pytest.fixture
def auth_headers(client, login):
    def _headers(email: str, password: str) -> dict[str, str]:
        response = login(email, password)
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    return _headers
