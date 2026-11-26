"""What each Role may do, through the API (GLOSSARY: Owner, Editor, Viewer; #78).

Viewers only ask and read. Editors also add, Replace, and delete Documents and change their
Effective Dates. Only the Owner manages the Collection, its invites, and its Members. Each
refusal is a 403 that says, in plain words, who can.
"""

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.api_keys import create_api_key
from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import create_collection
from docent_api.db import get_connection
from docent_api.documents import finish_upload, start_upload
from docent_api.library import ensure_user
from docent_api.main import app
from docent_api.storage import SignedUpload, get_file_store

SHA = "0" * 64


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


def a_user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"{uuid4().hex[:8]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


class Team:
    """A Collection with an Owner, an Editor, a Viewer, and one queued Document."""

    def __init__(self, conn: Connection[DictRow], store: FakeStore) -> None:
        self.owner, self.editor, self.viewer = a_user(conn), a_user(conn), a_user(conn)
        self.other = a_user(conn)  # whom the Owner-only actions are tried on
        self.id = create_collection(conn, self.owner.id, "Team").id
        members = ((self.editor, "editor"), (self.viewer, "viewer"), (self.other, "viewer"))
        for user, role in members:
            conn.execute(
                "insert into app.memberships (collection_id, user_id, role) values (%s, %s, %s)",
                (self.id, user.id, role),
            )
        document, target = start_upload(conn, store, self.owner.id, self.id, "policy.md", 5)
        store.files[target.path] = b"hello"
        finish_upload(conn, self.owner.id, document.id)
        conn.commit()
        self.document = document.id
        self.api_key = create_api_key(conn, self.owner.id, self.id, "Site").key.id


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def team(conn: Connection[DictRow], store: FakeStore) -> Team:
    return Team(conn, store)


@pytest.fixture(autouse=True)
def _clear_overrides() -> Iterator[None]:
    yield
    app.dependency_overrides.clear()


def as_user(database_url: str, store: FakeStore, user: AuthUser) -> TestClient:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[get_file_store] = lambda: store
    return TestClient(app)


def new_document(collection: UUID) -> dict[str, object]:
    return {"collection_id": str(collection), "name": "new.md", "size_bytes": 3, "sha256": SHA}


# Every action that changes Documents: (method, path, body), for a Team.
def document_actions(team: Team) -> list[tuple[str, str, dict[str, object] | None]]:
    doc = team.document
    return [
        ("POST", "/documents", new_document(team.id)),
        ("POST", "/documents", {**new_document(team.id), "replaces": str(doc)}),
        ("POST", f"/documents/{doc}/uploaded", None),
        ("POST", f"/documents/{doc}/retry", None),
        ("PATCH", f"/documents/{doc}", {"effective_date": "2024-01-01"}),
        ("DELETE", f"/documents/{doc}", None),
    ]


# Every action only the Owner may take.
def owner_actions(team: Team) -> list[tuple[str, str, dict[str, object] | None]]:
    viewer = team.other.id
    return [
        ("PATCH", f"/collections/{team.id}", {"name": "Mine now"}),
        ("DELETE", f"/collections/{team.id}", None),
        ("GET", f"/collections/{team.id}/invites", None),
        ("POST", f"/collections/{team.id}/invites", {"email": "x@example.com", "role": "viewer"}),
        ("PATCH", f"/collections/{team.id}/members/{viewer}", {"role": "editor"}),
        ("DELETE", f"/collections/{team.id}/members/{viewer}", None),
        ("POST", f"/collections/{team.id}/owner", {"user_id": str(viewer)}),
        ("PUT", f"/collections/{team.id}/public", {"public": True}),
        ("GET", f"/collections/{team.id}/api-keys", None),
        ("POST", f"/collections/{team.id}/api-keys", {"name": "Site"}),
        ("DELETE", f"/api-keys/{team.api_key}", None),
    ]


def call(client: TestClient, action: tuple[str, str, dict[str, object] | None]) -> tuple[int, str]:
    method, path, body = action
    response = client.request(method, path, json=body)
    detail = response.json().get("detail", "") if response.content else ""
    return response.status_code, str(detail)


def test_viewers_change_no_documents_and_hear_why(
    database_url: str, store: FakeStore, team: Team
) -> None:
    viewer = as_user(database_url, store, team.viewer)

    for action in document_actions(team):
        status, detail = call(viewer, action)
        assert status == 403, action
        assert "owner and editors" in detail, action
        assert "make you an editor" in detail, action


def test_editors_change_documents(database_url: str, store: FakeStore, team: Team) -> None:
    editor = as_user(database_url, store, team.editor)

    assert call(editor, ("POST", "/documents", new_document(team.id)))[0] == 201
    dated = ("PATCH", f"/documents/{team.document}", {"effective_date": "2024-01-01"})
    assert call(editor, dated)[0] == 200
    assert call(editor, ("DELETE", f"/documents/{team.document}", None))[0] == 204


@pytest.mark.parametrize("who", ["editor", "viewer"])
def test_only_the_owner_manages_the_collection(
    database_url: str, store: FakeStore, team: Team, who: str
) -> None:
    client = as_user(database_url, store, getattr(team, who))

    for action in owner_actions(team):
        status, detail = call(client, action)
        assert status == 403, action
        assert detail.startswith("Only the collection’s owner can do that."), action
    # Still a Member after all that, and free to leave.
    leave = ("DELETE", f"/collections/{team.id}/members/{getattr(team, who).id}", None)
    assert call(client, leave)[0] == 204


def test_someone_removed_hears_they_have_no_access_not_how_to_edit(
    database_url: str, conn: Connection[DictRow], store: FakeStore, team: Team
) -> None:
    conn.execute(
        "delete from app.memberships where collection_id = %s and user_id = %s",
        (team.id, team.editor.id),
    )
    conn.commit()
    editor = as_user(database_url, store, team.editor)

    status, detail = call(editor, ("POST", "/documents", new_document(team.id)))

    assert status == 404
    assert "no longer have access" in detail


def test_everyone_reads_and_asks(database_url: str, store: FakeStore, team: Team) -> None:
    for user in (team.owner, team.editor, team.viewer):
        client = as_user(database_url, store, user)
        listed = client.get("/documents").json()
        assert team.document in [UUID(d["id"]) for d in listed]
        assert client.get(f"/collections/{team.id}/members").status_code == 200
