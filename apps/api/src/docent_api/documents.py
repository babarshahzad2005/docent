"""Documents in a User's Collections: listing them and adding new ones (see GLOSSARY.md).

Adding a Document takes two steps, because the file goes straight from the browser to storage:
`start_upload` checks the request and returns a signed upload URL, then `finish_upload` hands
the Document to ingestion once the browser reports the file is stored.
"""

import re
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.storage import FileStore, SignedUpload

DocumentStatus = Literal["uploading", "queued", "parsing", "embedding", "indexed", "failed"]

MAX_FILE_BYTES = 20 * 1024 * 1024
FILE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class DocumentSummary(BaseModel):
    id: UUID
    collection_id: UUID
    name: str
    size_bytes: int
    status: DocumentStatus
    failure_reason: str | None
    can_retry: bool
    effective_date: date
    created_at: datetime
    updated_at: datetime


class UploadRejected(Exception):
    """The upload breaks a rule; the message tells the User what to do instead."""


class NotAllowed(Exception):
    """The User can't add or change Documents in this Collection."""


class NotRetryable(Exception):
    """Retrying can't help: the problem is in the file itself."""


class DocumentNotFound(Exception):
    """No such Document in any Collection the User can reach."""


_SUMMARY_COLUMNS = """
    d.id, d.collection_id, d.name, d.size_bytes, d.status, d.failure_reason,
    d.status = 'failed' and d.failure_retryable as can_retry,
    d.effective_date, d.created_at, d.updated_at
"""


def list_documents(conn: Connection[DictRow], user_id: UUID) -> list[DocumentSummary]:
    """Every Document in the User's Collections, newest first."""
    rows = conn.execute(
        f"""
        select {_SUMMARY_COLUMNS}
        from app.documents d
        join app.memberships m on m.collection_id = d.collection_id
        where m.user_id = %(user_id)s
        order by d.created_at desc, d.name
        """,
        {"user_id": user_id},
    ).fetchall()
    return [DocumentSummary.model_validate(row) for row in rows]


def start_upload(
    conn: Connection[DictRow],
    store: FileStore,
    user_id: UUID,
    collection_id: UUID,
    name: str,
    size_bytes: int,
) -> tuple[DocumentSummary, SignedUpload]:
    """Create the Document as `uploading` and return where the browser should send the file."""
    name = clean_name(name)
    extension = PurePosixPath(name).suffix.lower()
    if extension not in FILE_TYPES:
        raise UploadRejected(
            f"{name} can't be added: Docent reads PDF, Word (.docx), Markdown (.md), and plain "
            "text (.txt) files."
        )
    if size_bytes > MAX_FILE_BYTES:
        raise UploadRejected(
            f"{name} is larger than 20 MB, the limit per file. Split it into smaller files."
        )
    if size_bytes <= 0:
        raise UploadRejected(f"{name} is empty.")

    _require_editor(conn, user_id, collection_id)
    document_id = uuid4()
    # Signing first keeps the network call out of the database transaction.
    upload = store.signed_upload(f"{collection_id}/{document_id}{extension}")
    with conn.transaction():
        row = conn.execute(
            f"""
            insert into app.documents as d
                (id, collection_id, uploaded_by, name, size_bytes, storage_path)
            values (%(id)s, %(collection_id)s, %(user_id)s, %(name)s, %(size)s, %(path)s)
            returning {_SUMMARY_COLUMNS}
            """,
            {
                "id": document_id,
                "collection_id": collection_id,
                "user_id": user_id,
                "name": name,
                "size": size_bytes,
                "path": upload.path,
            },
        ).fetchone()
    assert row is not None
    return DocumentSummary.model_validate(row), upload


def finish_upload(conn: Connection[DictRow], user_id: UUID, document_id: UUID) -> DocumentSummary:
    """The file is stored: queue the Document for ingestion. Repeating the call is harmless."""
    row = _editable(conn, user_id, document_id)
    if row["status"] != "uploading":
        return DocumentSummary.model_validate(row)
    return _queue(conn, document_id, "uploading", reset_attempts=False) or (
        DocumentSummary.model_validate(row)
    )


