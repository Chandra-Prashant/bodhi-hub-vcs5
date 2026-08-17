"""
Endpoint tests for the document routes.

These exist because they were missing. Two consecutive versions of the delete
route shipped broken — one that would not import, one that raised NameError on
every call — while the suite reported 680 passing. Nothing exercised the route,
so nothing could tell.

The pattern of that failure is worth stating: every one of these routes was
verified once, by hand, at the moment it was written, and never again. A check
that runs once is a check that stops being true the next time somebody edits
the router.
"""

from __future__ import annotations

import json

import pytest

from app.models.user import Role


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _field(value, score=0.96, page=1):
    return {"value": value, "score": score, "source_page": page,
            "source_text": f"the document states {value}"}


CLEAN_EXTRACTION = {
    "project_name": _field("Aligarh Solar One"),
    "proponent": _field("Bodhi Hub Client Private Limited"),
    "country_iso2": _field("IN"),
    "technology": _field("terrestrial solar photovoltaic"),
    "installed_capacity_mw": _field("50"),
    "expected_annual_generation_mwh": _field("87600"),
    "initial_crediting_period_start": _field("01-MAR-2026"),
}


@pytest.fixture
def stub_extractor(monkeypatch):
    """Replace the model with a scripted response.

    Returns a setter so a test can choose what the "model" found. The routes
    call `_extractor()` at request time, so patching it covers every route
    that extracts.
    """
    from app.api import documents as documents_api
    from app.extraction.pipeline import Extractor

    class Stub(Extractor):
        name = "stub"
        response = json.dumps(CLEAN_EXTRACTION)

        def complete(self, system, document_text, image=None, media_type=""):
            return type(self).response

    monkeypatch.setattr(documents_api, "_extractor", lambda: Stub())

    def _set(payload: dict | str):
        Stub.response = payload if isinstance(payload, str) else json.dumps(payload)

    return _set


@pytest.fixture
def local_storage(tmp_path):
    """Keep uploads out of the working tree and away from other tests."""
    from app.services.storage import LocalStorage, set_storage

    set_storage(LocalStorage(tmp_path / "objects"))
    yield
    set_storage(None)


@pytest.fixture
def admin(make_user):
    return make_user(email="admin@bodhihub.com", password="correct-horse-battery",
                     role=Role.ADMIN, organization="Bodhi Hub")


@pytest.fixture
def headers(admin, auth_headers):
    return auth_headers(admin.email, "correct-horse-battery")


def _upload(client, headers, name="project.txt", body=b"Aligarh Solar One, 50 MW."):
    return client.post("/api/v1/documents/upload", headers=headers,
                       files={"file": (name, body, "text/plain")})


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------


