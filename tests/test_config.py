"""
Configuration tests.

The percent-encoding test exists because the fix has now been lost twice by a
file being shipped over a local edit. A test travels with the file; a manual
patch does not.
"""

from __future__ import annotations

import importlib

import pytest


def _settings(monkeypatch, **env):
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    from app.core import config

    config.get_settings.cache_clear()
    importlib.reload(config)
    return config.settings


@pytest.fixture(autouse=True)
def _restore():
    yield
    from app.core import config

    config.get_settings.cache_clear()
    importlib.reload(config)


@pytest.mark.parametrize("password", [
    "Umesh@921", "p:ss@word", "a/b#c", "with space", "100%sure",
])
def test_special_characters_in_the_password_do_not_break_the_host(
        monkeypatch, password):
    """An unencoded '@' ends the userinfo section early and everything after it
    is read as the hostname — which fails as a DNS lookup, not as bad auth."""
    settings = _settings(monkeypatch, POSTGRES_PASSWORD=password,
                         POSTGRES_HOST="localhost", POSTGRES_PORT="5432",
                         POSTGRES_DB="bodhi_vcs5")
    url = settings.database_url
    assert url.endswith("@localhost:5432/bodhi_vcs5")


def test_the_url_parses_back_to_the_original_password(monkeypatch):
    from sqlalchemy.engine import make_url

    settings = _settings(monkeypatch, POSTGRES_PASSWORD="Umesh@921")
    assert make_url(settings.database_url).password == "Umesh@921"


def test_a_plain_password_is_unchanged(monkeypatch):
    settings = _settings(monkeypatch, POSTGRES_PASSWORD="simple",
                         POSTGRES_HOST="localhost")
    assert "simple" in settings.database_url
