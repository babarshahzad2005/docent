"""Shared fixtures. Database tests need TEST_DATABASE_URL (a disposable Postgres with pgvector).

CI provides one; locally they are skipped unless you point TEST_DATABASE_URL at a throwaway
database. Never point it at a database you care about: the schema is dropped and recreated.
"""

import os
from collections.abc import Iterator

import psycopg
import pytest
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.migrate import upgrade

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL", "")


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL is not set")
    with psycopg.connect(TEST_DATABASE_URL, autocommit=True) as conn:
        conn.execute("drop schema if exists app cascade")  # includes app.alembic_version
        conn.execute("drop table if exists public.alembic_version")  # the earlier location
    upgrade(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


@pytest.fixture
def conn(database_url: str) -> Iterator[Connection[DictRow]]:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        yield connection
        connection.execute(
            "truncate app.answer_logs, app.citations, app.messages, app.conversations, "
            "app.chunks, app.documents, app.memberships, app.collections, app.users, "
            "app.storage_deletions"
        )
        connection.execute("update app.ingestion_lease set held_until = '-infinity'")
        connection.commit()
