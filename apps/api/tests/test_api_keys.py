"""API Keys (#98), against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from test_answers import MemoryStore
from test_documents import FakeStore

from docent_api.api_keys import (
    PREFIX,
    ApiKeyNotFound,
    BadKeyName,
    create_api_key,
    key_hash,
    list_api_keys,
    revoke_api_key,
)
from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import (
    FixedCollection,
    NotOwner,
    create_collection,
    delete_collection,
)
from docent_api.db import get_connection
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.storage import get_file_store


def a_user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"{uuid4().hex[:8]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


@pytest.fixture
def owner(conn: Connection[DictRow]) -> AuthUser:
    return a_user(conn)


@pytest.fixture
def team(conn: Connection[DictRow], owner: AuthUser) -> UUID:
    return create_collection(conn, owner.id, "Team").id


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def as_user(database_url: str, user: AuthUser) -> TestClient:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[get_file_store] = MemoryStore
    return TestClient(app)


def test_a_key_is_shown_once_and_stored_only_as_a_hash(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    created = create_api_key(conn, owner.id, team, "  Help   centre ")

    assert created.secret.startswith(PREFIX)
    assert len(created.secret) > 40
    assert created.key.name == "Help centre"
    assert created.key.last_used_at is None
    row = conn.execute("select * from app.api_keys where id = %s", (created.key.id,)).fetchone()
    conn.commit()
    assert row is not None
    assert bytes(row["key_hash"]) == key_hash(created.secret)
    assert created.secret.encode() not in b"".join(str(value).encode() for value in row.values())
    assert [k.id for k in list_api_keys(conn, owner.id, team)] == [created.key.id]
    conn.commit()
    # Every key is different.
    assert create_api_key(conn, owner.id, team, "Two").secret != created.secret


def test_a_key_needs_a_short_name(conn: Connection[DictRow], owner: AuthUser, team: UUID) -> None:
    with pytest.raises(BadKeyName):
        create_api_key(conn, owner.id, team, "   ")
    with pytest.raises(BadKeyName):
        create_api_key(conn, owner.id, team, "x" * 81)


def test_a_revoked_key_is_kept_but_marked(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    key = create_api_key(conn, owner.id, team, "Site").key

    revoke_api_key(conn, owner.id, key.id)

    assert list_api_keys(conn, owner.id, team) == []
    row = conn.execute("select revoked_at from app.api_keys where id = %s", (key.id,)).fetchone()
    conn.commit()
    assert row is not None and row["revoked_at"] is not None
    with pytest.raises(ApiKeyNotFound):
        revoke_api_key(conn, owner.id, key.id)


def test_only_the_owner_manages_keys(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    editor = a_user(conn)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'editor')",
        (team, editor.id),
    )
    conn.commit()
    key = create_api_key(conn, owner.id, team, "Site").key

    for attempt in (
        lambda: create_api_key(conn, editor.id, team, "Mine"),
        lambda: list_api_keys(conn, editor.id, team),
        lambda: revoke_api_key(conn, editor.id, key.id),
    ):
        with pytest.raises(NotOwner):
            attempt()
    assert len(list_api_keys(conn, owner.id, team)) == 1


def test_the_personal_and_demo_collections_have_no_keys(
    conn: Connection[DictRow], owner: AuthUser
) -> None:
    personal = next(c.id for c in list_collections(conn, owner.id) if c.is_personal)
    demo = conn.execute("select id from app.collections where is_demo").fetchone()
    if demo is None:
        demo = conn.execute(
            "insert into app.collections (name, is_demo, public) "
            "values ('Demo Collection', true, true) returning id"
        ).fetchone()
    assert demo is not None
    # Even made its Owner by hand, nobody gets keys for it.
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'owner') "
        "on conflict (collection_id, user_id) do update set role = 'owner'",
        (demo["id"], owner.id),
    )
    conn.commit()

    for fixed in (personal, demo["id"]):
        with pytest.raises(FixedCollection):
            create_api_key(conn, owner.id, fixed, "Site")
        with pytest.raises(FixedCollection):
            list_api_keys(conn, owner.id, fixed)


def test_deleting_the_collection_removes_its_keys(
    conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    create_api_key(conn, owner.id, team, "Site")

    delete_collection(conn, FakeStore(), owner.id, team)

    row = conn.execute("select count(*) as n from app.api_keys").fetchone()
    conn.commit()
    assert row is not None and row["n"] == 0


def test_the_api_shows_the_secret_only_when_created(
    database_url: str, conn: Connection[DictRow], owner: AuthUser, team: UUID
) -> None:
    client = as_user(database_url, owner)

    created = client.post(f"/collections/{team}/api-keys", json={"name": "Site"})
    assert created.status_code == 201
    secret = created.json()["secret"]
    listed = client.get(f"/collections/{team}/api-keys")
    assert listed.status_code == 200
    assert [k["name"] for k in listed.json()] == ["Site"]
    assert secret not in listed.text
    assert client.post(f"/collections/{team}/api-keys", json={"name": ""}).status_code == 400

    key_id = created.json()["key"]["id"]
    assert client.delete(f"/api-keys/{key_id}").status_code == 204
    assert client.delete(f"/api-keys/{key_id}").status_code == 204  # harmless again
    assert client.get(f"/collections/{team}/api-keys").json() == []
