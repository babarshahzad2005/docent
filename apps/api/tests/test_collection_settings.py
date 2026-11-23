"""Creating, renaming, and deleting Collections, against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import (
    BadName,
    CollectionNotFound,
    FixedCollection,
    NotOwner,
    create_collection,
    delete_collection,
    rename_collection,
)
from docent_api.db import get_connection
from docent_api.documents import finish_upload, start_upload
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.storage import SignedUpload, get_file_store


class FakeStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def signed_upload(self, path: str) -> SignedUpload:
        return SignedUpload(bucket="documents", path=path, token="token")

    def download(self, path: str) -> bytes:
        return self.files[path]

    def delete(self, paths: Sequence[str]) -> None:
        for path in paths:
            self.files.pop(path, None)


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


def a_user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"{uuid4().hex[:8]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


@pytest.fixture
def owner(conn: Connection[DictRow]) -> AuthUser:
    return a_user(conn)


def add_member(conn: Connection[DictRow], collection_id: UUID, user: AuthUser, role: str) -> None:
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, %s)",
        (collection_id, user.id, role),
    )
    conn.commit()


def count(conn: Connection[DictRow], sql: str, *params: object) -> int:
    row = conn.execute(f"select count(*) as n from {sql}", params).fetchone()
    conn.commit()
    assert row is not None
    return int(row["n"])


def test_a_new_collection_is_empty_and_owned_by_its_creator(
    conn: Connection[DictRow], owner: AuthUser
) -> None:
    created = create_collection(conn, owner.id, "  HR   policies ")

    assert (created.name, created.role, created.is_personal) == ("HR policies", "owner", False)
    names = [(c.name, c.role) for c in list_collections(conn, owner.id)]
    assert ("HR policies", "owner") in names
    assert count(conn, "app.documents where collection_id = %s", created.id) == 0


@pytest.mark.parametrize("name", ["", "   ", "\x00\x01", "x" * 121])
def test_a_collection_needs_a_sensible_name(
    conn: Connection[DictRow], owner: AuthUser, name: str
) -> None:
    with pytest.raises(BadName):
        create_collection(conn, owner.id, name)


def test_the_owner_renames_it(conn: Connection[DictRow], owner: AuthUser) -> None:
    created = create_collection(conn, owner.id, "Drafts")

    rename_collection(conn, owner.id, created.id, "Final")

    assert "Final" in [c.name for c in list_collections(conn, owner.id)]


def test_only_the_owner_renames_or_deletes(
    conn: Connection[DictRow], owner: AuthUser, store: FakeStore
) -> None:
    created = create_collection(conn, owner.id, "Shared")
    editor, stranger = a_user(conn), a_user(conn)
    add_member(conn, created.id, editor, "editor")

    with pytest.raises(NotOwner):
        rename_collection(conn, editor.id, created.id, "Mine now")
    with pytest.raises(NotOwner):
        delete_collection(conn, store, editor.id, created.id)
    # A stranger can't even tell it exists.
    with pytest.raises(CollectionNotFound):
        rename_collection(conn, stranger.id, created.id, "Mine now")
    with pytest.raises(CollectionNotFound):
        delete_collection(conn, store, stranger.id, created.id)


def test_the_personal_collection_stays(
    conn: Connection[DictRow], owner: AuthUser, store: FakeStore
) -> None:
    personal = list_collections(conn, owner.id)[0]
    assert personal.is_personal

    with pytest.raises(FixedCollection):
        rename_collection(conn, owner.id, personal.id, "Other")
    with pytest.raises(FixedCollection):
        delete_collection(conn, store, owner.id, personal.id)


def test_the_demo_collection_stays(
    conn: Connection[DictRow], owner: AuthUser, store: FakeStore
) -> None:
    row = conn.execute("select id from app.collections where is_demo").fetchone()
    if row is None:
        row = conn.execute(
            "insert into app.collections (name, is_demo, public) "
            "values ('Demo Collection', true, true) "
            "returning id"
        ).fetchone()
    assert row is not None
    demo = row["id"]
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer') "
        "on conflict do nothing",
        (demo, owner.id),
    )
    conn.commit()

    # Every User is its Viewer: it has no Owner to rename or delete it.
    with pytest.raises(NotOwner):
        rename_collection(conn, owner.id, demo, "Mine")
    with pytest.raises(NotOwner):
        delete_collection(conn, store, owner.id, demo)


def test_deleting_removes_its_documents_files_and_memberships(
    conn: Connection[DictRow], owner: AuthUser, store: FakeStore
) -> None:
    created = create_collection(conn, owner.id, "Old")
    viewer = a_user(conn)
    add_member(conn, created.id, viewer, "viewer")
    document, target = start_upload(conn, store, owner.id, created.id, "policy.md", 5)
    store.files[target.path] = b"hello"
    finish_upload(conn, owner.id, document.id)
    conn.commit()
    kept, kept_target = start_upload(
        conn, store, owner.id, list_collections(conn, owner.id)[0].id, "keep.md", 4
    )
    store.files[kept_target.path] = b"keep"
    finish_upload(conn, owner.id, kept.id)
    conn.commit()

    delete_collection(conn, store, owner.id, created.id)

    assert count(conn, "app.collections where id = %s", created.id) == 0
    assert count(conn, "app.documents where collection_id = %s", created.id) == 0
    assert count(conn, "app.chunks where document_id = %s", document.id) == 0
    assert count(conn, "app.memberships where collection_id = %s", created.id) == 0
    assert list(store.files) == [kept_target.path]
    assert created.id not in [c.id for c in list_collections(conn, viewer.id)]


# --- HTTP ---------------------------------------------------------------------------------


@pytest.fixture
def client(database_url: str, store: FakeStore, owner: AuthUser) -> Iterator[TestClient]:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: owner
    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[get_file_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_collection_endpoints(client: TestClient, conn: Connection[DictRow]) -> None:
    created = client.post("/collections", json={"name": "Team"})
    assert created.status_code == 201
    collection_id = created.json()["id"]

    assert client.post("/collections", json={"name": " "}).status_code == 400
    renamed = client.patch(f"/collections/{collection_id}", json={"name": "Team handbook"})
    assert (renamed.status_code, renamed.json()["name"]) == (200, "Team handbook")
    assert client.patch(f"/collections/{uuid4()}", json={"name": "x"}).status_code == 404

    assert client.delete(f"/collections/{collection_id}").status_code == 204
    assert client.delete(f"/collections/{collection_id}").status_code == 204  # harmless again
    assert count(conn, "app.collections where id = %s", UUID(collection_id)) == 0


def test_the_personal_collection_cant_be_deleted_over_http(
    client: TestClient, conn: Connection[DictRow], owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    conn.commit()

    response = client.delete(f"/collections/{personal}")

    assert response.status_code == 409
    assert "can’t be renamed or deleted" in response.json()["detail"]
