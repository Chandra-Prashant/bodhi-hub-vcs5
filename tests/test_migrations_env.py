"""
Guards on migrations/env.py.

Three fixes live in that file and all three have been lost once to an
overwrite. Reading the source is a crude test, but it is the one that would
have caught both losses — the failures otherwise appear only when someone runs
alembic, which is exactly when they are most expensive.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ENV = Path(__file__).resolve().parents[1] / "migrations" / "env.py"


@pytest.fixture(scope="module")
def source() -> str:
    return ENV.read_text()


def test_set_main_option_is_not_used(source):
    """Alembic routes that value through configparser, which treats '%' as
    interpolation syntax — so a percent-encoded password raises."""
    active = [
        line for line in source.splitlines()
        if "set_main_option" in line and not line.strip().startswith("#")
    ]
    assert not active, (
        "migrations/env.py calls set_main_option. A percent-encoded password "
        "will raise 'invalid interpolation syntax'. Build the engine from "
        "settings.database_url directly."
    )


def test_the_engine_is_built_from_settings(source):
    assert "create_engine(settings.database_url" in source


def test_reflection_is_filtered(source):
    """Without include_object, autogenerate proposes dropping every PostGIS
    tiger table."""
    assert "def include_object" in source
    assert source.count("include_object=include_object") >= 2, (
        "include_object must be passed to both the offline and online "
        "context.configure calls."
    )


def test_every_model_module_is_imported(source):
    """A model module missing here is invisible to autogenerate, which emits an
    empty migration rather than an error."""
    models_dir = ENV.parents[1] / "app" / "models"
    modules = {
        p.stem for p in models_dir.glob("*.py")
        if p.stem != "__init__"
    }
    missing = {m for m in modules if f"import {m} as" not in source}
    assert not missing, (
        f"model module(s) not imported in migrations/env.py: "
        f"{', '.join(sorted(missing))}"
    )
