"""Alembic migration environment."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool, text

from revvix_scout.config import get_settings
from revvix_scout.db import models as _models  # noqa: F401
from revvix_scout.db.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database_url.replace("%", "%%"))
target_metadata = Base.metadata


def include_name(name: str | None, type_: str, parent_names: dict[str, str | None]) -> bool:
    """Keep autogeneration scoped to Scout, never Supabase-managed schemas."""

    if type_ == "schema":
        return name == "scout"
    return parent_names.get("schema_name") in (None, "scout")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        compare_type=True,
        version_table_schema="scout_internal",
        include_name=include_name,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        # Keep Alembic metadata out of Supabase's exposed public schema. The
        # conditional move upgrades existing local databases created by M2A.
        with connection.begin():
            connection.execute(text("create schema if not exists scout_internal"))
            connection.execute(text("revoke all on schema scout_internal from public"))
            public_version_exists = connection.scalar(
                text("select to_regclass('public.alembic_version') is not null")
            )
            internal_version_exists = connection.scalar(
                text("select to_regclass('scout_internal.alembic_version') is not null")
            )
            if public_version_exists and not internal_version_exists:
                connection.execute(
                    text("alter table public.alembic_version set schema scout_internal")
                )
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_schemas=True,
            compare_type=True,
            version_table_schema="scout_internal",
            include_name=include_name,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
