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
FILE_TYPES = {".txt": "text", ".md": "markdown", ".markdown": "markdown"}
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class DocumentSummary(BaseModel):
    id: UUID
    collection_id: UUID
    name: str
    size_bytes: int
    status: DocumentStatus
    failure_reason: str | None
    effective_date: date
    created_at: datetime
    updated_at: datetime


class UploadRejected(Exception):
    """The upload breaks a rule; the message tells the User what to do instead."""


class NotAllowed(Exception):
    """The User can't add or change Documents in this Collection."""


class DocumentNotFound(Exception):
    """No such Document in any Collection the User can reach."""


_SUMMARY_COLUMNS = """
    d.id, d.collection_id, d.name, d.size_bytes, d.status, d.failure_reason,
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
            f"{name} can't be added: Docent reads Markdown (.md) and plain text (.txt) files."
        )
    if size_bytes > MAX_FILE_BYTES:
        raise UploadRejected(
            f"{name} is larger than 20 MB, the limit per file. Split it into smaller files."
        )
    if size_bytes <= 0:
        raise UploadRejected(f"{name} is empty.")

    with conn.transaction():
        _require_editor(conn, user_id, collection_id)
        document_id = uuid4()
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
                "path": f"{collection_id}/{document_id}{extension}",
            },
        ).fetchone()
        assert row is not None
        upload = store.signed_upload(f"{collection_id}/{document_id}{extension}")
    return DocumentSummary.model_validate(row), upload


def finish_upload(conn: Connection[DictRow], user_id: UUID, document_id: UUID) -> DocumentSummary:
    """The file is stored: queue the Document for ingestion. Repeating the call is harmless."""
    with conn.transaction():
        row = conn.execute(
            f"""
            update app.documents d
            set status = 'queued', updated_at = now()
            from app.memberships m
            where d.id = %(id)s
              and m.collection_id = d.collection_id
              and m.user_id = %(user_id)s
              and m.role in ('owner', 'editor')
              and d.status = 'uploading'
            returning {_SUMMARY_COLUMNS}
            """,
            {"id": document_id, "user_id": user_id},
        ).fetchone()
    if row is not None:
        return DocumentSummary.model_validate(row)
    existing = next((d for d in list_documents(conn, user_id) if d.id == document_id), None)
    if existing is None:
        raise DocumentNotFound(document_id)
    return existing


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
