"""Turning queued Documents into embedded chunks, in short resumable batches (ADR 0008).

One batch runs at a time (a lease in `app.ingestion_lease`), so repeated triggers can't pile up
work or compete for the embedding quota. A batch claims one Document at a time and moves it
through `parsing` and `embedding` to `indexed`. Progress is saved as it goes: chunks are stored
before any are embedded, and each embedded group is committed, so a batch that runs out of
time (or crashes) leaves the rest for the next one.

Embeddings are the bottleneck on the free tier (100 texts a minute, ADR 0010). When the
provider says to wait, a batch waits if it has time to spare, or stops and leaves the Document
for the next batch.

Nothing can loop forever: errors count attempts, and a Document that keeps being picked up
without finishing (say, one that kills its batch) is marked failed after MAX_CLAIMS.
"""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.chunking import Chunk, chunk_markdown, chunk_plain_text
from docent_api.documents import FILE_TYPES, MAX_FILE_BYTES
from docent_api.providers.base import Embedder, Purpose, RateLimited
from docent_api.storage import FileMissing, FileStore

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300
EMBED_BATCH = 100
MAX_ATTEMPTS = 5
MAX_CLAIMS = 30
STALE_UPLOAD_HOURS = 1
# Don't start an embedding call that might not finish before the batch's time is up.
_EMBED_CALL_ALLOWANCE = 60.0
# Statuses a Document passes through while ingestion owns it.
ACTIVE_STATUSES = ("queued", "parsing", "embedding")

# What counts as waiting work, in one place: the claim query, the stale-upload sweep, and the
# scheduler's every-minute check (scheduler.py) all use these.
CLAIMABLE_SQL = "status in ({}) and (locked_until is null or locked_until < now())".format(
    ", ".join(f"'{status}'" for status in ACTIVE_STATUSES)
)
STALE_UPLOAD_SQL = (
    f"status = 'uploading' and created_at < now() - interval '{STALE_UPLOAD_HOURS} hours'"
)
WORK_WAITING_SQL = (
    f"exists (select 1 from app.documents where ({CLAIMABLE_SQL}) or ({STALE_UPLOAD_SQL}))"
)

_CHUNKERS: dict[str, Callable[[str], list[Chunk]]] = {
    "text": chunk_plain_text,
    "markdown": chunk_markdown,
}

_UPLOAD_UNFINISHED = "The upload didn't finish. Upload the document again."
_GAVE_UP = (
    "Docent couldn't process this document after several tries. Retry, and if it fails again, "
    "check that it opens on your computer."
)
_KEEPS_FAILING = (
    "Docent couldn't process this document. Check that it opens on your computer, then upload "
    "it again."
)

Outcome = Literal["indexed", "failed", "paused", "retrying"]


@dataclass(frozen=True)
class BatchResult:
    indexed: int
    failed: int
    remaining: int
    ran: bool = True


@dataclass(frozen=True)
class _Budget:
    """When the batch must stop, and how it reads the time and waits (fakeable in tests)."""

    deadline: float
    clock: Callable[[], float]
    sleep: Callable[[float], None]

    def left(self) -> float:
        return self.deadline - self.clock()


class _Paused(Exception):
    """Stop work on this Document for now and come back to it in a later batch."""

    def __init__(self, retry_in: float) -> None:
        self.retry_in = retry_in


class _Unprocessable(Exception):
    """The Document can never be indexed as it is; the message is shown to the User."""


