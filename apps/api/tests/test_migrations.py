import psycopg
from alembic import command
from alembic.script import ScriptDirectory

from docent_api.migrate import alembic_config, upgrade

TABLES = [
    "alembic_version",
    "answer_logs",
    "chunks",
    "citations",
    "collections",
    "conversations",
    "documents",
    "ingestion_lease",
    "memberships",
    "messages",
    "storage_deletions",
    "trigger_tokens",
    "users",
]


def head() -> str:
    revision = ScriptDirectory.from_config(alembic_config()).get_current_head()
    assert revision is not None
    return revision


def test_every_application_table_is_private_and_locked(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            select c.relname, n.nspname, c.relrowsecurity
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where c.relkind = 'r' and n.nspname in ('app', 'public')
            order by c.relname
            """
        ).fetchall()

    assert rows == [(table, "app", True) for table in TABLES]


def test_a_database_from_before_the_version_table_moved_upgrades_in_place(
    database_url: str,
) -> None:
    # Recreate the earlier layout: at revision 0001, with the version table in `public`.
    command.downgrade(alembic_config(database_url), "0001")
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("alter table app.alembic_version set schema public")

    upgrade(database_url)

    with psycopg.connect(database_url) as conn:
        legacy = conn.execute("select to_regclass('public.alembic_version')").fetchone()
        version = conn.execute("select version_num from app.alembic_version").fetchone()
    assert legacy is not None and legacy[0] is None
    assert version is not None and version[0] == head()
