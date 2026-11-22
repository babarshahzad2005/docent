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
    DuplicateDocument,
    NotAllowed,
    NotRetryable,
    UploadRejected,
    delete_document,
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
from docent_api.storage import FileMissing, SignedUpload, StorageError, get_file_store

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
        ("big.txt", 20 * 1024 * 1024 + 1, "over the 20 MB limit per file"),
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
    assert reason is not None and "damaged or incomplete" in reason


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

    status_, reason = status(conn, document.id)
    assert status_ == "failed"
    assert reason is not None and "over the 20 MB limit per file" in reason


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
        json={
            "collection_id": str(personal(conn, user)),
            "name": "a.md",
            "size_bytes": 9,
            "sha256": "a" * 64,
        },
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
        json={
            "collection_id": str(personal(conn, user)),
            "name": "a.pptx",
            "size_bytes": 9,
            "sha256": "a" * 64,
        },
    )

    assert response.status_code == 400
    assert "Markdown (.md)" in response.json()["detail"]


def test_an_unknown_document_is_not_found(client: TestClient) -> None:
    assert client.post(f"/documents/{uuid4()}/uploaded").status_code == 404


# --- Bad files and limits -----------------------------------------------------------------

BAD_FILES = EXTRACTION_FILES / "bad"


def test_bad_files_fail_alone_with_their_own_reasons(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    locked = upload(conn, store, user, "locked.pdf", (BAD_FILES / "password.pdf").read_bytes())
    scan = upload(conn, store, user, "scan.pdf", (BAD_FILES / "scanned.pdf").read_bytes())
    broken = upload(conn, store, user, "broken.pdf", (BAD_FILES / "damaged.pdf").read_bytes())
    good = upload(conn, store, user, "good.md", POLICY)

    result = run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert (result.indexed, result.failed) == (1, 3)
    assert status(conn, good) == ("indexed", None)
    reasons = [status(conn, d)[1] or "" for d in (locked, scan, broken)]
    assert reasons[0].startswith("This PDF is password-protected.")
    assert reasons[1].startswith("This PDF is made of pictures of pages")
    assert reasons[2].startswith("This PDF is damaged or incomplete")
    assert not any(
        d.can_retry for d in list_documents(conn, user.id) if d.id in (locked, scan, broken)
    )


def fill_storage(conn: Connection[DictRow], user: AuthUser, size_bytes: int) -> None:
    conn.execute(
        """
        insert into app.documents (collection_id, uploaded_by, name, size_bytes, storage_path,
                                   status)
        values (%s, %s, 'existing.pdf', %s, %s, 'indexed')
        """,
        (personal(conn, user), user.id, size_bytes, f"x/{uuid4()}.pdf"),
    )
    conn.commit()


def test_uploads_over_the_100_mb_allowance_are_refused(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    fill_storage(conn, user, 96 * 1024 * 1024)

    with pytest.raises(UploadRejected) as refused:
        start_upload(conn, store, user.id, personal(conn, user), "big.pdf", 5 * 1024 * 1024)

    assert str(refused.value) == (
        "Your documents use 96.0\u00a0MB of your 100 MB. big.pdf (5.0\u00a0MB) would go over "
        "the limit: delete documents you no longer need to make room."
    )
    start_upload(conn, store, user.id, personal(conn, user), "small.pdf", 4 * 1024 * 1024)


def test_the_allowance_is_checked_again_with_the_real_file_size(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    fill_storage(conn, user, 99 * 1024 * 1024)
    document, target = start_upload(conn, store, user.id, personal(conn, user), "a.txt", 10)
    store.files[target.path] = b"x" * (2 * 1024 * 1024)  # the browser understated its size
    finish_upload(conn, user.id, document.id)
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    status_, reason = status(conn, document.id)
    assert status_ == "failed"
    assert reason is not None and "over your 100 MB" in reason


def sha256(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def test_the_same_file_twice_in_a_collection_is_flagged(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    collection = personal(conn, user)
    first, target = start_upload(
        conn, store, user.id, collection, "policy.md", len(POLICY), sha256=sha256(POLICY)
    )
    store.files[target.path] = POLICY
    conn.commit()

    with pytest.raises(DuplicateDocument) as flagged:
        start_upload(
            conn, store, user.id, collection, "policy copy.md", len(POLICY), sha256=sha256(POLICY)
        )
    assert str(flagged.value) == (
        "policy copy.md is already in the Personal collection as policy.md. Upload it anyway "
        "to keep both."
    )

    second, _ = start_upload(
        conn,
        store,
        user.id,
        collection,
        "policy copy.md",
        len(POLICY),
        sha256=sha256(POLICY),
        allow_duplicate=True,
    )
    assert second.id != first.id


def test_the_stored_files_fingerprint_replaces_the_browsers(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    collection = personal(conn, user)
    document, target = start_upload(
        conn, store, user.id, collection, "a.md", len(POLICY), sha256="0" * 64
    )
    store.files[target.path] = POLICY
    finish_upload(conn, user.id, document.id)
    conn.commit()
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    with pytest.raises(DuplicateDocument):
        start_upload(conn, store, user.id, collection, "b.md", len(POLICY), sha256=sha256(POLICY))


def test_a_malformed_fingerprint_is_refused(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    with pytest.raises(UploadRejected, match="couldn\u2019t be checked"):
        start_upload(conn, store, user.id, personal(conn, user), "a.md", 5, sha256="nope")


def test_a_file_that_can_never_be_read_is_removed_and_stops_counting(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    scan = upload(conn, store, user, "scan.pdf", (BAD_FILES / "scanned.pdf").read_bytes())

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert status(conn, scan)[0] == "failed"
    assert store.files == {}
    assert used_bytes(conn, user) == 0
    assert pending_removals(conn) == []


def test_a_failed_attempt_doesnt_block_uploading_the_file_again(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    data = (BAD_FILES / "scanned.pdf").read_bytes()
    document, target = start_upload(
        conn, store, user.id, personal(conn, user), "scan.pdf", len(data), sha256=sha256(data)
    )
    store.files[target.path] = data
    finish_upload(conn, user.id, document.id)
    conn.commit()
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    start_upload(  # not flagged: the earlier attempt failed
        conn, store, user.id, personal(conn, user), "scan.pdf", len(data), sha256=sha256(data)
    )


def test_unfinished_uploads_stop_counting_and_their_files_go_later(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    stale, target = start_upload(conn, store, user.id, personal(conn, user), "a.txt", 10**6)
    conn.execute(
        "update app.documents set created_at = now() - interval '90 minutes' where id = %s",
        (stale.id,),
    )
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert used_bytes(conn, user) == 0
    assert [(r["path"], r["later"]) for r in pending_removals(conn)] == [(target.path, True)]


def test_uploads_racing_for_the_last_space_dont_both_fail(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    fill_storage(conn, user, 70 * 1024 * 1024)
    collection = personal(conn, user)
    big = b"x" * (20 * 1024 * 1024)
    first, first_target = start_upload(conn, store, user.id, collection, "one.txt", 1)
    second, second_target = start_upload(conn, store, user.id, collection, "two.txt", 1)
    store.files[first_target.path] = big  # both browsers understated, so both passed the check
    store.files[second_target.path] = big
    finish_upload(conn, user.id, first.id)
    finish_upload(conn, user.id, second.id)
    conn.commit()

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    statuses = sorted(status(conn, d)[0] for d in (first.id, second.id))
    assert statuses == ["failed", "indexed"]


def test_a_pdf_over_300_pages_fails_with_the_limit_named(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    import io

    import pypdfium2

    document = pypdfium2.PdfDocument.new()
    for _ in range(301):
        document.new_page(612, 792)
    buffer = io.BytesIO()
    document.save(buffer)
    long_one = upload(conn, store, user, "long.pdf", buffer.getvalue())

    run_batch(conn, store, FakeEmbedder(), seconds=240)

    reason = status(conn, long_one)[1] or ""
    assert "301 pages; the limit is 300 per document" in reason


def test_the_upload_endpoint_reports_duplicates_with_409(
    client: TestClient, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    body = {
        "collection_id": str(personal(conn, user)),
        "name": "a.md",
        "size_bytes": len(POLICY),
        "sha256": sha256(POLICY),
    }
    assert client.post("/documents", json=body).status_code == 201

    again = client.post("/documents", json=body)
    kept = client.post("/documents", json={**body, "allow_duplicate": True})

    assert again.status_code == 409
    assert "Upload it anyway to keep both" in again.json()["detail"]
    assert kept.status_code == 201


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
    assert "won’t help" in refused.json()["detail"]


# --- Delete -------------------------------------------------------------------------------


def count_rows(conn: Connection[DictRow], table: str, document_id: UUID) -> int:
    column = "id" if table == "documents" else "document_id"
    row = conn.execute(
        f"select count(*) as n from app.{table} where {column} = %s", (document_id,)
    ).fetchone()
    conn.commit()
    assert row is not None
    return int(row["n"])


def pending_removals(conn: Connection[DictRow]) -> list[dict[str, object]]:
    rows = conn.execute(
        "select path, delete_after > now() as later from app.storage_deletions order by path"
    ).fetchall()
    conn.commit()
    return list(rows)


def used_bytes(conn: Connection[DictRow], user: AuthUser) -> int:
    row = conn.execute(
        "select coalesce(sum(size_bytes), 0) as n from app.documents where uploaded_by = %s",
        (user.id,),
    ).fetchone()
    conn.commit()
    assert row is not None
    return int(row["n"])


def test_deleting_removes_the_file_chunks_and_vectors_together(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    kept = upload(conn, store, user, "other.txt", b"Keep me.")
    assert count_rows(conn, "chunks", document_id) == 2
    used = used_bytes(conn, user)

    delete_document(conn, store, user.id, document_id)

    assert count_rows(conn, "documents", document_id) == 0
    assert count_rows(conn, "chunks", document_id) == 0
    assert not [path for path in store.files if str(document_id) in path]
    assert pending_removals(conn) == []
    assert used_bytes(conn, user) == used - len(POLICY)
    assert [d.id for d in list_documents(conn, user.id)] == [kept]


def test_the_deletion_is_committed_before_the_file_is_removed(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser, database_url: str
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    seen: list[int] = []

    def remove(paths: Sequence[str]) -> None:
        # Another connection sees the row gone by the time storage is asked to remove the file.
        with psycopg.connect(database_url) as other:
            row = other.execute(
                "select count(*) from app.documents where id = %s", (document_id,)
            ).fetchone()
            seen.append(row[0] if row else -1)
        FakeStore.delete(store, paths)

    store.delete = remove  # type: ignore[method-assign]
    delete_document(conn, store, user.id, document_id)

    assert seen == [0]


def test_a_file_storage_cant_remove_now_is_removed_by_a_later_batch(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser, monkeypatch: pytest.MonkeyPatch
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    def refuse(paths: Sequence[str]) -> None:
        raise StorageError("storage is down")

    monkeypatch.setattr(store, "delete", refuse)
    delete_document(conn, store, user.id, document_id)

    assert count_rows(conn, "documents", document_id) == 0  # the Document is gone for the User
    assert len(store.files) == 1  # its file isn't yet
    assert [r["later"] for r in pending_removals(conn)] == [False]

    monkeypatch.undo()
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    assert store.files == {}
    assert pending_removals(conn) == []


def test_a_file_still_uploading_is_removed_after_its_link_expires(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document, target = start_upload(conn, store, user.id, personal(conn, user), "a.txt", 5)
    conn.commit()

    delete_document(conn, store, user.id, document.id)
    store.files[target.path] = b"late!"  # the browser's upload finishes afterwards

    assert [(r["path"], r["later"]) for r in pending_removals(conn)] == [(target.path, True)]
    conn.execute("update app.storage_deletions set delete_after = now() - interval '1 second'")
    conn.commit()
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    assert store.files == {}


def test_only_editors_can_delete(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
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
        delete_document(conn, store, stranger.id, document_id)
    with pytest.raises(NotAllowed):
        delete_document(conn, store, viewer.id, document_id)
    conn.rollback()
    assert count_rows(conn, "documents", document_id) == 1


def test_deleting_while_embedding_leaves_nothing_behind(
    database_url: str, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    class DeletingEmbedder(FakeEmbedder):
        """The User deletes the Document while its batch is embedding."""

        async def embed(self, texts: Sequence[str], purpose: Purpose) -> Embeddings:
            with psycopg.connect(database_url, row_factory=dict_row) as other:
                delete_document(other, store, user.id, document_id)
            return await super().embed(texts, purpose)

    result = run_batch(conn, store, DeletingEmbedder(), seconds=240)

    assert (result.indexed, result.failed) == (0, 0)
    assert count_rows(conn, "documents", document_id) == 0
    assert count_rows(conn, "chunks", document_id) == 0
    assert store.files == {}


def test_deleting_while_parsing_leaves_nothing_behind(
    database_url: str, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    class DeletingStore(FakeStore):
        """The User deletes the Document just after its batch downloaded the file."""

        def download(self, path: str) -> bytes:
            data = super().download(path)
            with psycopg.connect(database_url, row_factory=dict_row) as other:
                delete_document(other, self, user.id, document_id)
            return data

    deleting = DeletingStore()
    deleting.files = store.files

    result = run_batch(conn, deleting, FakeEmbedder(), seconds=240)

    assert (result.indexed, result.failed) == (0, 0)  # the chunk insert found no Document
    assert count_rows(conn, "chunks", document_id) == 0
    assert deleting.files == {}


def test_the_delete_endpoint_is_repeatable(
    client: TestClient, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    assert client.delete(f"/documents/{document_id}").status_code == 204
    assert client.delete(f"/documents/{document_id}").status_code == 204
    assert client.get("/documents").json() == []


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


# --- Effective Date (#47) -----------------------------------------------------------------


def test_owners_set_the_effective_date_and_viewers_cannot(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    from datetime import date

    from docent_api.documents import set_effective_date

    document_id = upload(conn, store, user, "policy.md", POLICY)
    viewer = AuthUser(id=uuid4(), email="viewer@example.com")
    ensure_user(conn, viewer)
    conn.execute(
        "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'viewer')",
        (personal(conn, user), viewer.id),
    )
    conn.commit()

    summary = set_effective_date(conn, user.id, document_id, date(2024, 1, 1))

    assert summary.effective_date == date(2024, 1, 1)
    with pytest.raises(NotAllowed):
        set_effective_date(conn, viewer.id, document_id, date(2020, 1, 1))
    conn.rollback()
    row = conn.execute("select effective_date from app.documents where id = %s", (document_id,))
    assert str(row.fetchone()["effective_date"]) == "2024-01-01"  # type: ignore[index]
    conn.commit()


def test_the_update_endpoint_sets_the_effective_date(
    client: TestClient, conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)

    changed = client.patch(f"/documents/{document_id}", json={"effective_date": "2019-11-01"})

    assert changed.status_code == 200 and changed.json()["effective_date"] == "2019-11-01"
    path = f"/documents/{document_id}"
    # Not a date, or out of range: it orders Documents that disagree, so a typo mustn't win.
    for bad in ("soon", "9999-12-31", "0001-01-01"):
        assert client.patch(path, json={"effective_date": bad}).status_code == 422, bad
    assert (
        client.patch(f"/documents/{uuid4()}", json={"effective_date": "2019-11-01"}).status_code
        == 404
    )


# --- Replace (#47) ------------------------------------------------------------------------

NEW_POLICY = b"# Leave\n\n## Carry-over\n\nUp to 5 days.\n\n## Footer\n\nCompany confidential.\n"


def replace(
    conn: Connection[DictRow],
    store: FakeStore,
    user: AuthUser,
    document_id: UUID,
    data: bytes,
    name: str = "policy.md",
) -> UUID:
    import hashlib

    version, target = start_upload(
        conn,
        store,
        user.id,
        personal(conn, user),
        name,
        len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        replaces=document_id,
    )
    store.files[target.path] = data
    finish_upload(conn, user.id, version.id)
    conn.commit()
    return version.id


def current_texts(conn: Connection[DictRow], document_id: UUID) -> list[str]:
    rows = conn.execute(
        "select content from app.chunks where document_id = %s and superseded_at is null "
        "order by ordinal",
        (document_id,),
    ).fetchall()
    conn.commit()
    return [row["content"] for row in rows]


def test_a_replaced_document_answers_from_the_old_version_until_the_new_one_is_indexed(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    from docent_api.retrieval import passage_in_context

    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    old_chunk = conn.execute(
        "select id from app.chunks where document_id = %s and content = 'Up to 10 days.'",
        (document_id,),
    ).fetchone()["id"]  # type: ignore[index]
    old_path = conn.execute(
        "select storage_path from app.documents where id = %s", (document_id,)
    ).fetchone()["storage_path"]  # type: ignore[index]
    conn.commit()

    version_id = replace(conn, store, user, document_id, NEW_POLICY)

    # Meanwhile: one Document in the Library, still the old version, with its replacement.
    listed = list_documents(conn, user.id)
    conn.commit()
    assert [d.id for d in listed] == [document_id]
    assert listed[0].replacement is not None and listed[0].replacement.status == "queued"
    assert current_texts(conn, document_id) == ["Up to 10 days.", "Company confidential."]

    embedder = FakeEmbedder()
    run_batch(conn, store, embedder, seconds=240)

    assert current_texts(conn, document_id) == ["Up to 5 days.", "Company confidential."]
    # The unchanged footer kept its vector: only the changed passage was embedded.
    assert embedder.texts == ["Leave > Carry-over\n\nUp to 5 days."]
    assert count_rows(conn, "documents", version_id) == 0
    [document] = list_documents(conn, user.id)
    conn.commit()
    assert document.replacement is None and document.status == "indexed"
    # The old passage still opens for past Citations, marked replaced, and isn't searched.
    cited = passage_in_context(conn, user.id, old_chunk)
    assert cited["content"] == "Up to 10 days." and cited["replaced"] is True
    superseded = conn.execute(
        "select embedding is null as no_vector from app.chunks where id = %s", (old_chunk,)
    ).fetchone()
    queued = conn.execute(
        "select 1 from app.storage_deletions where path = %s", (old_path,)
    ).fetchone()
    conn.commit()
    assert superseded is not None and superseded["no_vector"]
    assert queued is not None or old_path not in store.files  # the old file goes


def test_a_failed_replacement_leaves_the_document_answering_and_can_be_cancelled(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    import hashlib

    version, target = start_upload(
        conn,
        store,
        user.id,
        personal(conn, user),
        "policy.md",
        5,
        sha256=hashlib.sha256(b"\x00\x01").hexdigest(),
        replaces=document_id,
    )
    store.files[target.path] = b"\x00\x01\x02\x03\x04"  # no text in it
    finish_upload(conn, user.id, version.id)
    conn.commit()
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    [document] = list_documents(conn, user.id)
    conn.commit()
    assert document.status == "indexed"
    assert document.replacement is not None and document.replacement.status == "failed"
    assert current_texts(conn, document_id) == ["Up to 10 days.", "Company confidential."]
    delete_document(conn, store, user.id, version.id)  # Cancel
    [document] = list_documents(conn, user.id)
    conn.commit()
    assert document.replacement is None


def test_replace_is_refused_while_another_is_under_way_or_for_the_same_content(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    import hashlib

    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    with pytest.raises(UploadRejected, match="the same as the current version"):
        start_upload(
            conn,
            store,
            user.id,
            personal(conn, user),
            "policy.md",
            len(POLICY),
            sha256=hashlib.sha256(POLICY).hexdigest(),
            replaces=document_id,
        )
    conn.rollback()
    replace(conn, store, user, document_id, NEW_POLICY)
    with pytest.raises(UploadRejected, match="already being replaced"):
        start_upload(
            conn,
            store,
            user.id,
            personal(conn, user),
            "policy.md",
            10,
            sha256=hashlib.sha256(b"other").hexdigest(),
            replaces=document_id,
        )
    conn.rollback()


def test_deleting_a_document_takes_its_replacement_and_both_files(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    version_id = replace(conn, store, user, document_id, NEW_POLICY)

    delete_document(conn, store, user.id, document_id)

    assert count_rows(conn, "documents", document_id) == 0
    assert count_rows(conn, "documents", version_id) == 0
    assert store.files == {}


def test_a_swap_whose_replacement_was_deleted_changes_nothing(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    from docent_api.ingestion import _replace

    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    version_id = replace(conn, store, user, document_id, NEW_POLICY)
    delete_document(conn, store, user.id, version_id)  # Dismissed in another tab

    with conn.transaction():
        swapped = _replace(conn, version_id, document_id)

    assert swapped is False
    # The Document still answers from all its passages, vectors included.
    rows = conn.execute(
        "select count(*) filter (where embedding is not null) as embedded, count(*) as current "
        "from app.chunks where document_id = %s and superseded_at is null",
        (document_id,),
    ).fetchone()
    conn.commit()
    assert rows is not None and rows["current"] == 2 and rows["embedded"] == 2


def test_replace_keeps_the_effective_date_and_each_version_keeps_its_own_context(
    conn: Connection[DictRow], store: FakeStore, user: AuthUser
) -> None:
    from datetime import date

    from docent_api.documents import set_effective_date
    from docent_api.retrieval import passage_in_context

    document_id = upload(conn, store, user, "policy.md", POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    set_effective_date(conn, user.id, document_id, date(2024, 1, 1))
    replace(conn, store, user, document_id, NEW_POLICY)
    run_batch(conn, store, FakeEmbedder(), seconds=240)
    third = NEW_POLICY.replace(b"5 days", b"3 days")
    replace(conn, store, user, document_id, third)
    run_batch(conn, store, FakeEmbedder(), seconds=240)

    [document] = list_documents(conn, user.id)
    conn.commit()
    assert document.effective_date == date(2024, 1, 1)
    assert current_texts(conn, document_id) == ["Up to 3 days.", "Company confidential."]
    # The second version's passage opens with the second version's neighbours, not the third's.
    second = conn.execute(
        "select id from app.chunks where document_id = %s and content = 'Up to 5 days.'",
        (document_id,),
    ).fetchone()
    conn.commit()
    assert second is not None
    cited = passage_in_context(conn, user.id, second["id"])
    assert cited["replaced"] is True and cited["content"] == "Up to 5 days."


def test_answer_log_entries_past_90_days_are_deleted_and_newer_ones_kept(
    conn: Connection[DictRow], user: AuthUser
) -> None:
    from docent_api.scheduler import RETENTION_SQL

    conversation = conn.execute(
        "insert into app.conversations (user_id, title) values (%s, 'q') returning id", (user.id,)
    ).fetchone()["id"]  # type: ignore[index]
    for age in (89, 91):  # either side of the 90-day boundary
        message = conn.execute(
            "insert into app.messages (conversation_id, role, status) "
            "values (%s, 'assistant', 'complete') returning id",
            (conversation,),
        ).fetchone()["id"]  # type: ignore[index]
        conn.execute(
            """
            insert into app.answer_logs
                (message_id, user_id, question, scope, retrieved, prompt, answer, outcome, model,
                 latency_ms, created_at)
            values (%s, %s, 'q', '{}', '[]', '', '', 'answered', 'fake', 1,
                    now() - make_interval(days => %s))
            """,
            (message, user.id, age),
        )
    conn.commit()

    conn.execute(RETENTION_SQL)
    ages = conn.execute(
        "select extract(day from now() - created_at)::int as days from app.answer_logs"
    ).fetchall()
    conn.commit()

    assert [row["days"] for row in ages] == [89]