def test_upload_requires_authentication(client, local_storage):
    response = client.post("/api/v1/documents/upload",
                           files={"file": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 401


def test_a_clean_upload_is_approved_without_review(
        client, headers, stub_extractor, local_storage):
    response = _upload(client, headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["status"] == "APPROVED"
    assert body["auto_approved"] is True
    assert body["review_items"] == []


def test_a_flagged_upload_needs_review(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    body = _upload(client, headers).json()
    assert body["document"]["status"] == "NEEDS_REVIEW"
    assert any(i["field_name"] == "country_iso2" for i in body["review_items"])


def test_an_unsupported_type_is_rejected(client, headers, local_storage):
    response = client.post(
        "/api/v1/documents/upload", headers=headers,
        files={"file": ("archive.zip", b"\x00\x01", "application/zip")})
    assert response.status_code == 400
    assert "not accepted" in response.json()["detail"]


def test_an_empty_upload_is_rejected(client, headers, local_storage):
    response = client.post("/api/v1/documents/upload", headers=headers,
                           files={"file": ("a.txt", b"", "text/plain")})
    assert response.status_code == 400


def test_the_same_file_cannot_be_uploaded_twice(
        client, headers, stub_extractor, local_storage):
    _upload(client, headers)
    again = _upload(client, headers, name="different-name.txt")
    assert again.status_code == 400
    assert "already been uploaded" in again.json()["detail"]


def test_a_failed_extraction_routes_to_manual_entry(
        client, headers, stub_extractor, local_storage):
    stub_extractor("this is not json")
    body = _upload(client, headers).json()
    assert body["document"]["status"] == "MANUAL_ENTRY"
    assert body["extraction"]["status"] == "FAILED"


# ---------------------------------------------------------------------------
# Listing and scoping
# ---------------------------------------------------------------------------


def test_documents_are_scoped_to_the_organization(
        client, headers, auth_headers, make_user, stub_extractor, local_storage):
    _upload(client, headers)

    outsider = make_user(email="other@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other_headers = auth_headers(outsider.email, "correct-horse-battery")

    assert len(client.get("/api/v1/documents", headers=headers).json()) == 1
    assert client.get("/api/v1/documents", headers=other_headers).json() == []


def test_the_queue_holds_only_pending_items(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)

    queue = client.get("/api/v1/documents/queue", headers=headers).json()
    assert len(queue) == 1
    assert queue[0]["state"] == "PENDING"


def test_the_queue_puts_blocking_items_first(
        client, headers, stub_extractor, local_storage):
    stub_extractor({
        **CLEAN_EXTRACTION,
        "country_iso2": _field("India"),          # ERROR — not an ISO code
        "capex": _field("40000", score=0.75),     # WARNING — low confidence
    })
    _upload(client, headers)

    severities = [i["severity"]
                  for i in client.get("/api/v1/documents/queue",
                                      headers=headers).json()]
    assert severities[0] == "ERROR"
    assert "WARNING" in severities


# ---------------------------------------------------------------------------
# Review
# ---------------------------------------------------------------------------


def _first_queue_item(client, headers):
    return client.get("/api/v1/documents/queue", headers=headers).json()[0]


def test_approving_records_the_decision(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    response = client.post(f"/api/v1/documents/review/{item['id']}",
                           headers=headers, json={"state": "APPROVED"})
    assert response.status_code == 200
    assert response.json()["state"] == "APPROVED"
    assert client.get("/api/v1/documents/queue", headers=headers).json() == []


def test_an_edit_stores_the_correction(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    response = client.post(
        f"/api/v1/documents/review/{item['id']}", headers=headers,
        json={"state": "EDITED", "corrected_value": "IN"})
    assert response.status_code == 200
    assert response.json()["corrected_value"] == "IN"


def test_an_edit_without_a_value_is_rejected(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    response = client.post(f"/api/v1/documents/review/{item['id']}",
                           headers=headers, json={"state": "EDITED"})
    assert response.status_code == 400


def test_a_decision_cannot_be_reopened(
        client, headers, stub_extractor, local_storage):
    """The decision is part of the audit trail."""
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    client.post(f"/api/v1/documents/review/{item['id']}", headers=headers,
                json={"state": "APPROVED"})
    again = client.post(f"/api/v1/documents/review/{item['id']}", headers=headers,
                        json={"state": "REJECTED"})
    assert again.status_code == 409


def test_a_failed_extraction_cannot_be_approved(
        client, headers, stub_extractor, local_storage):
    """Approving it once marked a FAILED extraction APPROVED, so a document
    with two of thirteen fields looked complete."""
    stub_extractor("not json")
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    response = client.post(f"/api/v1/documents/review/{item['id']}",
                           headers=headers, json={"state": "APPROVED"})
    assert response.status_code == 400
    assert "no value to approve" in response.json()["detail"]


def test_a_failed_extraction_can_be_rejected(
        client, headers, stub_extractor, local_storage):
    stub_extractor("not json")
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    response = client.post(f"/api/v1/documents/review/{item['id']}",
                           headers=headers, json={"state": "REJECTED"})
    assert response.status_code == 200


def test_review_items_are_scoped_to_the_organization(
        client, headers, auth_headers, make_user, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)

    outsider = make_user(email="other@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")

    response = client.post(f"/api/v1/documents/review/{item['id']}",
                           headers=other, json={"state": "APPROVED"})
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# Assess
# ---------------------------------------------------------------------------


def _document_id(client, headers):
    return client.get("/api/v1/documents", headers=headers).json()[0]["id"]


def test_assess_runs_on_a_clean_document(
        client, headers, stub_extractor, local_storage):
    _upload(client, headers)
    response = client.post(
        f"/api/v1/documents/{_document_id(client, headers)}/assess",
        headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["assessment"]["project_name"] == "Aligarh Solar One"
    assert body["project"]["country_iso2"] == "IN"


def test_assess_refuses_while_a_blocking_item_is_unresolved(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)

    response = client.post(
        f"/api/v1/documents/{_document_id(client, headers)}/assess",
        headers=headers)
    assert response.status_code == 409
    assert "unresolved" in response.json()["detail"]


def test_a_correction_reaches_the_assessment(
        client, headers, stub_extractor, local_storage):
    """The whole point of the review step. If the correction were ignored, the
    queue would be decorative."""
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    item = _first_queue_item(client, headers)
    client.post(f"/api/v1/documents/review/{item['id']}", headers=headers,
                json={"state": "EDITED", "corrected_value": "IN"})

    body = client.post(
        f"/api/v1/documents/{_document_id(client, headers)}/assess",
        headers=headers).json()
    assert body["project"]["country_iso2"] == "IN"
    assert "country_iso2" in body["corrections_applied"]


def test_assess_is_scoped_to_the_organization(
        client, headers, auth_headers, make_user, stub_extractor, local_storage):
    _upload(client, headers)
    document_id = _document_id(client, headers)

    outsider = make_user(email="other@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")

    response = client.post(f"/api/v1/documents/{document_id}/assess",
                           headers=other)
    assert response.status_code == 409  # no extraction visible to them


# ---------------------------------------------------------------------------
# Delete — the route that shipped broken twice
# ---------------------------------------------------------------------------


def test_delete_removes_the_document(
        client, headers, stub_extractor, local_storage):
    _upload(client, headers)
    document_id = _document_id(client, headers)

    response = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert response.status_code == 204
    assert response.content == b""
    assert client.get("/api/v1/documents", headers=headers).json() == []


def test_deleting_twice_returns_not_found(
        client, headers, stub_extractor, local_storage):
    _upload(client, headers)
    document_id = _document_id(client, headers)

    client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    again = client.delete(f"/api/v1/documents/{document_id}", headers=headers)
    assert again.status_code == 404


def test_delete_requires_authentication(client, local_storage):
    import uuid

    response = client.delete(f"/api/v1/documents/{uuid.uuid4()}")
    assert response.status_code == 401


def test_project_managers_cannot_delete(
        client, headers, auth_headers, make_user, stub_extractor, local_storage):
    _upload(client, headers)
    document_id = _document_id(client, headers)

    manager = make_user(email="pm@bodhihub.com", password="correct-horse-battery",
                        role=Role.PROJECT_MANAGER, organization="Bodhi Hub")
    pm_headers = auth_headers(manager.email, "correct-horse-battery")

    response = client.delete(f"/api/v1/documents/{document_id}",
                             headers=pm_headers)
    assert response.status_code == 403


def test_delete_is_scoped_to_the_organization(
        client, headers, auth_headers, make_user, stub_extractor, local_storage):
    _upload(client, headers)
    document_id = _document_id(client, headers)

    outsider = make_user(email="other@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")

    assert client.delete(f"/api/v1/documents/{document_id}",
                         headers=other).status_code == 404
    assert len(client.get("/api/v1/documents", headers=headers).json()) == 1


def test_deleting_removes_the_review_items_too(
        client, headers, stub_extractor, local_storage):
    stub_extractor({**CLEAN_EXTRACTION, "country_iso2": _field("India")})
    _upload(client, headers)
    assert client.get("/api/v1/documents/queue", headers=headers).json()

    client.delete(f"/api/v1/documents/{_document_id(client, headers)}",
                  headers=headers)
    assert client.get("/api/v1/documents/queue", headers=headers).json() == []


def test_the_audit_trail_survives_the_deletion(
        client, headers, stub_extractor, local_storage):
    """A compliance system that can erase its own history is not one. The audit
    rows store the resource id as a string, not a foreign key, so the record of
    upload, extraction and deletion outlives its subject."""
    _upload(client, headers)
    client.delete(f"/api/v1/documents/{_document_id(client, headers)}",
                  headers=headers)

    actions = [row["action"] for row in
               client.get("/api/v1/admin/audit-logs?limit=20",
                          headers=headers).json()]
    assert "document.deleted" in actions
    assert "ingest.document_uploaded" in actions


def test_the_extraction_endpoint_reports_a_missing_document(client, headers):
    import uuid

    response = client.get(f"/api/v1/documents/{uuid.uuid4()}/extraction",
                          headers=headers)
    assert response.status_code == 404


def test_a_bad_upload_is_refused_without_a_model_configured(client, headers,
                                                            local_storage):
    """The upload gate must not depend on the model. Reporting "no extraction
    model configured" for a .zip sends whoever is debugging it to the wrong
    place — and it is what these tests found on their first run."""
    response = client.post(
        "/api/v1/documents/upload", headers=headers,
        files={"file": ("archive.zip", b"\x00\x01", "application/zip")})
    assert response.status_code == 400
    assert "not accepted" in response.json()["detail"]
