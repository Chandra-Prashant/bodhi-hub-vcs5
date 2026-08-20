"""
Projects, document scoping, and what happens when documents disagree.

The conflict tests are the important ones. A project described by ten PDFs will
contain contradictions, and the rule that a contradiction is a finding for a
person rather than a tiebreak for software is the whole design — it is also the
rule most likely to be quietly "improved" later into picking the newest file.
"""

from __future__ import annotations

import json

import pytest

from app.models.user import Role


def _field(value, page=1, score=0.95):
    return {"value": value, "score": score, "source_page": page,
            "source_text": f"the document states {value}"}


BASE = {
    "project_name": _field("Aligarh Solar One"),
    "proponent": _field("Bodhi Hub Client"),
    "country_iso2": _field("IN"),
    "technology": _field("terrestrial solar photovoltaic"),
    "installed_capacity_mw": _field("50"),
    "expected_annual_generation_mwh": _field("87600"),
    "initial_crediting_period_start": _field("01-MAR-2026"),
}


@pytest.fixture
def stub_extractor(monkeypatch):
    from app.api import documents as documents_api
    from app.extraction.pipeline import Extractor

    class Stub(Extractor):
        name = "stub"
        response = json.dumps(BASE)

        def complete(self, system, document_text, image=None, media_type=""):
            return type(self).response

    monkeypatch.setattr(documents_api, "_extractor", lambda: Stub())

    def _set(payload):
        Stub.response = payload if isinstance(payload, str) else json.dumps(payload)

    return _set


@pytest.fixture
def local_storage(tmp_path):
    from app.services.storage import LocalStorage, set_storage

    set_storage(LocalStorage(tmp_path / "objects"))
    yield
    set_storage(None)


@pytest.fixture
def headers(make_user, auth_headers):
    user = make_user(email="proj@bodhihub.com", password="correct-horse-battery",
                     role=Role.ADMIN, organization="Bodhi Hub")
    return auth_headers(user.email, "correct-horse-battery")


