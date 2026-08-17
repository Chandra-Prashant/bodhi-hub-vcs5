"""
Storage backend tests.

The key-generation tests matter most: a storage key built from a user-supplied
filename is how a path traversal becomes an overwrite of another
organization's document.
"""

from __future__ import annotations

import pytest

from app.services.storage import (
    LocalStorage,
    Storage,
    StorageError,
    get_storage,
    set_storage,
)


@pytest.fixture
def storage(tmp_path) -> LocalStorage:
    return LocalStorage(tmp_path / "objects")


@pytest.fixture(autouse=True)
def _reset_backend():
    yield
    set_storage(None)


# --- round trip ------------------------------------------------------------

def test_content_survives_a_round_trip(storage):
    key = storage.put(storage.new_key("Bodhi Hub", "a.pdf"), b"hello")
    assert storage.get(key) == b"hello"


def test_exists_reports_accurately(storage):
    key = storage.put(storage.new_key("Bodhi Hub", "a.pdf"), b"x")
    assert storage.exists(key)
    assert not storage.exists("org/does-not-exist.pdf")


def test_reading_a_missing_object_raises(storage):
    with pytest.raises(StorageError, match="No stored object"):
        storage.get("org/missing.pdf")


def test_binary_content_is_unchanged(storage):
    blob = bytes(range(256))
    key = storage.put(storage.new_key("Bodhi Hub", "a.png"), blob)
    assert storage.get(key) == blob


# --- keys are generated, never derived from a filename --------------------

@pytest.mark.parametrize("filename", [
    "../../etc/passwd", "..\\..\\windows\\system32", "a/b/c.pdf",
    "report;rm -rf ~.pdf",
])
def test_a_dangerous_filename_never_reaches_the_key(storage, filename):
    key = storage.new_key("Bodhi Hub", filename)
    assert ".." not in key
    assert key.count("/") == 1        # exactly the organization separator


def test_keys_are_unique_for_identical_filenames(storage):
    """Two uploads of report.pdf must not overwrite each other."""
    keys = {storage.new_key("Bodhi Hub", "report.pdf") for _ in range(50)}
    assert len(keys) == 50


def test_the_suffix_is_preserved(storage):
    """The extractor dispatches on it — a PDF stored without .pdf is refused
    as an unsupported type."""
    assert storage.new_key("Bodhi Hub", "report.PDF").endswith(".pdf")


def test_the_organization_prefixes_the_key(storage):
    assert storage.new_key("Bodhi Hub", "a.pdf").startswith("BodhiHub/")


def test_an_organization_name_cannot_escape_its_prefix(storage):
    key = storage.new_key("../other-org", "a.pdf")
    assert ".." not in key


def test_traversal_in_a_locator_is_refused(storage):
    """Keys are generated, but a future caller passing one through should not
    be able to read outside the root."""
    with pytest.raises(StorageError, match="outside the storage root"):
        storage.get("../../../etc/passwd")


# --- backend selection -----------------------------------------------------

def test_local_is_the_default(monkeypatch):
    monkeypatch.setenv("STORAGE_BACKEND", "local")
    from app.core import config
    import importlib

    config.get_settings.cache_clear()
    importlib.reload(config)
    set_storage(None)
    assert get_storage().name == "local"


def test_an_unknown_backend_is_refused(monkeypatch):
    import importlib

    from app.core import config

    monkeypatch.setenv("STORAGE_BACKEND", "dropbox")
    config.get_settings.cache_clear()
    importlib.reload(config)
    import app.services.storage as storage_module

    importlib.reload(storage_module)
    storage_module.set_storage(None)
    with pytest.raises(storage_module.StorageError, match="Unknown STORAGE_BACKEND"):
        storage_module.get_storage()


def test_s3_without_a_bucket_is_refused(monkeypatch):
    import importlib

    from app.core import config

    monkeypatch.setenv("STORAGE_BACKEND", "s3")
    monkeypatch.setenv("S3_BUCKET", "")
    config.get_settings.cache_clear()
    importlib.reload(config)
    import app.services.storage as storage_module

    importlib.reload(storage_module)
    storage_module.set_storage(None)
    with pytest.raises(storage_module.StorageError, match="S3_BUCKET is not set"):
        storage_module.get_storage()


def test_the_backend_is_built_once(storage):
    set_storage(storage)
    assert get_storage() is get_storage()


def test_every_backend_implements_the_contract():
    for method in ("put", "get", "exists", "new_key"):
        assert hasattr(Storage, method)
