"""Adding Documents and ingesting them, against a real database (TEST_DATABASE_URL)."""

from collections.abc import Iterator, Sequence
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.documents import (
    DocumentNotFound,
    NotAllowed,
    UploadRejected,
    finish_upload,
    list_documents,
    start_upload,
)
from docent_api.ingestion import _claim, run_batch
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.providers.base import Embeddings, Purpose, RateLimited, Usage
from docent_api.storage import FileMissing, SignedUpload, get_file_store

POLICY = b"# Leave\n\n## Carry-over\n\nUp to 10 days.\n\n## Footer\n\nCompany confidential.\n"


class FakeStore:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def signed_upload(self, path: str) -> SignedUpload:
        return SignedUpload(bucket="documents", path=path, token=f"token-for-{path}")

    def download(self, path: str) -> bytes:
        if path not in self.files:
            raise FileMissing(path)
        return self.files[path]

    def delete(self, paths: Sequence[str]) -> None:
        for path in paths:
            self.files.pop(path, None)


class FakeEmbedder:
    """Returns a distinct unit vector per call; can be told to rate-limit the next calls."""

    dimensions = 1024

    def __init__(self) -> None:
        self.texts: list[str] = []
        self.limits: list[float] = []

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        assert purpose is Purpose.PASSAGE
        if self.limits:
            raise RateLimited("fake", "slow down", retry_after=self.limits.pop(0))
        self.texts += texts
        vectors = [[1.0] + [0.0] * 1023 for _ in texts]
        return Embeddings(vectors, Usage("fake", "embed-1", "embed-1-v2", latency_ms=1.0))


class Clock:
    def __init__(self) -> None:
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def store() -> FakeStore:
    return FakeStore()


@pytest.fixture
def user(conn: Connection[DictRow]) -> AuthUser:
    user = AuthUser(id=uuid4(), email="reader@example.com")
    ensure_user(conn, user)
    conn.commit()
    return user


def personal(conn: Connection[DictRow], user: AuthUser) -> UUID:
    return list_collections(conn, user.id)[0].id


def upload(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser, name: str, data: bytes
) -> UUID:
    document, target = start_upload(conn, store, user.id, personal(conn, user), name, len(data))
    store.files[target.path] = data
    finish_upload(conn, user.id, document.id)
    conn.commit()
    return document.id


def status(conn: Connection[DictRow], document_id: UUID) -> tuple[str, str | None]:
    row = conn.execute(
        "select status, failure_reason from app.documents where id = %s", (document_id,)
    ).fetchone()
    conn.commit()
    assert row is not None
    return row["status"], row["failure_reason"]


def chunks(conn: Connection[DictRow], document_id: UUID) -> list[dict[str, object]]:
    rows = conn.execute(
        """
        select heading_path, content, embedding is not null as embedded, embedding_model
        from app.chunks where document_id = %s order by ordinal
        """,
        (document_id,),
    ).fetchall()
    conn.commit()
    return list(rows)


# --- Adding Documents ---------------------------------------------------------------------


