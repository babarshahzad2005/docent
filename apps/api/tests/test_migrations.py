import psycopg

from docent_api.migrate import upgrade


def test_every_application_table_is_private_and_locked(database_url: str) -> None:
    with psycopg.connect(database_url) as conn:
        rows = conn.execute(
            """
            select c.relname, n.nspname, c.relrowsecurity
            from pg_class c join pg_namespace n on n.oid = c.relnamespace
            where c.relname in ('users', 'collections', 'memberships', 'alembic_version')
              and c.relkind = 'r' and n.nspname in ('app', 'public')
            """
        ).fetchall()

    assert sorted(rows) == [
        ("alembic_version", "app", True),
        ("collections", "app", True),
        ("memberships", "app", True),
        ("users", "app", True),
    ]


def test_a_database_from_before_the_version_table_moved_upgrades_in_place(
    database_url: str,
) -> None:
    # Recreate the earlier layout: version table in `public`, at revision 0001.
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("alter table app.alembic_version disable row level security")
        conn.execute("alter table app.alembic_version set schema public")
        conn.execute("update public.alembic_version set version_num = '0001'")

    upgrade(database_url)

    with psycopg.connect(database_url) as conn:
        legacy = conn.execute("select to_regclass('public.alembic_version')").fetchone()
        version = conn.execute("select version_num from app.alembic_version").fetchone()
    assert legacy is not None and legacy[0] is None
    assert version is not None and version[0] == "0002"
