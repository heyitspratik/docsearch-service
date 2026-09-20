"""Alembic environment setup."""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.clients.db import Base  # noqa: WPS433
from app.settings import settings  # noqa: WPS433

# This is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config  # type: ignore[attr-defined]

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Provide metadata for "autogenerate" support
# from your models here.
# target_metadata = mymodel.Base.metadata
# for more info see the Alembic docs

target_metadata = Base.metadata  # type: ignore[attr-defined]


def run_migrations_offline() -> None:  # noqa: D401
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(  # type: ignore[attr-defined]
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():  # type: ignore[attr-defined]
        context.run_migrations()  # type: ignore[attr-defined]


def run_migrations_online() -> None:  # noqa: D401
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(  # type: ignore[attr-defined]
        config.get_section(config.config_ini_section),  # type: ignore[arg-type]
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:  # type: ignore[attr-defined]
        context.configure(  # type: ignore[attr-defined]
            connection=connection,
            target_metadata=target_metadata,
        )

        with context.begin_transaction():  # type: ignore[attr-defined]
            context.run_migrations()  # type: ignore[attr-defined]


if context.is_offline_mode():  # type: ignore[attr-defined]
    run_migrations_offline()
else:
    run_migrations_online()
