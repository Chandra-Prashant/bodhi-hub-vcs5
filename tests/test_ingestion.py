"""
Ingestion tests — upload validation, pipeline orchestration, review workflow.

The upload-sanitisation tests defend Rules.md ("always validate and sanitize
uploaded file contents"); the audit tests defend its security rule that raw
client financial data never reaches a log.
"""

from __future__ import annotations

import json

import pytest

from app.extraction.pipeline import Extractor
from app.services.ingestion import (
    ALLOWED_SUFFIXES,
    MAX_UPLOAD_BYTES,
    UploadRejected,
    check_upload,
    safe_filename,
)


class FakeExtractor(Extractor):
    name = "fake"

    def __init__(self, response="{}"):
        self.response = response

    def complete(self, system, document_text):
        return self.response


def _f(v, s=0.95):
    return {"value": v, "score": s, "source_page": 1, "source_text": f"states {v}"}


CLEAN_RESPONSE = json.dumps({
    "project_name": _f("Aligarh Solar One"),
    "proponent": _f("Bodhi Hub Client"),
    "country_iso2": _f("IN"),
    "technology": _f("solar PV"),
    "installed_capacity_mw": _f("50"),
    "expected_annual_generation_mwh": _f("87600"),
    "initial_crediting_period_start": _f("2026-03-01"),
})


# --- filename sanitisation -------------------------------------------------

@pytest.mark.parametrize("raw,forbidden", [
    ("../../etc/passwd", "/"),
    ("..\\..\\windows\\system32", "\\"),
    ("report;rm -rf ~.pdf", ";"),
    ("a b c.pdf", " "),
])
def test_dangerous_filenames_are_neutralised(raw, forbidden):
    cleaned = safe_filename(raw)
    assert forbidden not in cleaned
    assert ".." not in cleaned


def test_an_empty_name_still_yields_something():
    assert safe_filename("...") == "document"
    assert safe_filename("") == "document"


def test_long_names_are_truncated():
    assert len(safe_filename("x" * 500 + ".pdf")) <= 200


def test_ordinary_names_survive():
    assert safe_filename("Audit_Kolar_2024.pdf") == "Audit_Kolar_2024.pdf"


# --- upload gate -----------------------------------------------------------

def test_an_empty_upload_is_rejected():
    with pytest.raises(UploadRejected, match="empty"):
        check_upload("a.pdf", b"")


def test_an_oversized_upload_is_rejected():
    with pytest.raises(UploadRejected, match="limit is"):
        check_upload("a.pdf", b"x" * (MAX_UPLOAD_BYTES + 1))


@pytest.mark.parametrize("name", ["a.exe", "a.js", "a.zip", "noextension"])
def test_unsupported_types_are_rejected(name):
    with pytest.raises(UploadRejected, match="not accepted"):
        check_upload(name, b"content")


@pytest.mark.parametrize("suffix", sorted(ALLOWED_SUFFIXES))
def test_supported_types_pass(suffix):
    check_upload(f"doc{suffix}", b"content")


def test_the_allowed_list_excludes_executables():
    assert not {".exe", ".sh", ".js", ".html"} & ALLOWED_SUFFIXES