def test_starting_an_upload_creates_an_uploading_document(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    collection_id = personal(conn, user)

    document, target = start_upload(conn, store, user.id, collection_id, "policy.md", 120)

    assert (document.name, document.status, document.size_bytes) == ("policy.md", "uploading", 120)
    assert target.path == f"{collection_id}/{document.id}.md"
    assert target.token == f"token-for-{target.path}"
    assert [d.id for d in list_documents(conn, user.id)] == [document.id]


@pytest.mark.parametrize(
    ("name", "size", "message"),
    [
        ("report.pdf", 100, "Markdown (.md) and plain text (.txt)"),
        ("notes", 100, "Markdown (.md) and plain text (.txt)"),
        ("big.txt", 20 * 1024 * 1024 + 1, "larger than 20 MB"),
        ("empty.txt", 0, "empty"),
        ("../../", 10, "needs a name"),
    ],
)
def test_uploads_that_break_a_rule_are_refused(
    conn: Connection[DictRow],
    store: FakeStore,
    user: AuthUser,
    name: str,
    size: int,
    message: str,
) -> None:
    with pytest.raises(UploadRejected, match=message):
        start_upload(conn, store, user.id, personal(conn, user), name, size)
    assert list_documents(conn, user.id) == []


def test_folders_in_the_file_name_are_dropped(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, _ = start_upload(
        conn, store, user.id, personal(conn, user), "C:\\Users\\me\\notes.txt", 5
    )

    assert document.name == "notes.txt"


def test_nobody_can_add_to_a_collection_they_cant_edit(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    other = AuthUser(id=uuid4(), email="other@example.com")
    ensure_user(conn, other)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (personal(conn, other), user.id),
    )
    conn.commit()

    with pytest.raises(NotAllowed):
        start_upload(conn, store, user.id, personal(conn, other), "x.txt", 5)
    with pytest.raises(NotAllowed):
        start_upload(conn, store, user.id, uuid4(), "x.txt", 5)


def test_finishing_an_upload_queues_the_document_once(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, _ = start_upload(conn, store, user.id, personal(conn, user), "a.txt", 5)

    assert finish_upload(conn, user.id, document.id).status == "queued"
    assert finish_upload(conn, user.id, document.id).status == "queued"


def test_users_never_see_each_others_documents(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    mine = upload(conn, store, user, "mine.txt", b"private")
    other = AuthUser(id=uuid4(), email="other@example.com")
    ensure_user(conn, other)

    assert list_documents(conn, other.id) == []
    with pytest.raises(DocumentNotFound):
        finish_upload(conn, other.id, mine)


# --- Ingestion ----------------------------------------------------------------------------


def test_a_markdown_document_becomes_indexed_with_headings(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    embedder = FakeEmbedder()

    result = run_batch(conn, store, embedder, seconds=240)

    assert (result.indexed, result.failed, result.remaining) == (1, 0, 0)
    assert status(conn, document_id) == ("indexed", None)
    assert chunks(conn, document_id) == [
        {
            "heading_path": ["Leave", "Carry-over"],
            "content": "Up to 10 days.",
            "embedded": True,
            "embedding_model": "fake:embed-1-v2",
        },
        {
            "heading_path": ["Leave", "Footer"],
            "content": "Company confidential.",
            "embedded": True,
            "embedding_model": "fake:embed-1-v2",
        },
    ]
    assert "Leave > Carry-over\n\nUp to 10 days." in embedder.texts


def test_repeated_passages_are_embedded_once(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    repeated = "\n\n".join(["Company confidential." + " pad" * 300] * 4).encode()
    document_id = upload(conn, store, user, "footer.txt", repeated)
    embedder = FakeEmbedder()

    run_batch(conn, store, embedder, seconds=240)

    assert len(chunks(conn, document_id)) == 4
    assert all(c["embedded"] for c in chunks(conn, document_id))
    assert len(embedder.texts) == 1


def test_a_file_that_never_arrived_fails_with_a_reason(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, _ = start_upload(conn, store, user.id, personal(conn, user), "lost.txt", 5)
    finish_upload(conn, user.id, document.id)
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, document.id) == (
        "failed",
        "The file never finished uploading. Remove it and upload it again.",
    )


def test_a_file_without_text_fails_alone(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    blank = upload(conn, store, user, "blank.md", b"# Title only\n\n  \n")
    good = upload(conn, store, user, "good.txt", b"Real text.")

    result = run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert (result.indexed, result.failed) == (1, 1)
    assert status(conn, blank) == ("failed", "No text was found in this file.")
    assert status(conn, good) == ("indexed", None)


def test_non_utf8_text_is_still_read(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "legacy.txt", "Café menu".encode("cp1252"))

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert chunks(conn, document_id)[0]["content"] == "Café menu"


def test_a_short_rate_limit_is_waited_out(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    embedder, clock = FakeEmbedder(), Clock()
    embedder.limits = [20.0]

    run_batch(conn, store, embedder, seconds=240, clock=clock, sleep=clock.sleep)

    assert clock.slept == [20.0]
    assert status(conn, document_id) == ("indexed", None)


def test_a_long_rate_limit_pauses_the_document_for_a_later_batch(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    embedder, clock = FakeEmbedder(), Clock()
    embedder.limits = [600.0]

    result = run_batch(conn, store, embedder, seconds=240, clock=clock, sleep=clock.sleep)

    assert result.remaining == 1
    assert status(conn, document_id) == ("embedding", None)
    assert _claim(conn) is None  # paused until the provider's quota resets
    conn.rollback()

    conn.execute("update app.documents set locked_until = null where id = %s", (document_id,))
    conn.commit()
    run_batch(conn, store, embedder, seconds=240)
    assert status(conn, document_id) == ("indexed", None)


def test_two_batches_never_claim_the_same_document(
    database_url: str, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    first = upload(conn, store, user, "a.txt", b"one")
    second = upload(conn, store, user, "b.txt", b"two")

    with (
        psycopg.connect(database_url, row_factory=dict_row) as a,
        psycopg.connect(database_url, row_factory=dict_row) as b,
    ):
        a.autocommit = b.autocommit = True
        claims = [_claim(a), _claim(b), _claim(a)]

    claimed = [c["id"] for c in claims if c is not None]
    assert sorted(claimed) == sorted([first, second])


def test_running_out_of_time_leaves_the_rest_for_the_next_batch(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    clock = Clock()

    result = run_batch(conn, store, FakeEmbedder(), seconds=20, clock=clock, sleep=clock.sleep)

    assert result.remaining == 1
    assert status(conn, document_id) == ("queued", None)


# --- HTTP ---------------------------------------------------------------------------------


@pytest.fixture
def client(database_url: str, store: FakeStore, user: AuthUser) -> Iterator[TestClient]:
    def connection() -> Iterator[Connection[DictRow]]:
        with psycopg.connect(database_url, row_factory=dict_row) as own:
            yield own

    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_connection] = connection
    app.dependency_overrides[get_file_store] = lambda: store
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_the_upload_endpoints_add_a_document(
    client: TestClient, conn: Connection[DictRow], user: AuthUser
) -> None:
    started = client.post(
        "/documents",
        json={"collection_id": str(personal(conn, user)), "name": "a.md", "size_bytes": 9},
    )
    assert started.status_code == 201
    document = started.json()["document"]
    assert started.json()["upload"]["bucket"] == "documents"

    finished = client.post(f"/documents/{document['id']}/uploaded")

    assert finished.json()["status"] == "queued"
    assert [d["id"] for d in client.get("/documents").json()] == [document["id"]]


def test_a_refused_upload_explains_why(
    client: TestClient, conn: Connection[DictRow], user: AuthUser
) -> None:
    response = client.post(
        "/documents",
        json={"collection_id": str(personal(conn, user)), "name": "a.pdf", "size_bytes": 9},
    )

    assert response.status_code == 400
    assert "Markdown (.md)" in response.json()["detail"]


def test_an_unknown_document_is_not_found(client: TestClient) -> None:
    assert client.post(f"/documents/{uuid4()}/uploaded").status_code == 404
