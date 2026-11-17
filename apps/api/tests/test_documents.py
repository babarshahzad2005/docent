"""Adding Documents and ingesting them, against a real database (TEST_DATABASE_URL)."""

import re
from collections.abc import Iterator, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import Connection
from psycopg.rows import DictRow, dict_row

from docent_api import ingestion, main
from docent_api.auth import AuthUser, current_user
from docent_api.db import get_connection
from docent_api.documents import (
    MAX_FILE_BYTES,
    DocumentNotFound,
    NotAllowed,
    NotRetryable,
    UploadRejected,
    finish_upload,
    list_documents,
    retry_document,
    start_upload,
)
from docent_api.ingestion import (
    MAX_ATTEMPTS,
    MAX_CLAIMS,
    _claim,
    backoff_seconds,
    run_batch,
)
from docent_api.library import ensure_user, list_collections
from docent_api.main import app
from docent_api.providers.base import (
    Embeddings,
    ProviderUnavailable,
    Purpose,
    RateLimited,
    Usage,
)
from docent_api.scheduler import set_trigger_token
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
    """Returns a unit vector per text; can be told to rate-limit, or to break."""

    dimensions = 1024

    def __init__(self, broken: Exception | None = None) -> None:
        self.texts: list[str] = []
        self.limits: list[float | None] = []  # per call: None succeeds, a number limits
        self.broken = broken

    async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
        assert purpose is Purpose.PASSAGE
        if self.broken:
            raise self.broken
        limit = self.limits.pop(0) if self.limits else None
        if limit is not None:
            raise RateLimited("fake", "slow down", retry_after=limit)
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
        ("slides.pptx", 100, "PDF, Word (.docx), Markdown (.md), and plain text (.txt)"),
        ("notes", 100, "PDF, Word (.docx), Markdown (.md), and plain text (.txt)"),
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
    with pytest.raises(UploadRejected, match=re.escape(message)):
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


def test_viewers_cant_queue_a_document(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, _ = start_upload(conn, store, user.id, personal(conn, user), "a.txt", 5)
    viewer = AuthUser(id=uuid4(), email="viewer@example.com")
    ensure_user(conn, viewer)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (personal(conn, user), viewer.id),
    )
    conn.commit()

    with pytest.raises(NotAllowed):
        finish_upload(conn, viewer.id, document.id)


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
        "The upload didn't finish. Upload the document again.",
    )


