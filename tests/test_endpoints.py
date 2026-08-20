"""
Endpoint tests — the behaviour the domain suite cannot reach.

These require Postgres (see conftest.py) and are skipped without it.

The first group is a regression suite for a bug that shipped: audit rows for
failed logins were written and then discarded by `get_db()`'s rollback when the
route raised, so the failure trail was empty and account lockout never engaged.
Every test in the 240-test domain suite passed throughout.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.user import AuditLog, Role

PASSWORD = "correct-horse-battery-staple"
WRONG = "not-the-right-password"


def _audit_rows(db, action=None):
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    return list(db.scalars(stmt.order_by(AuditLog.created_at)))


# --- audit persistence across a failed request ----------------------------

def test_successful_login_is_audited(client, db_session, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD)
    assert login("pm@example.com", PASSWORD).status_code == 200
    rows = _audit_rows(db_session, "auth.login")
    assert [r.outcome for r in rows] == ["SUCCESS"]


def test_failed_login_is_audited(client, db_session, make_user, login):
    """THE REGRESSION TEST. The route writes an audit row then raises; if that
    write is rolled back with the request, this table stays empty."""
    make_user(email="pm@example.com", password=PASSWORD)
    assert login("pm@example.com", WRONG).status_code == 401
    rows = _audit_rows(db_session, "auth.login")
    assert len(rows) == 1
    assert rows[0].outcome == "FAILURE"
    assert "attempt 1" in (rows[0].note or "")


def test_login_against_an_unknown_address_is_audited(client, db_session, login):
    """Repeated failures against unknown addresses are the signature of
    credential stuffing, so they must be recorded too."""
    assert login("nobody@example.com", WRONG).status_code == 401
    rows = _audit_rows(db_session, "auth.login")
    assert len(rows) == 1
    assert rows[0].actor_email == "nobody@example.com"


# --- lockout counter survives across requests -----------------------------

def test_failed_attempts_accumulate(client, db_session, make_user, login):
    user = make_user(email="pm@example.com", password=PASSWORD)
    for _ in range(3):
        login("pm@example.com", WRONG)
    db_session.refresh(user)
    assert user.failed_login_count == 3
    assert not user.is_locked


def test_account_locks_at_the_configured_threshold(
        client, db_session, make_user, login):
    user = make_user(email="pm@example.com", password=PASSWORD)
    for _ in range(settings.MAX_FAILED_LOGINS):
        login("pm@example.com", WRONG)
    db_session.refresh(user)
    assert user.is_locked
    assert any(r.action == "auth.account_locked" for r in _audit_rows(db_session))


def test_a_locked_account_refuses_the_correct_password(
        client, db_session, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD)
    for _ in range(settings.MAX_FAILED_LOGINS):
        login("pm@example.com", WRONG)
    assert login("pm@example.com", PASSWORD).status_code == 401


def test_a_successful_login_resets_the_counter(
        client, db_session, make_user, login):
    user = make_user(email="pm@example.com", password=PASSWORD)
    login("pm@example.com", WRONG)
    login("pm@example.com", PASSWORD)
    db_session.refresh(user)
    assert user.failed_login_count == 0


def test_inactive_accounts_are_refused(client, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD, is_active=False)
    assert login("pm@example.com", PASSWORD).status_code == 401


# --- no user enumeration ---------------------------------------------------

def test_unknown_address_and_wrong_password_are_indistinguishable(
        client, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD)
    unknown = login("nobody@example.com", WRONG)
    wrong = login("pm@example.com", WRONG)
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json()


def test_locked_account_is_indistinguishable_from_a_bad_password(
        client, make_user, login):
    make_user(email="locked@example.com", password=PASSWORD, is_locked=True)
    make_user(email="pm@example.com", password=PASSWORD)
    assert (login("locked@example.com", PASSWORD).json()
            == login("pm@example.com", WRONG).json())


# --- RBAC ------------------------------------------------------------------

@pytest.mark.parametrize("role", [Role.PROJECT_MANAGER, Role.AUDITOR])
def test_non_admins_cannot_create_users(client, make_user, auth_headers, role):
    make_user(email="user@example.com", password=PASSWORD, role=role)
    response = client.post(
        "/api/v1/admin/users",
        headers=auth_headers("user@example.com", PASSWORD),
        json={"email": "new@example.com", "full_name": "New",
              "role": "PROJECT_MANAGER", "organization": "Bodhi Hub",
              "initial_password": "another-long-password"})
    assert response.status_code == 403


def test_admins_can_create_users(client, make_user, auth_headers):
    make_user(email="admin@example.com", password=PASSWORD, role=Role.ADMIN)
    response = client.post(
        "/api/v1/admin/users",
        headers=auth_headers("admin@example.com", PASSWORD),
        json={"email": "new@example.com", "full_name": "New",
              "role": "PROJECT_MANAGER", "organization": "Bodhi Hub",
              "initial_password": "another-long-password"})
    assert response.status_code == 201
    assert response.json()["must_change_password"] is True


def test_project_managers_cannot_read_audit_logs(
        client, make_user, auth_headers):
    make_user(email="pm@example.com", password=PASSWORD)
    response = client.get("/api/v1/admin/audit-logs",
                          headers=auth_headers("pm@example.com", PASSWORD))
    assert response.status_code == 403


def test_auditors_can_read_audit_logs(client, make_user, auth_headers):
    make_user(email="auditor@example.com", password=PASSWORD, role=Role.AUDITOR)
    response = client.get("/api/v1/admin/audit-logs",
                          headers=auth_headers("auditor@example.com", PASSWORD))
    assert response.status_code == 200


# --- organization scoping — the one that leaks client data ----------------

def test_admins_only_see_their_own_organizations_users(
        client, make_user, auth_headers):
    make_user(email="admin@a.com", password=PASSWORD, role=Role.ADMIN,
              organization="Org A")
    make_user(email="pm@b.com", password=PASSWORD, organization="Org B")
    response = client.get("/api/v1/admin/users",
                          headers=auth_headers("admin@a.com", PASSWORD))
    assert response.status_code == 200
    assert {u["email"] for u in response.json()} == {"admin@a.com"}


def test_admins_cannot_unlock_another_organizations_user(
        client, make_user, auth_headers):
    make_user(email="admin@a.com", password=PASSWORD, role=Role.ADMIN,
              organization="Org A")
    victim = make_user(email="pm@b.com", password=PASSWORD,
                       organization="Org B", is_locked=True)
    response = client.post(
        f"/api/v1/admin/users/{victim.id}/unlock",
        headers=auth_headers("admin@a.com", PASSWORD))
    assert response.status_code == 404


def test_admins_cannot_deactivate_another_organizations_user(
        client, make_user, auth_headers):
    make_user(email="admin@a.com", password=PASSWORD, role=Role.ADMIN,
              organization="Org A")
    victim = make_user(email="pm@b.com", password=PASSWORD, organization="Org B")
    response = client.post(
        f"/api/v1/admin/users/{victim.id}/deactivate",
        headers=auth_headers("admin@a.com", PASSWORD))
    assert response.status_code == 404


def test_audit_logs_are_scoped_to_the_organization(
        client, db_session, make_user, auth_headers, login):
    make_user(email="admin@a.com", password=PASSWORD, role=Role.ADMIN,
              organization="Org A")
    make_user(email="pm@b.com", password=PASSWORD, organization="Org B")
    login("pm@b.com", PASSWORD)
    response = client.get("/api/v1/admin/audit-logs",
                          headers=auth_headers("admin@a.com", PASSWORD))
    assert all(r["organization"] == "Org A" for r in response.json())


def test_an_admin_cannot_deactivate_themselves(client, make_user, auth_headers):
    admin = make_user(email="admin@a.com", password=PASSWORD, role=Role.ADMIN)
    response = client.post(
        f"/api/v1/admin/users/{admin.id}/deactivate",
        headers=auth_headers("admin@a.com", PASSWORD))
    assert response.status_code == 400


# --- tokens ----------------------------------------------------------------

def test_protected_routes_reject_anonymous_requests(client):
    assert client.get("/api/v1/auth/me").status_code == 401
    assert client.post("/api/v1/classification/evaluate", json={}).status_code == 401


def test_a_refresh_token_is_rejected_as_a_bearer_token(
        client, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD)
    refresh = login("pm@example.com", PASSWORD).json()["refresh_token"]
    response = client.get("/api/v1/auth/me",
                          headers={"Authorization": f"Bearer {refresh}"})
    assert response.status_code == 401


def test_refresh_issues_a_working_access_token(client, make_user, login):
    make_user(email="pm@example.com", password=PASSWORD)
    refresh = login("pm@example.com", PASSWORD).json()["refresh_token"]
    response = client.post("/api/v1/auth/refresh",
                           json={"refresh_token": refresh})
    assert response.status_code == 200
    token = response.json()["access_token"]
    assert client.get("/api/v1/auth/me",
                      headers={"Authorization": f"Bearer {token}"}
                      ).status_code == 200


def test_a_locked_users_token_stops_working(
        client, db_session, make_user, auth_headers):
    user = make_user(email="pm@example.com", password=PASSWORD)
    headers = auth_headers("pm@example.com", PASSWORD)
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
    user.is_locked = True
    db_session.flush()
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


# --- password change -------------------------------------------------------

def test_password_change_clears_the_must_change_flag(
        client, db_session, make_user, auth_headers):
    user = make_user(email="pm@example.com", password=PASSWORD,
                     must_change_password=True)
    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers("pm@example.com", PASSWORD),
        json={"current_password": PASSWORD,
              "new_password": "a-brand-new-long-password"})
    assert response.status_code == 200
    db_session.refresh(user)
    assert not user.must_change_password


def test_a_wrong_current_password_is_audited(
        client, db_session, make_user, auth_headers):
    make_user(email="pm@example.com", password=PASSWORD)
    response = client.post(
        "/api/v1/auth/change-password",
        headers=auth_headers("pm@example.com", PASSWORD),
        json={"current_password": WRONG,
              "new_password": "a-brand-new-long-password"})
    assert response.status_code == 400
    rows = _audit_rows(db_session, "auth.password_change")
    assert rows and rows[-1].outcome == "FAILURE"


def test_the_new_password_actually_works(client, make_user, auth_headers, login):
    make_user(email="pm@example.com", password=PASSWORD)
    client.post("/api/v1/auth/change-password",
                headers=auth_headers("pm@example.com", PASSWORD),
                json={"current_password": PASSWORD,
                      "new_password": "a-brand-new-long-password"})
    assert login("pm@example.com", "a-brand-new-long-password").status_code == 200
    assert login("pm@example.com", PASSWORD).status_code == 401


# --- the working state survives a session ---------------------------------

def _draft_payload(**over):
    payload = {
        "name": "Aligarh Solar One", "proponent": "Bodhi Hub Client",
        "country_iso2": "IN", "technology": "SOLAR_PV_TERRESTRIAL",
        "installed_capacity_mw": 50.0,
        "expected_annual_generation_mwh": 87600.0,
        "initial_crediting_period_start": "2026-03-01",
        "grid_units": [],
        "esg_entries": [{
            "category": "S2", "risk_id": "S2.1", "severity": 4, "likelihood": 3,
            "description": "Land assembled from multiple smallholders.",
            "justification": "Records incomplete; informal tenancy common.",
            "mitigation": "Independent title verification; grievance mechanism.",
        }],
    }
    payload.update(over)
    return payload


def test_an_empty_draft_is_not_an_error(client, admin_headers):
    """First use is a normal condition, not a 404."""
    response = client.get("/api/v1/assessment/draft", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["state"] is None


def test_a_draft_survives_a_new_session(client, admin_headers):
    """Twelve categories of ESG judgement is an hour of typing. It used to
    live only in the browser tab and vanish on sign-out."""
    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload())

    state = client.get("/api/v1/assessment/draft",
                       headers=admin_headers).json()["state"]
    assert state["name"] == "Aligarh Solar One"
    assert len(state["esg_entries"]) == 1
    assert state["esg_entries"][0]["severity"] == 4


def test_a_malformed_draft_is_refused_not_stored(client, admin_headers):
    """A draft that cannot be loaded must never be written."""
    assert client.put("/api/v1/assessment/draft", headers=admin_headers,
                      json={"name": "x"}).status_code == 422
    assert client.get("/api/v1/assessment/draft",
                      headers=admin_headers).json()["state"] is None


def test_saving_a_draft_is_audited(client, admin_headers):
    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload())
    actions = [r["action"] for r in
               client.get("/api/v1/admin/audit-logs?limit=10",
                          headers=admin_headers).json()]
    assert "draft.saved" in actions


def test_clearing_discards_the_draft(client, admin_headers):
    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload())
    assert client.delete("/api/v1/assessment/draft",
                         headers=admin_headers).status_code == 204
    assert client.get("/api/v1/assessment/draft",
                      headers=admin_headers).json()["state"] is None


def test_drafts_are_scoped_to_the_organization(client, admin_headers,
                                               auth_headers, make_user):
    from app.models.user import Role

    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload())
    outsider = make_user(email="other@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")
    assert client.get("/api/v1/assessment/draft",
                      headers=other).json()["state"] is None


def test_a_working_draft_downloads_while_incomplete(client, admin_headers):
    """The document that tells an author what is missing cannot require that
    nothing is missing."""
    response = client.post(
        "/api/v1/assessment/project-description?strip_guidance=false",
        headers=admin_headers, json=_draft_payload())
    assert response.status_code == 200
    assert response.content[:2] == b"PK"


def test_the_submission_copy_still_refuses_when_incomplete(client, admin_headers):
    """Stripping Verra's guidance removes the only marks showing which
    sections were never written."""
    response = client.post(
        "/api/v1/assessment/project-description?strip_guidance=true",
        headers=admin_headers, json=_draft_payload())
    assert response.status_code == 422


def test_a_draft_keeps_esg_entries_through_a_rewrite(client, admin_headers):
    """Saving a project without ESG must not be possible to do by accident —
    the caller sends what it holds, so the guard has to be that the stored
    draft is only ever replaced by a complete payload."""
    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload())
    assert len(client.get("/api/v1/assessment/draft",
                          headers=admin_headers).json()["state"]
               ["esg_entries"]) == 1

    # A later save that omits them does overwrite — by design, since the
    # frontend is the source of truth for the working state. The protection
    # against losing them lives in the merge, which is why the test above
    # exists.
    client.put("/api/v1/assessment/draft", headers=admin_headers,
               json=_draft_payload(esg_entries=[]))
    assert client.get("/api/v1/assessment/draft",
                      headers=admin_headers).json()["state"]["esg_entries"] == []
