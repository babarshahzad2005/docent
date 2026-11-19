"""Documents in a User's Collections: listing them and adding new ones (see GLOSSARY.md).

Adding a Document takes two steps, because the file goes straight from the browser to storage:
`start_upload` checks the request and returns a signed upload URL, then `finish_upload` hands
the Document to ingestion once the browser reports the file is stored.
"""

import math
import re
from datetime import date, datetime
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from psycopg import Connection, errors
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.storage import FileStore, SignedUpload, StorageError

DocumentStatus = Literal["uploading", "queued", "parsing", "embedding", "indexed", "failed"]

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_USER_BYTES = 100 * 1024 * 1024  # original files per User (PRD, Constraints)
# Supabase's signed upload links last two hours; a file can arrive until then.
UPLOAD_LINK_HOURS = 2
FILE_TYPES = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".md": "markdown",
    ".markdown": "markdown",
    ".txt": "text",
}
_SHA256 = re.compile(r"[0-9a-f]{64}")
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class ReplacementSummary(BaseModel):
    """A new version on its way to replacing a Document (GLOSSARY: Replace)."""

    id: UUID
    name: str
    status: DocumentStatus
    failure_reason: str | None
    can_retry: bool


class DocumentSummary(BaseModel):
    id: UUID
    collection_id: UUID
    name: str
    size_bytes: int
    status: DocumentStatus
    failure_reason: str | None
    can_retry: bool
    source_url: str | None
    """Where the Document was published, for Documents Docent provides (the Demo Collection)."""
    source_credit: str | None
    source_licence_url: str | None
    effective_date: date
    created_at: datetime
    updated_at: datetime
    replacement: ReplacementSummary | None = None
    """The new version being processed to replace this one; it answers until that's indexed."""


class UploadRejected(Exception):
    """The upload breaks a rule; the message tells the User what to do instead."""


class DuplicateDocument(Exception):
    """The Collection already has a Document with exactly this content."""


class NotAllowed(Exception):
    """The User can't add or change Documents in this Collection."""


class NotRetryable(Exception):
    """Retrying can't help: the problem is in the file itself."""


class DocumentNotFound(Exception):
    """No such Document in any Collection the User can reach."""


_SUMMARY_COLUMNS = """
    d.id, d.collection_id, d.name, d.size_bytes, d.status, d.failure_reason,
    d.status = 'failed' and d.failure_retryable as can_retry,
    d.source_url, d.source_credit, d.source_licence_url,
    d.effective_date, d.created_at, d.updated_at,
    (
        select json_build_object(
            'id', v.id, 'name', v.name, 'status', v.status,
            'failure_reason', v.failure_reason,
            'can_retry', v.status = 'failed' and v.failure_retryable
        )
        from app.documents v where v.replaces_id = d.id
    ) as replacement
"""