def run_batch(
    conn: Connection[DictRow],
    store: FileStore,
    embedder: Embedder,
    seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> BatchResult:
    """Work through queued Documents until none are left or `seconds` have passed.

    Returns at once (with `ran` False) if another batch is already running. Runs in autocommit
    mode so that each step's transaction really commits as it finishes.
    """
    conn.commit()
    conn.autocommit = True
    try:
        if not _take_lease(conn, seconds):
            return BatchResult(indexed=0, failed=0, remaining=_remaining(conn), ran=False)
        try:
            return _run(conn, store, embedder, _Budget(clock() + seconds, clock, sleep))
        finally:
            conn.execute("update app.ingestion_lease set held_until = '-infinity'")
    finally:
        conn.autocommit = False


def _take_lease(conn: Connection[DictRow], seconds: float) -> bool:
    row = conn.execute(
        """
        update app.ingestion_lease
        set held_until = now() + make_interval(secs => %(seconds)s)
        where held_until < now()
        returning true as taken
        """,
        {"seconds": seconds + _EMBED_CALL_ALLOWANCE},
    ).fetchone()
    return row is not None


def _run(
    conn: Connection[DictRow], store: FileStore, embedder: Embedder, budget: _Budget
) -> BatchResult:
    _fail_unfinished_uploads(conn)
    indexed = failed = 0
    while budget.left() > _EMBED_CALL_ALLOWANCE / 2:
        document = _claim(conn)
        if document is None:
            break
        if document["claims"] > MAX_CLAIMS:
            # Picked up again and again without progress: something about it breaks batches.
            _finish(conn, document["id"], "failed", _KEEPS_FAILING)
            failed += 1
            continue
        outcome = _DocumentWorker(conn, store, embedder, document, budget).run()
        indexed += outcome == "indexed"
        failed += outcome == "failed"
        if outcome == "paused":
            break
    return BatchResult(indexed=indexed, failed=failed, remaining=_remaining(conn))


def _claim(conn: Connection[DictRow]) -> dict[str, Any] | None:
    with conn.transaction():
        return conn.execute(
            f"""
            update app.documents
            set locked_until = now() + make_interval(secs => %(lease)s), claims = claims + 1
            where id = (
                select id from app.documents
                where {CLAIMABLE_SQL}
                order by created_at
                for update skip locked
                limit 1
            )
            returning id, collection_id, name, storage_path, status, attempts, claims
            """,
            {"lease": LEASE_SECONDS},
        ).fetchone()


def _remaining(conn: Connection[DictRow]) -> int:
    row = conn.execute(
        "select count(*) as n from app.documents where status = any(%s::app.document_status[])",
        (list(ACTIVE_STATUSES),),
    ).fetchone()
    return int(row["n"]) if row else 0


def _fail_unfinished_uploads(conn: Connection[DictRow]) -> None:
    """A browser that never reported its upload finished (closed tab, failed upload)."""
    conn.execute(
        f"""
        update app.documents
        set status = 'failed', failure_reason = %(reason)s, updated_at = now()
        where {STALE_UPLOAD_SQL}
        """,
        {"reason": _UPLOAD_UNFINISHED},
    )


def _finish(
    conn: Connection[DictRow],
    document_id: UUID,
    status: str,
    reason: str | None,
    retryable: bool = False,
) -> None:
    """End ingestion. `retryable` says whether retrying could help (a temporary problem)."""
    conn.execute(
        """
        update app.documents
        set status = %(status)s, failure_reason = %(reason)s,
            failure_retryable = %(retryable)s, locked_until = null, updated_at = now()
        where id = %(id)s
        """,
        {"status": status, "reason": reason, "retryable": retryable, "id": document_id},
    )


class _DocumentWorker:
    def __init__(
        self,
        conn: Connection[DictRow],
        store: FileStore,
        embedder: Embedder,
        document: dict[str, Any],
        budget: _Budget,
    ) -> None:
        self.conn = conn
        self.store = store
        self.embedder = embedder
        self.document = document
        self.id: UUID = document["id"]
        self.budget = budget
        # Whether this claim saved any work. A Document that progresses is never given up on
        # for being picked up often: a large one legitimately takes many batches.
        self.progressed = False

    def run(self) -> Outcome:
        try:
            if self.document["status"] in ("queued", "parsing"):
                self._parse()
            self._embed()
        except _Unprocessable as problem:
            _finish(self.conn, self.id, "failed", str(problem))
            return "failed"
        except _Paused as pause:
            self._release(pause.retry_in)
            return "paused"
        except Exception as error:  # anything else: count it, so it can't loop forever
            return self._retry_later(error)
        _finish(self.conn, self.id, "indexed", None)
        return "indexed"

    def _parse(self) -> None:
        self._set_status("parsing")
        try:
            data = self.store.download(self.document["storage_path"])
        except FileMissing as error:
            raise _Unprocessable(_UPLOAD_UNFINISHED) from error
        self.conn.execute(
            "update app.documents set size_bytes = %s where id = %s", (len(data), self.id)
        )
        if len(data) > MAX_FILE_BYTES:
            raise _Unprocessable("This document is larger than 20 MB, the limit per document.")
        file_type = FILE_TYPES.get(PurePosixPath(self.document["name"]).suffix.lower())
        if file_type is None:
            raise _Unprocessable("Docent can't read this type of document.")
        chunks = _CHUNKERS[file_type](_decode(data))
        if not chunks:
            raise _Unprocessable("No text was found in this document.")
        with self.conn.transaction():
            self.conn.execute("delete from app.chunks where document_id = %s", (self.id,))
            with self.conn.cursor() as cursor:
                cursor.executemany(
                    """
                    insert into app.chunks
                        (document_id, collection_id, ordinal, heading_path, content, content_hash)
                    values (%s, %s, %s, %s, %s, %s)
                    """,
                    [
                        (
                            self.id,
                            self.document["collection_id"],
                            c.ordinal,
                            list(c.heading_path),
                            c.content,
                            c.content_hash,
                        )
                        for c in chunks
                    ],
                )
            self._set_status("embedding")
        self.progressed = True

    def _embed(self) -> None:
        self._reuse_identical_embeddings()
        while True:
            pending = self.conn.execute(
                """
                select distinct on (content_hash) content_hash, heading_path, content
                from app.chunks
                where document_id = %s and embedding is null
                order by content_hash, ordinal
                limit %s
                """,
                (self.id, EMBED_BATCH),
            ).fetchall()
            if not pending:
                return
            if self.budget.left() < _EMBED_CALL_ALLOWANCE:
                raise _Paused(retry_in=0)
            texts = [
                Chunk(0, tuple(row["heading_path"]), row["content"]).text_for_embedding
                for row in pending
            ]
            try:
                result = asyncio.run(self.embedder.embed(texts, Purpose.PASSAGE))
            except RateLimited as limit:
                self._wait_or_pause(limit.retry_after or 60.0)
                continue
            model = f"{result.usage.provider}:{result.usage.model_version}"
            with self.conn.transaction(), self.conn.cursor() as cursor:
                cursor.executemany(
                    """
                    update app.chunks
                    set embedding = %s::extensions.vector, embedding_model = %s
                    where document_id = %s and content_hash = %s and embedding is null
                    """,
                    [
                        (_vector_literal(vector), model, self.id, row["content_hash"])
                        for row, vector in zip(pending, result.vectors, strict=True)
                    ],
                )
            self.progressed = True

    def _reuse_identical_embeddings(self) -> None:
        """Repeated passages (a footer on every page, say) are embedded once per Document."""
        self.conn.execute(
            """
            update app.chunks c
            set embedding = done.embedding, embedding_model = done.embedding_model
            from (
                select distinct on (content_hash) content_hash, embedding, embedding_model
                from app.chunks
                where document_id = %(id)s and embedding is not null
            ) done
            where c.document_id = %(id)s and c.embedding is null
              and c.content_hash = done.content_hash
            """,
            {"id": self.id},
        )

    def _wait_or_pause(self, seconds: float) -> None:
        if seconds < self.budget.left() - _EMBED_CALL_ALLOWANCE:
            self.budget.sleep(seconds)
        else:
            raise _Paused(retry_in=seconds)

    def _retry_later(self, error: Exception) -> Outcome:
        attempts = self.document["attempts"] + 1
        logger.warning("ingesting %s failed (attempt %s): %r", self.id, attempts, error)
        if attempts >= MAX_ATTEMPTS:
            _finish(self.conn, self.id, "failed", _GAVE_UP, retryable=True)
            return "failed"
        self.conn.execute(
            """
            update app.documents
            set attempts = %(attempts)s,
                locked_until = now() + make_interval(secs => %(backoff)s),
                claims = case when %(progressed)s then 0 else claims end
            where id = %(id)s
            """,
            {
                "attempts": attempts,
                "backoff": backoff_seconds(attempts),
                "progressed": self.progressed,
                "id": self.id,
            },
        )
        return "retrying"

    def _set_status(self, status: str) -> None:
        self.conn.execute(
            "update app.documents set status = %s, updated_at = now() where id = %s",
            (status, self.id),
        )

    def _release(self, retry_in: float) -> None:
        self.conn.execute(
            """
            update app.documents
            set locked_until = now() + make_interval(secs => %(retry_in)s),
                claims = case when %(progressed)s then 0 else claims end
            where id = %(id)s
            """,
            {"retry_in": retry_in, "progressed": self.progressed, "id": self.id},
        )


def backoff_seconds(attempts: int) -> int:
    """Wait before trying a failing Document again: 1, 2, 4, 8 minutes."""
    return int(30 * 2**attempts)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _vector_literal(vector: list[float]) -> str:
    return "[" + ",".join(repr(v) for v in vector) + "]"
