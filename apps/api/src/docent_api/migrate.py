"""Apply database migrations.

Run locally or in CI with `docent-migrate`. On Vercel this runs as the API's build step and
only migrates for production deployments, so preview deployments never change the
production database.
"""

import os
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def alembic_config(database_url: str | None = None) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS_DIR))
    if database_url:
        config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def upgrade(database_url: str | None = None) -> None:
    command.upgrade(alembic_config(database_url), "head")


def main() -> None:
    vercel_env = os.environ.get("VERCEL_ENV")
    if vercel_env is not None and vercel_env != "production":
        print(f"Skipping migrations for a {vercel_env} deployment.")
        return
    try:
        upgrade()
    except RuntimeError as error:
        sys.exit(f"Migration failed: {error}")
    print("Database is up to date.")


if __name__ == "__main__":
    main()
