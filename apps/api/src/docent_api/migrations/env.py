"""Alembic environment: runs migrations against DATABASE_URL."""

from alembic import context
from sqlalchemy import create_engine, pool

from docent_api.settings import get_settings


def _sqlalchemy_url(database_url: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if database_url.startswith(prefix):
            return "postgresql+psycopg://" + database_url.removeprefix(prefix)
    return database_url


def run_migrations_online() -> None:
    url = context.config.get_main_option("sqlalchemy.url") or get_settings().database_url
    if not url:
        raise RuntimeError("DATABASE_URL is not set.")
    engine = create_engine(
        _sqlalchemy_url(url),
        poolclass=pool.NullPool,
        # Supabase's transaction pooler doesn't support prepared statements.
        connect_args={"prepare_threshold": None},
    )
    with engine.connect() as connection:
        context.configure(connection=connection, version_table_schema="public")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
