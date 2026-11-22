"""Zero cross-Collection leaks (#80; PRD milestone M3: "automated tests prove zero
cross-collection leaks").

One world: Team A (Alice owns it; an Editor, a Viewer, and a Member removed since) and Team B
(Bob's, holding a secret), plus a stranger. Every API endpoint is called as each kind of User,
and each sees only what their Membership allows. A new endpoint without a place here fails
`test_every_endpoint_is_covered`.
"""

from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from test_answers import LEAVE, QUOTES, MemoryStore, ScriptedModel, WordsEmbedder, sse_events

from docent_api import main
from docent_api.auth import AuthUser, current_user
from docent_api.collection_settings import create_collection
from docent_api.db import get_connection
from docent_api.documents import finish_upload, start_upload
from docent_api.ingestion import run_batch
from docent_api.invites import invite
from docent_api.library import ensure_user, list_collections
from docent_api.storage import get_file_store

SECRET = b"""# Leave for the board

Board members carry over up to 40 days of leave. Code word: PERIWINKLE.
"""

# Endpoints that hold no Collection's data: health checks, the scheduler's own trigger
# (authenticated by its token, tested in test_documents), and starting an ingestion batch
# (it reports only counts).
EXEMPT = {
    ("GET", "/health"),
    ("GET", "/health/database"),
    ("POST", "/ingestion/scheduled"),
    ("POST", "/ingestion/run"),
}

# Every other endpoint, and the test that covers it.
COVERED = {
    ("GET", "/me"): "test_reads",
    ("GET", "/documents"): "test_reads",
    ("GET", "/passages/{chunk_id}"): "test_reads",
    ("GET", "/conversations"): "test_reads",
    ("GET", "/conversations/{conversation_id}"): "test_reads",
    ("GET", "/collections/{collection_id}/members"): "test_reads",
    ("GET", "/collections/{collection_id}/invites"): "test_reads",
    ("POST", "/answers"): "test_answers_never_cross_collections",
    ("POST", "/documents"): "test_outsiders_change_nothing",
    ("POST", "/documents/{document_id}/uploaded"): "test_outsiders_change_nothing",
    ("POST", "/documents/{document_id}/retry"): "test_outsiders_change_nothing",
    ("PATCH", "/documents/{document_id}"): "test_outsiders_change_nothing",
    ("DELETE", "/documents/{document_id}"): "test_outsiders_change_nothing",
    ("POST", "/documents/{document_id}/move"): "test_outsiders_change_nothing",
    ("POST", "/collections"): "test_outsiders_change_nothing",
    ("PATCH", "/collections/{collection_id}"): "test_outsiders_change_nothing",
    ("DELETE", "/collections/{collection_id}"): "test_outsiders_change_nothing",
    ("POST", "/collections/{collection_id}/invites"): "test_outsiders_change_nothing",
    ("DELETE", "/invites/{invite_id}"): "test_outsiders_change_nothing",
    ("POST", "/invites/{invite_id}/accept"): "test_outsiders_change_nothing",
    ("PATCH", "/collections/{collection_id}/members/{member_id}"): "test_outsiders_change_nothing",
    ("DELETE", "/collections/{collection_id}/members/{member_id}"): (
        "test_outsiders_change_nothing"
    ),
    ("POST", "/collections/{collection_id}/owner"): "test_outsiders_change_nothing",
}

MEMBERS = ("owner", "editor", "viewer")
OUTSIDERS = ("removed", "stranger")


@dataclass
class World:
    users: dict[str, AuthUser]
    team_a: UUID
    team_b: UUID
    doc_a: UUID
    doc_b: UUID
    chunk_a: UUID
    chunk_b: UUID
    invite_a: UUID
    alice_conversation: UUID
    removed_conversation: UUID


