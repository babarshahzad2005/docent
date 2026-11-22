"""Moving a Document between Collections, against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import create_collection
from docent_api.db import get_connection
from docent_api.documents import (
    DuplicateDocument,
    NotAllowed,
    NotMovable,
    finish_upload,
    list_documents,
    move_document,
    start_upload,
)
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.retrieval import PassageNotFound, passage_in_context, retrieve
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


def indexed(
    conn: Connection[DictRow],
    store: FakeStore,
    user: AuthUser,
    collection_id: UUID,
    text: str,
    sha256: str | None = None,
) -> tuple[UUID, UUID]:
    """A Ready Document with one passage, as ingestion leaves it; returns both ids."""
    document, target = start_upload(
        conn, store, user.id, collection_id, "carry-over.md", len(text), sha256=sha256
    )
    store.files[target.path] = text.encode()
    finish_upload(conn, user.id, document.id)
    conn.execute("update app.documents set status = 'indexed' where id = %s", (document.id,))
    row = conn.execute(
        """
        insert into app.chunks
            (document_id, collection_id, ordinal, content, content_hash, search)
        values (%s, %s, 0, %s, 'h', to_tsvector('english', %s))
        returning id
        """,
        (document.id, collection_id, text, text),
    ).fetchone()
    conn.commit()
    assert row is not None
    return document.id, row["id"]


def collection_of(conn: Connection[DictRow], document_id: UUID) -> UUID:
    row = conn.execute(
        "select collection_id from app.documents where id = %s", (document_id,)
    ).fetchone()
    conn.commit()
    assert row is not None
    return UUID(str(row["collection_id"]))


def test_a_document_moves_with_its_passages(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    team = create_collection(conn, owner.id, "Team").id
    document_id, chunk_id = indexed(conn, store, owner, personal, "Carry over up to ten days.")

    moved = move_document(conn, owner.id, document_id, team)

    assert moved.collection_id == team
    assert collection_of(conn, document_id) == team
    found = retrieve(conn, owner.id, [team], "carry over days", None)
    assert [p.chunk_id for p in found] == [chunk_id]
    assert retrieve(conn, owner.id, [personal], "carry over days", None) == []
    conn.commit()


def test_after_a_move_only_the_new_collections_members_read_it(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    team = create_collection(conn, owner.id, "Team").id
    other = create_collection(conn, owner.id, "Other").id
    reader = a_user(conn)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (team, reader.id),
    )
    conn.commit()
    document_id, chunk_id = indexed(conn, store, owner, team, "Carry over up to ten days.")
    assert passage_in_context(conn, reader.id, chunk_id)

    move_document(conn, owner.id, document_id, other)
    conn.commit()

    with pytest.raises(PassageNotFound):
        passage_in_context(conn, reader.id, chunk_id)
    assert document_id not in [d.id for d in list_documents(conn, reader.id)]


def test_moving_needs_editor_or_owner_in_both(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    team = create_collection(conn, owner.id, "Team").id
    elsewhere_owner = a_user(conn)
    elsewhere = create_collection(conn, elsewhere_owner.id, "Elsewhere").id
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (elsewhere, owner.id),
    )
    conn.commit()
    document_id, _ = indexed(conn, store, owner, team, "Carry over up to ten days.")

    with pytest.raises(NotAllowed):  # only a Viewer there
        move_document(conn, owner.id, document_id, elsewhere)
    with pytest.raises(NotAllowed):  # not a Member at all
        move_document(conn, owner.id, document_id, create_collection(conn, a_user(conn).id, "X").id)
    assert collection_of(conn, document_id) == team


def test_only_a_settled_document_moves(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    team = create_collection(conn, owner.id, "Team").id
    queued, target = start_upload(conn, store, owner.id, personal, "new.md", 3)
    store.files[target.path] = b"new"
    finish_upload(conn, owner.id, queued.id)
    conn.commit()

    with pytest.raises(NotMovable, match="still being added"):
        move_document(conn, owner.id, queued.id, team)

    ready, _ = indexed(conn, store, owner, personal, "Carry over up to ten days.")
    replacement, upload = start_upload(
        conn, store, owner.id, personal, "carry-over.md", 4, replaces=ready
    )
    store.files[upload.path] = b"next"
    conn.commit()
    with pytest.raises(NotMovable, match="replacement on the way"):
        move_document(conn, owner.id, ready, team)
    assert replacement.id


def test_the_same_content_isnt_moved_in_twice(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    team = create_collection(conn, owner.id, "Team").id
    sha = "a" * 64
    indexed(conn, store, owner, team, "Carry over up to ten days.", sha256=sha)
    twin, _ = indexed(conn, store, owner, personal, "Carry over up to ten days.", sha256=sha)

    with pytest.raises(DuplicateDocument, match="Team collection already has this content"):
        move_document(conn, owner.id, twin, team)


def test_the_demo_collection_is_never_a_source_or_destination(
    conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    row = conn.execute("select id from app.collections where is_demo").fetchone()
    if row is None:
        row = conn.execute(
            "insert into app.collections (name, is_demo) values ('Demo Collection', true) "
            "returning id"
        ).fetchone()
    assert row is not None
    demo = row["id"]
    # Even made an Editor of it by hand, nobody moves Documents in.
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'editor') "
        "on conflict (collection_id, user_id) do update set role = 'editor'",
        (demo, owner.id),
    )
    conn.commit()
    personal = list_collections(conn, owner.id)[0].id
    document_id, _ = indexed(conn, store, owner, personal, "Carry over up to ten days.")

    with pytest.raises(NotAllowed):
        move_document(conn, owner.id, document_id, demo)


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


def test_the_move_endpoint(
    client: TestClient, conn: Connection[DictRow], store: FakeStore, owner: AuthUser
) -> None:
    personal = list_collections(conn, owner.id)[0].id
    team = create_collection(conn, owner.id, "Team").id
    document_id, _ = indexed(conn, store, owner, personal, "Carry over up to ten days.")

    moved = client.post(f"/documents/{document_id}/move", json={"collection_id": str(team)})
    assert (moved.status_code, moved.json()["collection_id"]) == (200, str(team))

    stranger = create_collection(conn, a_user(conn).id, "Theirs").id
    refused = client.post(f"/documents/{document_id}/move", json={"collection_id": str(stranger)})
    assert refused.status_code == 404
    gone = client.post(f"/documents/{uuid4()}/move", json={"collection_id": str(team)})
    assert gone.status_code == 404
