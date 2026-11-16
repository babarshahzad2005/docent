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
        # The version table lives in the private schema too: `public` is reachable through
        # Supabase's Data API (ADR 0009). Databases migrated before this moved are moved once.
        connection.exec_driver_sql("create schema if not exists app")
        connection.exec_driver_sql(
            """
            do $$ begin
              if to_regclass('public.alembic_version') is not null
                 and to_regclass('app.alembic_version') is null then
                alter table public.alembic_version set schema app;
              end if;
            end $$;
            """
        )
        connection.commit()
        context.configure(connection=connection, version_table_schema="app")
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
