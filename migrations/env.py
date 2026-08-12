from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool
from app.core.config import settings
from app.core.database import Base
from app.models import user as _user  # noqa: F401  (registers tables)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to) -> bool:
    """Restrict autogenerate to tables we actually declare.

    PostGIS installs several dozen of its own tables (spatial_ref_sys,
    topology, layer, and the whole tiger geocoder). They are visible on the
    search_path, so without this filter Alembic reflects them, finds no
    matching model, and generates drop_table for every one of them.
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
    # Build the engine directly from settings rather than via
    # config.set_main_option: Alembic runs that value through configparser,
    # which interprets '%' as interpolation syntax and chokes on
    # percent-encoded credentials.
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
