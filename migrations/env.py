"""
Alembic environment.

Three things here are load-bearing, and each was learned from a failure. They
are commented rather than left bare because all three have been lost once to a
file being overwritten, and a bare line gives the next person no reason not to
"simplify" it away.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool

from app.core.config import settings
from app.core.database import Base

# Importing the model modules is what registers their tables on Base.metadata.
# A module missing from this list is invisible to autogenerate, which produces
# an empty migration rather than an error.
from app.models import ingestion as _ingestion  # noqa: F401
from app.models import user as _user  # noqa: F401

config = context.config

# NOTE: config.set_main_option("sqlalchemy.url", ...) is deliberately NOT used.
# Alembic passes that value through configparser, which treats '%' as
# interpolation syntax — so a percent-encoded password (Umesh%40921) raises
# "invalid interpolation syntax". The engine is built directly from settings in
# run_migrations_online instead.

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def include_object(object, name, type_, reflected, compare_to) -> bool:
    """Restrict autogenerate to tables this application declares.

    PostGIS installs several dozen tables of its own — spatial_ref_sys,
    topology, layer, and the entire tiger geocoder. They sit on the search_path,
    so without this filter Alembic reflects them, finds no matching model, and
    generates drop_table for every one of them. Applying that migration would
    delete the geocoder.
    """
    if type_ == "table":
        return name in target_metadata.tables

    parent = getattr(object, "table", None)
    if parent is not None and parent.name not in target_metadata.tables:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
        include_object=include_object,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # Built directly from settings rather than via config.set_main_option —
    # see the note above about configparser and percent-encoded passwords.
    connectable = create_engine(settings.database_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_object=include_object,
            include_schemas=False,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