def test_a_file_without_text_fails_alone(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    blank = upload(conn, store, user, "blank.md", b"# Title only\n\n  \n")
    good = upload(conn, store, user, "good.txt", b"Real text.")

    result = run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert (result.indexed, result.failed) == (1, 1)
    status_, reason = status(conn, blank)
    assert status_ == "failed"
    assert reason is not None and reason.startswith("No text was found in this document.")
    assert status(conn, good) == ("indexed", None)


def test_non_utf8_text_is_still_read(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "legacy.txt", "Café menu".encode("cp1252"))

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert chunks(conn, document_id)[0]["content"] == "Café menu"


EXTRACTION_FILES = Path(__file__).parent / "extraction" / "files"


def test_a_pdf_becomes_indexed_with_page_numbers(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    data = (EXTRACTION_FILES / "fit-note-checklist.pdf").read_bytes()
    document_id = upload(conn, store, user, "fit-note.pdf", data)

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, document_id) == ("indexed", None)
    rows = conn.execute(
        "select page, heading_path, content from app.chunks where document_id = %s",
        (document_id,),
    ).fetchall()
    conn.commit()
    assert rows and all(row["page"] == 1 for row in rows)
    assert rows[0]["heading_path"] == ["Fit Note: Checklist for Employers"]


def test_a_word_document_becomes_indexed_with_headings(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    data = (EXTRACTION_FILES / "staffing-guidance.docx").read_bytes()
    document_id = upload(conn, store, user, "staffing.docx", data)

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, document_id) == ("indexed", None)
    first = chunks(conn, document_id)[0]
    assert first["heading_path"] == ["Introduction", "About this guidance"]


def test_a_pdf_with_equations_is_stored_without_control_characters(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    data = (EXTRACTION_FILES / "dense-passage-retrieval.pdf").read_bytes()
    document_id = upload(conn, store, user, "dpr.pdf", data)

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, document_id) == ("indexed", None)


def test_a_file_that_isnt_really_a_pdf_fails_with_a_reason(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "fake.pdf", b"just some text, not a PDF")

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    status_, reason = status(conn, document_id)
    assert status_ == "failed"
    assert reason is not None and "PDF couldn't be opened" in reason


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


def test_a_document_that_keeps_failing_is_marked_failed(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    embedder = FakeEmbedder(broken=ValueError("unexpected"))

    for _ in range(MAX_ATTEMPTS):
        run_batch(conn, store, embedder, seconds=240)
        conn.execute("update app.documents set locked_until = null where id = %s", (document_id,))
        conn.commit()

    status_, reason = status(conn, document_id)
    assert status_ == "failed"
    assert reason is not None and "after several tries" in reason


def test_a_document_picked_up_too_often_is_marked_failed(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    conn.execute("update app.documents set claims = %s where id = %s", (MAX_CLAIMS, document_id))
    conn.commit()

    result = run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert result.failed == 1
    assert status(conn, document_id)[0] == "failed"


def test_uploads_never_reported_finished_fail_after_an_hour(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    stale, _ = start_upload(conn, store, user.id, personal(conn, user), "stale.txt", 5)
    fresh, _ = start_upload(conn, store, user.id, personal(conn, user), "fresh.txt", 5)
    conn.execute(
        "update app.documents set created_at = now() - interval '2 hours' where id = %s",
        (stale.id,),
    )
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, stale.id) == (
        "failed",
        "The upload didn't finish. Upload the document again.",
    )
    assert status(conn, fresh.id) == ("uploading", None)


def test_the_real_file_size_is_checked_not_the_claimed_one(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, target = start_upload(conn, store, user.id, personal(conn, user), "big.txt", 10)
    store.files[target.path] = b"x" * (MAX_FILE_BYTES + 1)
    finish_upload(conn, user.id, document.id)
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, document.id) == (
        "failed",
        "This document is larger than 20 MB, the limit per document.",
    )


def test_only_one_batch_runs_at_a_time(
    database_url: str, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "a.txt", b"one")
    conn.execute("update app.ingestion_lease set held_until = now() + interval '1 minute'")
    conn.commit()

    blocked = run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert (blocked.ran, blocked.remaining) == (False, 1)
    conn.execute("update app.ingestion_lease set held_until = '-infinity'")
    conn.commit()
    assert run_batch(conn, store, FakeEmbedder(), seconds=240).ran
    assert status(conn, document_id) == ("indexed", None)


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
        json={"collection_id": str(personal(conn, user)), "name": "a.pptx", "size_bytes": 9},
    )

    assert response.status_code == 400
    assert "Markdown (.md)" in response.json()["detail"]


def test_an_unknown_document_is_not_found(client: TestClient) -> None:
    assert client.post(f"/documents/{uuid4()}/uploaded").status_code == 404


# --- Retry and backoff --------------------------------------------------------------------


def fail_retryably(conn: Connection[DictRow], store: FakeStore, user: AuthUser) -> UUID:
    """A Document that failed because the embedding provider kept erroring."""
    document_id = upload(conn, store, user, "policy.md", POLICY)
    broken = FakeEmbedder(broken=ProviderUnavailable("fake", "down"))
    for _ in range(MAX_ATTEMPTS):
        run_batch(conn, store, broken, seconds=240)
        conn.execute("update app.documents set locked_until = null where id = %s", (document_id,))
        conn.commit()
    return document_id


def embedded(conn: Connection[DictRow], document_id: UUID) -> list[object]:
    return [c["embedded"] for c in chunks(conn, document_id)]


def test_a_failing_document_waits_longer_before_each_try(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    run_batch(conn, store, FakeEmbedder(broken=ValueError("unexpected")), seconds=240)

    row = conn.execute(
        """
        select attempts, extract(epoch from locked_until - now()) as wait
        from app.documents where id = %s
        """,
        (document_id,),
    ).fetchone()
    conn.commit()
    assert row is not None and row["attempts"] == 1
    assert backoff_seconds(1) - 5 < row["wait"] <= backoff_seconds(1)
    assert [backoff_seconds(n) for n in range(1, 5)] == [60, 120, 240, 480]
    assert _claim(conn) is None  # not picked up again until the wait is over
    conn.rollback()


def test_a_half_embedded_document_resumes_without_repeating_work(
    conn: Connection[DictRow],
    store: FakeStore,
    user: AuthUser,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ingestion, "EMBED_BATCH", 1)
    document_id = upload(conn, store, user, "policy.md", POLICY)
    embedder = FakeEmbedder()
    embedder.limits = [None, 600.0]  # the first passage goes through, then the quota runs out

    run_batch(conn, store, embedder, seconds=240)
    assert sorted(embedded(conn, document_id), key=bool) == [False, True]

    conn.execute("update app.documents set locked_until = null where id = %s", (document_id,))
    conn.commit()
    run_batch(conn, store, embedder, seconds=240)

    assert status(conn, document_id) == ("indexed", None)
    assert len(embedder.texts) == len(set(embedder.texts)) == 2


def test_a_document_that_makes_progress_is_never_given_up_on(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    conn.execute(
        "update app.documents set claims = %s where id = %s", (MAX_CLAIMS - 1, document_id)
    )
    conn.commit()
    embedder = FakeEmbedder()
    embedder.limits = [600.0]

    run_batch(conn, store, embedder, seconds=240)  # parses, then pauses on the rate limit

    row = conn.execute("select claims from app.documents where id = %s", (document_id,)).fetchone()
    conn.commit()
    assert row == {"claims": 0}
    assert status(conn, document_id) == ("embedding", None)


def test_retrying_requeues_a_document_a_retry_can_help(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = fail_retryably(conn, store, user)
    conn.execute("update app.documents set claims = 3 where id = %s", (document_id,))
    conn.commit()
    failed = next(d for d in list_documents(conn, user.id) if d.id == document_id)
    assert (failed.status, failed.can_retry) == ("failed", True)

    retried = retry_document(conn, user.id, document_id)
    conn.commit()

    assert (retried.status, retried.failure_reason, retried.can_retry) == ("queued", None, False)
    row = conn.execute(
        "select attempts, claims, locked_until from app.documents where id = %s", (document_id,)
    ).fetchone()
    conn.commit()
    assert row == {"attempts": 0, "claims": 3, "locked_until": None}  # claims are kept
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    assert status(conn, document_id) == ("indexed", None)


def test_problems_in_the_file_itself_cant_be_retried(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "blank.md", b"# Title only")
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert not next(d for d in list_documents(conn, user.id) if d.id == document_id).can_retry
    with pytest.raises(NotRetryable):
        retry_document(conn, user.id, document_id)


def test_retrying_a_document_that_hasnt_failed_changes_nothing(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "a.txt", b"text")
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert retry_document(conn, user.id, document_id).status == "indexed"


def test_only_editors_can_retry(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = fail_retryably(conn, store, user)
    stranger = AuthUser(id=uuid4(), email="stranger@example.com")
    viewer = AuthUser(id=uuid4(), email="viewer@example.com")
    ensure_user(conn, stranger)
    ensure_user(conn, viewer)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (personal(conn, user), viewer.id),
    )
    conn.commit()

    with pytest.raises(DocumentNotFound):
        retry_document(conn, stranger.id, document_id)
    with pytest.raises(NotAllowed):
        retry_document(conn, viewer.id, document_id)


def test_the_retry_endpoint_queues_or_explains(
    client: TestClient, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    retryable = fail_retryably(conn, store, user)
    blank = upload(conn, store, user, "blank.md", b"# Title only")
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert client.post(f"/documents/{retryable}/retry").json()["status"] == "queued"
    refused = client.post(f"/documents/{blank}/retry")
    assert refused.status_code == 409
    assert "won't help" in refused.json()["detail"]


# --- Scheduler ----------------------------------------------------------------------------


@pytest.fixture
def scheduler_token(conn: Connection[DictRow]) -> Iterator[str]:
    set_trigger_token(conn, "the-real-token")
    conn.commit()
    yield "the-real-token"
    conn.execute("delete from app.trigger_tokens")
    conn.commit()


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Bearer guessed"}, {"Authorization": "Basic the-real-token"}],
    ids=["none", "wrong-token", "wrong-scheme"],
)
def test_only_the_scheduler_can_start_a_scheduled_batch(
    client: TestClient, scheduler_token: str, headers: dict[str, str]
) -> None:
    assert client.post("/ingestion/scheduled", headers=headers).status_code == 401


def test_without_a_token_set_up_nothing_can_start_a_scheduled_batch(client: TestClient) -> None:
    response = client.post("/ingestion/scheduled", headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_the_scheduler_processes_waiting_documents(
    client: TestClient,
    conn: Connection[DictRow],
    store: FakeStore,
    user: AuthUser,
    scheduler_token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    monkeypatch.setattr(main, "embedder", FakeEmbedder)

    response = client.post(
        "/ingestion/scheduled", headers={"Authorization": f"Bearer {scheduler_token}"}
    )

    assert response.json() == {"indexed": 1, "failed": 0, "remaining": 0, "ran": True}
    assert status(conn, document_id) == ("indexed", None)
