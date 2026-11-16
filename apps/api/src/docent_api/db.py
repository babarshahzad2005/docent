"""Database connections.

The production database is reached through Supabase's transaction pooler, which does not
support prepared statements, so they are disabled for every connection.
"""

from collections.abc import Iterator
from functools import lru_cache

from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from docent_api.settings import get_settings


def _configure(conn: Connection[DictRow]) -> None:
    conn.prepare_threshold = None


@lru_cache
def get_pool() -> ConnectionPool[Connection[DictRow]]:
    return ConnectionPool(
        get_settings().database_url,
        min_size=0,
        max_size=5,
        open=True,
        configure=_configure,
        # Serverless instances sleep between requests; drop connections that died meanwhile.
        check=ConnectionPool.check_connection,
        kwargs={"row_factory": dict_row},
        connection_class=Connection[DictRow],
    )


def get_connection() -> Iterator[Connection[DictRow]]:
    """FastAPI dependency: one connection per request, committed if the request succeeds."""
    with get_pool().connection() as conn:
        yield conn