def _project(client, headers, name="Aligarh Solar One"):
    response = client.post("/api/v1/projects", headers=headers,
                           json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(client, headers, project_id, name="doc.txt", body=b"Aligarh, 50 MW."):
    return client.post(f"/api/v1/documents/upload?project_id={project_id}",
                       headers=headers,
                       files={"file": (name, body, "text/plain")})


# --- projects --------------------------------------------------------------


def test_a_project_can_be_created_and_listed(client, headers):
    _project(client, headers)
    listed = client.get("/api/v1/projects", headers=headers).json()
    assert [p["name"] for p in listed] == ["Aligarh Solar One"]
    assert listed[0]["document_count"] == 0


def test_duplicate_names_are_refused(client, headers):
    _project(client, headers)
    again = client.post("/api/v1/projects", headers=headers,
                        json={"name": "Aligarh Solar One"})
    assert again.status_code == 409
    assert "already exists" in again.json()["detail"]


def test_projects_are_scoped_to_the_organization(client, headers, auth_headers,
                                                 make_user):
    _project(client, headers)
    outsider = make_user(email="rival@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")
    assert client.get("/api/v1/projects", headers=other).json() == []


def test_another_organizations_project_is_not_found(client, headers,
                                                    auth_headers, make_user):
    """404 rather than 403: whether a project exists elsewhere is not something
    a stranger should be able to learn."""
    project_id = _project(client, headers)
    outsider = make_user(email="rival@rival.com", password="correct-horse-battery",
                         role=Role.ADMIN, organization="Rival Advisory")
    other = auth_headers(outsider.email, "correct-horse-battery")
    assert client.get(f"/api/v1/projects/{project_id}",
                      headers=other).status_code == 404


# --- documents belong to a project ----------------------------------------


def test_documents_are_listed_per_project(client, headers, stub_extractor,
                                          local_storage):
    aligarh = _project(client, headers, "Aligarh Solar One")
    kutch = _project(client, headers, "Kutch Wind Two")

    _upload(client, headers, aligarh, "pim.txt")
    _upload(client, headers, aligarh, "technical.txt", b"Different content.")
    _upload(client, headers, kutch, "kutch.txt", b"Kutch, 60 MW.")

    assert len(client.get(f"/api/v1/documents?project_id={aligarh}",
                          headers=headers).json()) == 2
    assert len(client.get(f"/api/v1/documents?project_id={kutch}",
                          headers=headers).json()) == 1


def test_the_same_file_can_serve_two_projects(client, headers, stub_extractor,
                                              local_storage):
    """A grid study legitimately supports several projects. Refusing the second
    upload would force a rename to work around it."""
    aligarh = _project(client, headers, "Aligarh Solar One")
    kutch = _project(client, headers, "Kutch Wind Two")

    assert _upload(client, headers, aligarh, "grid.txt").status_code == 201
    assert _upload(client, headers, kutch, "grid.txt").status_code == 201


def test_the_same_file_is_still_refused_within_one_project(
        client, headers, stub_extractor, local_storage):
    project = _project(client, headers)
    _upload(client, headers, project, "pim.txt")
    again = _upload(client, headers, project, "renamed.txt")
    assert again.status_code == 400


def test_uploading_to_a_missing_project_is_refused(client, headers,
                                                   stub_extractor,
                                                   local_storage):
    import uuid

    assert _upload(client, headers, uuid.uuid4()).status_code == 404


def test_the_queue_shows_only_this_projects_items(client, headers,
                                                  stub_extractor,
                                                  local_storage):
    """A reviewer looking at Aligarh must never be shown a flagged field from
    Kutch."""
    aligarh = _project(client, headers, "Aligarh Solar One")
    kutch = _project(client, headers, "Kutch Wind Two")

    stub_extractor({**BASE, "country_iso2": _field("India")})   # flags
    _upload(client, headers, aligarh, "a.txt")
    stub_extractor(BASE)                                        # clean
    _upload(client, headers, kutch, "k.txt", b"Kutch content.")

    assert client.get(f"/api/v1/documents/queue?project_id={aligarh}",
                      headers=headers).json()
    assert client.get(f"/api/v1/documents/queue?project_id={kutch}",
                      headers=headers).json() == []


# --- merging across documents ---------------------------------------------


def test_values_merge_across_documents_with_provenance(client, headers,
                                                       stub_extractor,
                                                       local_storage):
    project = _project(client, headers)

    # Between them the two documents supply everything required — which is the
    # point: no single file describes a project completely.
    stub_extractor(BASE)
    _upload(client, headers, project, "pim.txt", b"PIM content.")

    stub_extractor({"tariff_per_mwh": _field("0.03", page=8),
                    "capex": _field("40000")})
    _upload(client, headers, project, "financials.txt", b"Financial content.")

    body = client.post(f"/api/v1/projects/{project}/assess",
                       headers=headers).json()
    provenance = body["provenance"]
    assert provenance["installed_capacity_mw"][0]["filename"] == "pim.txt"
    assert provenance["tariff_per_mwh"][0]["filename"] == "financials.txt"
    assert provenance["tariff_per_mwh"][0]["page"] == 8


def test_disagreeing_documents_block_rather_than_choose(client, headers,
                                                        stub_extractor,
                                                        local_storage):
    """The memorandum says 50 MW, the technical report says 49.5. Neither
    "newest wins" nor "highest confidence wins" is defensible — confidence
    measures how clearly a value was read, not whether it is right."""
    project = _project(client, headers)

    stub_extractor({**BASE, "installed_capacity_mw": _field("50")})
    _upload(client, headers, project, "pim.txt", b"PIM content.")

    stub_extractor({**BASE, "installed_capacity_mw": _field("49.5", page=12)})
    _upload(client, headers, project, "technical.txt", b"Technical content.")

    response = client.post(f"/api/v1/projects/{project}/assess", headers=headers)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "disagree" in detail["message"]

    conflict = next(c for c in detail["conflicts"]
                    if c["field"] == "installed_capacity_mw")
    files = {o["filename"] for o in conflict["options"]}
    assert files == {"pim.txt", "technical.txt"}
    assert any(o["page"] == 12 for o in conflict["options"])


def test_formatting_differences_are_not_conflicts(client, headers,
                                                  stub_extractor,
                                                  local_storage):
    """"50" and "50.0" are the same reading. Flagging them would train
    reviewers to dismiss conflicts."""
    project = _project(client, headers)

    stub_extractor({**BASE, "installed_capacity_mw": _field("50")})
    _upload(client, headers, project, "pim.txt", b"PIM content.")

    stub_extractor({**BASE, "installed_capacity_mw": _field("50.0")})
    _upload(client, headers, project, "model.txt", b"Model content.")

    assert client.post(f"/api/v1/projects/{project}/assess",
                       headers=headers).status_code == 200


def test_saved_state_survives_a_project_assessment(client, headers,
                                                   stub_extractor,
                                                   local_storage):
    """ESG entries live only in the saved state — no document contains them —
    so an assessment must not overwrite them with what the documents said."""
    project = _project(client, headers)
    _upload(client, headers, project, "pim.txt")

    client.put(f"/api/v1/projects/{project}/state", headers=headers, json={
        "name": "Aligarh Solar One", "proponent": "Bodhi Hub Client",
        "country_iso2": "IN", "technology": "SOLAR_PV_TERRESTRIAL",
        "installed_capacity_mw": 50.0,
        "expected_annual_generation_mwh": 87600.0,
        "initial_crediting_period_start": "2026-03-01",
        "grid_units": [],
        "esg_entries": [{
            "category": "S2", "risk_id": "S2.1", "severity": 4,
            "likelihood": 3, "description": "Land rights.",
            "justification": "Records incomplete.",
            "mitigation": "Title verification.",
        }],
    })

    stored = client.get(f"/api/v1/projects/{project}",
                        headers=headers).json()["state"]
    assert len(stored["esg_entries"]) == 1


def test_deleting_a_project_takes_its_documents(client, headers,
                                                stub_extractor, local_storage):
    project = _project(client, headers)
    _upload(client, headers, project, "pim.txt")

    assert client.delete(f"/api/v1/projects/{project}",
                         headers=headers).status_code == 204
    assert client.get("/api/v1/projects", headers=headers).json() == []


def test_deleting_a_project_is_audited(client, headers):
    project = _project(client, headers)
    client.delete(f"/api/v1/projects/{project}", headers=headers)
    actions = [r["action"] for r in
               client.get("/api/v1/admin/audit-logs?limit=10",
                          headers=headers).json()]
    assert "project.deleted" in actions
    assert "project.created" in actions