def retry_document(conn: Connection[DictRow], user_id: UUID, document_id: UUID) -> DocumentSummary:
    """Queue a Document again after a failure a retry could fix. Harmless if it didn't fail.

    Only the attempt count is reset: a Document that keeps breaking batches stays marked as
    such, so retrying can't loop it forever.
    """
    row = _editable(conn, user_id, document_id)
    if row["status"] != "failed":
        return DocumentSummary.model_validate(row)
    if not row["can_retry"]:
        raise NotRetryable(document_id)
    return _queue(conn, document_id, "failed", reset_attempts=True) or (
        DocumentSummary.model_validate(row)
    )


def delete_document(
    conn: Connection[DictRow], store: FileStore, user_id: UUID, document_id: UUID
) -> None:
    """Delete the Document with its original file, chunks, and vectors, all or nothing.

    The row (and, by cascade, its chunks and their vectors) is deleted and the file removed
    from storage inside one transaction: if storage refuses, the transaction rolls back and
    the Document stays whole, so a deleted Document can never leave a file behind. A batch
    working on the Document at the time stops at its next step (ingestion.py).
    """
    _editable(conn, user_id, document_id)
    with conn.transaction():
        row = conn.execute(
            "delete from app.documents where id = %s returning storage_path", (document_id,)
        ).fetchone()
        if row is None:
            return  # deleted meanwhile by another request
        store.delete([row["storage_path"]])


def storage_used(conn: Connection[DictRow], user_id: UUID) -> int:
    """Bytes of original files the User has uploaded, counted against their allowance."""
    row = conn.execute(
        "select coalesce(sum(size_bytes), 0) as used from app.documents where uploaded_by = %s",
        (user_id,),
    ).fetchone()
    return int(row["used"]) if row else 0


def _editable(conn: Connection[DictRow], user_id: UUID, document_id: UUID) -> DictRow:
    row = conn.execute(
        f"""
        select {_SUMMARY_COLUMNS}, m.role
        from app.documents d
        join app.memberships m on m.collection_id = d.collection_id
        where d.id = %(id)s and m.user_id = %(user_id)s
        """,
        {"id": document_id, "user_id": user_id},
    ).fetchone()
    if row is None:
        raise DocumentNotFound(document_id)
    if row["role"] not in ("owner", "editor"):
        raise NotAllowed(row["collection_id"])
    return row


def _queue(
    conn: Connection[DictRow], document_id: UUID, from_status: DocumentStatus, reset_attempts: bool
) -> DocumentSummary | None:
    with conn.transaction():
        row = conn.execute(
            f"""
            update app.documents d
            set status = 'queued', failure_reason = null, failure_retryable = false,
                attempts = case when %(reset)s then 0 else attempts end,
                locked_until = null, updated_at = now()
            where d.id = %(id)s and d.status = %(from_status)s
            returning {_SUMMARY_COLUMNS}
            """,
            {"id": document_id, "from_status": from_status, "reset": reset_attempts},
        ).fetchone()
    return DocumentSummary.model_validate(row) if row else None


def clean_name(name: str) -> str:
    """The file's own name, without any folders, control characters, or excess length."""
    name = _CONTROL_CHARACTERS.sub("", name.replace("\\", "/").rsplit("/", 1)[-1]).strip()
    if not name or name in {".", ".."}:
        raise UploadRejected("The file needs a name.")
    if len(name) > 255:
        stem, suffix = PurePosixPath(name).stem, PurePosixPath(name).suffix
        name = stem[: 255 - len(suffix)] + suffix
    return name


def _require_editor(conn: Connection[DictRow], user_id: UUID, collection_id: UUID) -> None:
    row = conn.execute(
        """
        select role from app.memberships
        where collection_id = %(collection_id)s and user_id = %(user_id)s
        """,
        {"collection_id": collection_id, "user_id": user_id},
    ).fetchone()
    if row is None or row["role"] not in ("owner", "editor"):
        raise NotAllowed(collection_id)