def list_documents(conn: Connection[DictRow], user_id: UUID) -> list[DocumentSummary]:
    """Every Document in the User's Collections, newest first."""
    rows = conn.execute(
        f"""
        select {_SUMMARY_COLUMNS}
        from app.documents d
        join app.memberships m on m.collection_id = d.collection_id
        where m.user_id = %(user_id)s
          and d.replaces_id is null  -- a replacement shows on the Document it replaces
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
    sha256: str | None = None,
    allow_duplicate: bool = False,
    replaces: UUID | None = None,
) -> tuple[DocumentSummary, SignedUpload]:
    """Create the Document as `uploading` and return where the browser should send the file.

    Every limit is checked here, on the server, before anything is stored: the file type, 20 MB
    per file, and 100 MB per User. If `sha256` (the file's fingerprint; the API requires it from
    browsers, see main.py) matches
    a Document already in the Collection, the upload is refused as a duplicate unless the User
    chose to keep both (`allow_duplicate`). Ingestion checks the stored file again (ingestion.py),
    so a browser that misreports the size or fingerprint gains nothing.

    With `replaces`, the file is a new version of that Document (GLOSSARY: Replace): it is
    processed as a hidden Document of its own while the current version keeps answering, and
    takes its place once indexed (ingestion.py). One replacement at a time; a failed one is
    discarded when the User replaces again.
    """
    name = clean_name(name)
    extension = PurePosixPath(name).suffix.lower()
    if extension not in FILE_TYPES:
        raise UploadRejected(
            f"{name} can\u2019t be added: Docent reads PDF, Word (.docx), Markdown (.md), and "
            "plain text (.txt) files."
        )
    if size_bytes > MAX_FILE_BYTES:
        raise UploadRejected(
            f"{name} is {megabytes(size_bytes)}, over the 20 MB limit per file. Split it into "
            "smaller files and upload those."
        )
    if size_bytes <= 0:
        raise UploadRejected(f"{name} is empty.")
    if sha256 is not None:
        sha256 = sha256.lower()
    if sha256 is not None and not _SHA256.fullmatch(sha256):
        raise UploadRejected(f"{name} couldn\u2019t be checked. Reload the page and try again.")

    _require_editor(conn, user_id, collection_id)
    if replaces is not None:
        current = _replaceable(conn, user_id, replaces, collection_id)
        if sha256 is not None and current["content_hash"] == sha256:
            raise UploadRejected(f"{name} is the same as the current version of {current['name']}.")
    used = storage_used(conn, user_id)
    if used + size_bytes > MAX_USER_BYTES:
        raise UploadRejected(
            f"Your documents use {megabytes(used)} of your 100 MB. {name} "
            f"({megabytes(size_bytes)}) would go over the limit: delete documents you no longer "
            "need to make room."
        )
    if sha256 is not None and not allow_duplicate and replaces is None:
        # Failed attempts don't count: their file is gone or unusable (ingestion.py).
        existing = conn.execute(
            """
            select d.name, c.name as collection from app.documents d
            join app.collections c on c.id = d.collection_id
            where d.collection_id = %s and d.content_hash = %s and d.status <> 'failed'
              and d.replaces_id is null  -- a replacement isn't a Document of its own
            order by d.created_at limit 1
            """,
            (collection_id, sha256),
        ).fetchone()
        if existing is not None:
            raise DuplicateDocument(
                f"{name} is already in the {existing['collection']} collection as "
                f"{existing['name']}. Upload it anyway to keep both."
            )

    document_id = uuid4()
    # Signing first keeps the network call out of the database transaction.
    upload = store.signed_upload(f"{collection_id}/{document_id}{extension}")
    try:
        row = _insert(
            conn, document_id, collection_id, user_id, name, size_bytes, upload, sha256, replaces
        )
    except errors.UniqueViolation as error:  # another replacement started meanwhile
        raise UploadRejected(f"{name}: this document is already being replaced.") from error
    assert row is not None
    return DocumentSummary.model_validate(row), upload


def _insert(
    conn: Connection[DictRow],
    document_id: UUID,
    collection_id: UUID,
    user_id: UUID,
    name: str,
    size_bytes: int,
    upload: SignedUpload,
    sha256: str | None,
    replaces: UUID | None,
) -> DictRow | None:
    with conn.transaction():
        return conn.execute(
            f"""
            insert into app.documents as d
                (id, collection_id, uploaded_by, name, size_bytes, storage_path, content_hash,
                 replaces_id)
            values (%(id)s, %(collection_id)s, %(user_id)s, %(name)s, %(size)s, %(path)s,
                    %(sha256)s, %(replaces)s)
            returning {_SUMMARY_COLUMNS}
            """,
            {
                "id": document_id,
                "collection_id": collection_id,
                "user_id": user_id,
                "name": name,
                "size": size_bytes,
                "path": upload.path,
                "sha256": sha256,
                "replaces": replaces,
            },
        ).fetchone()


def _replaceable(
    conn: Connection[DictRow], user_id: UUID, document_id: UUID, collection_id: UUID
) -> DictRow:
    """The Document a new version will replace, checked: the User may change it, it is
    indexed (so it can keep answering meanwhile), and no other replacement is under way.
    A failed replacement is cleared out of the way (its file queued for removal)."""
    current = _editable(conn, user_id, document_id)
    if current["collection_id"] != collection_id or current["replaces_id"] is not None:
        raise DocumentNotFound(document_id)
    if current["status"] != "indexed":
        raise UploadRejected(f"{current['name']} can be replaced once it has finished processing.")
    pending = current["replacement"]
    if pending is not None and pending["status"] != "failed":
        raise UploadRejected(f"{current['name']} is already being replaced.")
    if pending is not None:
        with conn.transaction():
            gone = conn.execute(
                "delete from app.documents where id = %s returning storage_path",
                (pending["id"],),
            ).fetchone()
            if gone is not None:
                conn.execute(
                    "insert into app.storage_deletions (path) values (%s) "
                    "on conflict (path) do nothing",
                    (gone["storage_path"],),
                )
    return current


def storage_used(conn: Connection[DictRow], user_id: UUID) -> int:
    """Bytes of original files the User has uploaded, counted against their 100 MB.

    A Document that failed for good has its file removed and counts as 0 (ingestion.py), and a
    browser whose upload fails cancels its Document, so only stored files use the allowance.
    Uploads in progress count at their stated size, so parallel uploads can't overshoot it.
    """
    row = conn.execute(
        "select coalesce(sum(size_bytes), 0) as used from app.documents where uploaded_by = %s",
        (user_id,),
    ).fetchone()
    return int(row["used"]) if row else 0


def megabytes(size_bytes: int) -> str:
    """A size as people read it: "8.2\u00a0MB", with a non-breaking space (DESIGN.md).

    Rounded up, so a file just over a limit never reads as exactly the limit.
    """
    return f"{math.ceil(size_bytes / (1024 * 1024) * 10) / 10:.1f}\u00a0MB"


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


def set_effective_date(
    conn: Connection[DictRow], user_id: UUID, document_id: UUID, effective: date
) -> DocumentSummary:
    """Set the date a Document's content applies from (GLOSSARY: Effective Date).

    Owners and Editors of its Collection only; Viewers get NotAllowed.
    """
    _editable(conn, user_id, document_id)
    row = conn.execute(
        f"""
        update app.documents d set effective_date = %s, updated_at = now()
        where d.id = %s
        returning {_SUMMARY_COLUMNS}
        """,
        (effective, document_id),
    ).fetchone()
    conn.commit()
    if row is None:
        raise DocumentNotFound(document_id)  # deleted meanwhile
    return DocumentSummary.model_validate(row)


def delete_document(
    conn: Connection[DictRow], store: FileStore, user_id: UUID, document_id: UUID
) -> None:
    """Delete the Document with its original file, chunks, and vectors.

    The row (and, by cascade, its chunks and their vectors) is deleted and committed first,
    together with a note of its file in `app.storage_deletions`; only then is the file removed.
    So a remaining Document never loses its file, and a deleted one never keeps it: if storage
    can't remove the file now, the note stays and ingestion batches remove it later. A file
    still being uploaded is noted for removal once its upload link has expired. A batch working
    on the Document at the time stops at its next step (ingestion.py).
    """
    _editable(conn, user_id, document_id)
    conn.commit()  # end the read above, so the block below is a transaction of its own
    with conn.transaction():
        # Lock the Document before any replacement of it, in the order the swap locks them
        # (ingestion._replace), so a delete and a swap never wait on each other.
        target = conn.execute(
            "select replaces_id from app.documents where id = %s", (document_id,)
        ).fetchone()
        first = target["replaces_id"] if target and target["replaces_id"] else document_id
        conn.execute("select 1 from app.documents where id = %s for update", (first,))
        conn.execute("select 1 from app.documents where replaces_id = %s for update", (first,))
        # A replacement under way goes with it (by cascade), and so does its file.
        rows = conn.execute(
            """
            delete from app.documents
            where id = %(id)s or replaces_id = %(id)s
            returning storage_path, status
            """,
            {"id": document_id},
        ).fetchall()
        if not rows:
            return  # deleted meanwhile by another request
        for row in rows:
            conn.execute(
                """
                insert into app.storage_deletions (path, delete_after)
                values (%(path)s, now() + make_interval(hours => %(wait)s))
                on conflict (path) do nothing
                """,
                {
                    "path": row["storage_path"],
                    "wait": UPLOAD_LINK_HOURS if row["status"] == "uploading" else 0,
                },
            )
    stored = [row["storage_path"] for row in rows if row["status"] != "uploading"]
    if stored:
        remove_files(conn, store, stored)


def remove_files(conn: Connection[DictRow], store: FileStore, paths: list[str]) -> bool:
    """Remove files noted for deletion; returns False (keeping the notes) if storage fails."""
    try:
        store.delete(paths)
    except StorageError:
        conn.execute(
            "update app.storage_deletions set attempts = attempts + 1 where path = any(%s)",
            (paths,),
        )
        conn.commit()
        return False
    conn.execute("delete from app.storage_deletions where path = any(%s)", (paths,))
    conn.commit()
    return True


def _editable(conn: Connection[DictRow], user_id: UUID, document_id: UUID) -> DictRow:
    row = conn.execute(
        f"""
        select {_SUMMARY_COLUMNS}, m.role, d.content_hash, d.replaces_id
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