@pytest.fixture(autouse=True)
def _pool(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Answering opens its own connections from the pool; point it at the test database."""
    from psycopg_pool import ConnectionPool

    pool = ConnectionPool(
        database_url, min_size=0, max_size=4, kwargs={"row_factory": dict_row}, open=True
    )
    monkeypatch.setattr("docent_api.answers.get_pool", lambda: pool)
    yield
    pool.close()


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from docent_api.settings import get_settings

    monkeypatch.setattr(get_settings(), "decline_below_similarity", 0.0)
    monkeypatch.setattr(main, "embedder", WordsEmbedder)
    monkeypatch.setattr(
        main, "answer_generator", lambda: ScriptedModel(["Up to 10 days [1].", QUOTES])
    )
    yield
    main.app.dependency_overrides.clear()


def a_user(conn: Connection[DictRow], name: str) -> AuthUser:
    user = AuthUser(id=uuid4(), email=f"{name}-{uuid4().hex[:6]}@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


def ingest(
    conn: Connection[DictRow], user: AuthUser, collection_id: UUID, name: str, data: bytes
) -> tuple[UUID, UUID]:
    store = MemoryStore()
    document, target = start_upload(conn, store, user.id, collection_id, name, len(data))
    store.files[target.path] = data
    finish_upload(conn, user.id, document.id)
    conn.commit()
    run_batch(conn, store, WordsEmbedder(), seconds=240)
    row = conn.execute(
        "select id from app.chunks where document_id = %s order by ordinal limit 1",
        (document.id,),
    ).fetchone()
    conn.commit()
    assert row is not None, "ingestion made no passages"
    return document.id, row["id"]


def client_for(database_url: str, user: AuthUser) -> TestClient:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    main.app.dependency_overrides[current_user] = lambda: user
    main.app.dependency_overrides[get_connection] = connection
    main.app.dependency_overrides[get_file_store] = MemoryStore
    return TestClient(main.app)


def ask(client: TestClient, question: str, scope: list[UUID] | None = None) -> list:  # type: ignore[type-arg]
    body: dict[str, object] = {"question": question}
    if scope is not None:
        body["scope"] = [str(s) for s in scope]
    response = client.post("/answers", json=body)
    assert response.status_code == 200, response.text
    return sse_events(response.text)


@pytest.fixture
def world(database_url: str, conn: Connection[DictRow]) -> World:
    users = {
        name: a_user(conn, name)
        for name in ("owner", "editor", "viewer", "removed", "stranger", "bob")
    }
    team_a = create_collection(conn, users["owner"].id, "Team A").id
    team_b = create_collection(conn, users["bob"].id, "Team B").id
    for name in ("editor", "viewer", "removed"):
        role = "editor" if name == "editor" else "viewer"
        conn.execute(
            "insert into app.memberships (collection_id, user_id, role) values (%s, %s, %s)",
            (team_a, users[name].id, role),
        )
    conn.commit()
    doc_a, chunk_a = ingest(conn, users["owner"], team_a, "leave.md", LEAVE)
    doc_b, chunk_b = ingest(conn, users["bob"], team_b, "board-leave.md", SECRET)
    invite_a = invite(conn, users["owner"].id, team_a, "pending@example.com", "viewer").id

    alice = ask(client_for(database_url, users["owner"]), "How much leave carries over?", [team_a])
    removed = ask(
        client_for(database_url, users["removed"]), "How much leave carries over?", [team_a]
    )
    conn.execute(
        "delete from app.memberships where collection_id = %s and user_id = %s",
        (team_a, users["removed"].id),
    )
    conn.commit()
    main.app.dependency_overrides.clear()
    return World(
        users=users,
        team_a=team_a,
        team_b=team_b,
        doc_a=doc_a,
        doc_b=doc_b,
        chunk_a=chunk_a,
        chunk_b=chunk_b,
        invite_a=invite_a,
        alice_conversation=UUID(str(alice[0][1]["conversation_id"])),
        removed_conversation=UUID(str(removed[0][1]["conversation_id"])),
    )


def test_every_endpoint_is_covered() -> None:
    routes = {
        (method, route.path)
        for route in main.app.routes
        if isinstance(route, APIRoute)
        for method in route.methods
    }
    missing = routes - EXEMPT - set(COVERED)
    assert not missing, f"endpoints without leak coverage, add them to test_leaks: {missing}"
    stale = (set(COVERED) | EXEMPT) - routes
    assert not stale, f"covered endpoints that no longer exist: {stale}"


def test_reads(database_url: str, world: World) -> None:
    for kind in (*MEMBERS, *OUTSIDERS):
        member = kind in MEMBERS
        client = client_for(database_url, world.users[kind])

        collections = [UUID(c["id"]) for c in client.get("/me").json()["collections"]]
        assert (world.team_a in collections) == member, kind
        assert world.team_b not in collections, kind

        documents = [UUID(d["id"]) for d in client.get("/documents").json()]
        assert (world.doc_a in documents) == member, kind
        assert world.doc_b not in documents, kind

        assert client.get(f"/passages/{world.chunk_a}").status_code == (200 if member else 404)
        assert client.get(f"/passages/{world.chunk_b}").status_code == 404, kind

        listed = [UUID(c["id"]) for c in client.get("/conversations").json()]
        assert (world.alice_conversation in listed) == (kind == "owner"), kind
        alice = client.get(f"/conversations/{world.alice_conversation}")
        assert alice.status_code == (200 if kind == "owner" else 404), kind

        members = client.get(f"/collections/{world.team_a}/members")
        assert members.status_code == (200 if member else 404), kind
        assert client.get(f"/collections/{world.team_b}/members").status_code == 404, kind

        invites = client.get(f"/collections/{world.team_a}/invites")
        expected = {"owner": 200, "editor": 403, "viewer": 403}.get(kind, 404)
        assert invites.status_code == expected, kind


def test_a_removed_member_keeps_their_answers_but_not_the_passages(
    database_url: str, world: World
) -> None:
    client = client_for(database_url, world.users["removed"])

    saved = client.get(f"/conversations/{world.removed_conversation}").json()
    answer = saved["messages"][1]
    citation = answer["citations"][0]

    assert "10 days" in answer["content"]  # what was read can't be unread
    assert citation["passage"] is None
    assert citation["access_lost"] is True
    assert client.get(f"/passages/{citation['chunk_id']}").status_code == 404
    # Alice, still a Member, sees her passage text.
    owner = client_for(database_url, world.users["owner"])
    hers = owner.get(f"/conversations/{world.alice_conversation}").json()
    assert hers["messages"][1]["citations"][0]["passage"]
    assert hers["messages"][1]["citations"][0]["access_lost"] is False


def test_answers_never_cross_collections(
    database_url: str, world: World, monkeypatch: pytest.MonkeyPatch
) -> None:
    for kind in (*MEMBERS, *OUTSIDERS):
        model = ScriptedModel(["Up to 10 days [1].", QUOTES])
        monkeypatch.setattr(main, "answer_generator", lambda model=model: model)
        client = client_for(database_url, world.users[kind])

        for scope in ([world.team_a], [world.team_b], None):
            events = ask(client, "How much leave carries over, and what is the code word?", scope)
            sent = " ".join(model.prompts)
            assert "PERIWINKLE" not in sent, (kind, scope)
            assert "40 days" not in sent, (kind, scope)
            if kind in OUTSIDERS:
                assert "10 days carries" not in sent, (kind, scope)
            sources = [
                source["document_id"]
                for name, data in events
                if name == "start"
                for source in data.get("sources", [])  # type: ignore[union-attr]
            ]
            assert str(world.doc_b) not in sources, (kind, scope)
            if kind in OUTSIDERS:
                assert str(world.doc_a) not in sources, (kind, scope)

        # Nobody continues someone else's Conversation.
        if kind != "owner":
            response = client.post(
                "/answers",
                json={"question": "And more?", "conversation_id": str(world.alice_conversation)},
            )
            assert response.status_code == 404, kind


def state(conn: Connection[DictRow], world: World) -> dict[str, object]:
    def one(sql: str, *params: object) -> object:
        row = conn.execute(sql, params).fetchone()
        return None if row is None else tuple(row.values())

    snapshot = {
        "collection": one("select name from app.collections where id = %s", world.team_a),
        "document": one(
            "select collection_id, effective_date, status from app.documents where id = %s",
            world.doc_a,
        ),
        "chunks": one(
            "select count(*), min(collection_id::text) from app.chunks where document_id = %s",
            world.doc_a,
        ),
        "members": one(
            "select string_agg(user_id::text || role, ',' order by user_id) from app.memberships "
            "where collection_id = %s",
            world.team_a,
        ),
        "invite": one("select role from app.invites where id = %s", world.invite_a),
    }
    conn.commit()
    return snapshot


def test_outsiders_change_nothing(
    database_url: str, conn: Connection[DictRow], world: World
) -> None:
    before = state(conn, world)
    a, doc, viewer = world.team_a, world.doc_a, world.users["viewer"].id

    for kind in OUTSIDERS:
        outsider = world.users[kind]
        own = list_collections(conn, outsider.id)[0].id
        conn.commit()
        client = client_for(database_url, outsider)
        new_doc = {"collection_id": str(a), "name": "x.md", "size_bytes": 3, "sha256": "0" * 64}
        attempts: list[tuple[str, str, dict[str, object] | None, set[int]]] = [
            ("POST", "/documents", new_doc, {404}),
            ("POST", f"/documents/{doc}/uploaded", None, {404}),
            ("POST", f"/documents/{doc}/retry", None, {404}),
            ("PATCH", f"/documents/{doc}", {"effective_date": "2001-01-01"}, {404}),
            ("DELETE", f"/documents/{doc}", None, {204}),  # "already gone", for them
            ("POST", f"/documents/{doc}/move", {"collection_id": str(own)}, {404}),
            ("PATCH", f"/collections/{a}", {"name": "Taken"}, {404}),
            ("DELETE", f"/collections/{a}", None, {204}),
            (
                "POST",
                f"/collections/{a}/invites",
                {"email": "me@example.com", "role": "editor"},
                {404},
            ),
            ("DELETE", f"/invites/{world.invite_a}", None, {204}),
            ("POST", f"/invites/{world.invite_a}/accept", None, {403}),
            ("PATCH", f"/collections/{a}/members/{viewer}", {"role": "editor"}, {404}),
            ("DELETE", f"/collections/{a}/members/{viewer}", None, {404}),
            ("POST", f"/collections/{a}/owner", {"user_id": str(outsider.id)}, {404}),
        ]
        for method, path, body, allowed in attempts:
            response = client.request(method, path, json=body)
            assert response.status_code in allowed, (kind, method, path, response.text)
            if response.status_code == 403:
                assert "pending@example.com" not in response.text  # masked, not leaked

        # Their own new Collection is theirs alone.
        mine = client.post("/collections", json={"name": "Mine"})
        assert mine.status_code == 201
        assert UUID(mine.json()["id"]) not in [
            c.id for c in list_collections(conn, world.users["owner"].id)
        ]
        conn.commit()

    assert state(conn, world) == before
