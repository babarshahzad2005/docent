"""Creating, renaming, and deleting Collections (GLOSSARY: Collection, Owner)."""

import re
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow

from docent_api.documents import UPLOAD_LINK_HOURS, remove_files
from docent_api.library import CollectionSummary
from docent_api.storage import FileStore

MAX_NAME_LENGTH = 120  # the column's check constraint (migration 0001)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")


class CollectionNotFound(Exception):
    """No such Collection, or the User isn't a Member: the same answer, so neither leaks."""


class NotOwner(Exception):
    """The User is a Member, but only the Owner may do this."""


class FixedCollection(Exception):
    """The Personal Collection and the Demo Collection can't be renamed or deleted."""


class BadName(Exception):
    """The name is empty once tidied, or too long; the message says which."""


def clean_collection_name(name: str) -> str:
    name = " ".join(_CONTROL_CHARACTERS.sub("", name).split())
    if not name:
        raise BadName("Give the collection a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise BadName(f"Keep the name to {MAX_NAME_LENGTH} characters or fewer.")
    return name


def create_collection(conn: Connection[DictRow], user_id: UUID, name: str) -> CollectionSummary:
    """A new, empty Collection with the User as its Owner."""
    name = clean_collection_name(name)
    with conn.transaction():
        row = conn.execute(
            "insert into app.collections (name) values (%s) returning id", (name,)
        ).fetchone()
        assert row is not None
        conn.execute(
            "insert into app.memberships (collection_id, user_id, role) values (%s, %s, 'owner')",
            (row["id"], user_id),
        )
    return CollectionSummary(
        id=row["id"], name=name, is_personal=False, is_demo=False, role="owner"
    )


def rename_collection(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, name: str
) -> CollectionSummary:
    name = clean_collection_name(name)
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        conn.execute("update app.collections set name = %s where id = %s", (name, collection_id))
    return CollectionSummary(
        id=collection_id, name=name, is_personal=False, is_demo=False, role="owner"
    )


def delete_collection(
    conn: Connection[DictRow], store: FileStore, user_id: UUID, collection_id: UUID
) -> None:
    """Delete the Collection with its Documents, their files, passages, and vectors.

    As with deleting a Document (documents.delete_document), the rows go first, committed with
    a note of each file in `app.storage_deletions`; then the files are removed, or ingestion
    batches remove them later. Locking the Collection's row makes an upload starting into it
    at the same moment wait, then be refused (main.new_document).
    """
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        # Documents before their replacements, the order a swap locks them in
        # (ingestion._replace), so the two never wait on each other; and each file's path is
        # read under the lock, after any swap that got there first.
        conn.execute(
            """
            select 1 from app.documents where collection_id = %s
            order by replaces_id is not null, id
            for update
            """,
            (collection_id,),
        )
        rows = conn.execute(
            "delete from app.documents where collection_id = %s returning storage_path, status",
            (collection_id,),
        ).fetchall()
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
        # Their chunks and vectors went with the Documents; memberships go by cascade.
        conn.execute("delete from app.collections where id = %s", (collection_id,))
    stored = [row["storage_path"] for row in rows if row["status"] != "uploading"]
    if stored:
        remove_files(conn, store, stored)


def require_owner(conn: Connection[DictRow], user_id: UUID, collection_id: UUID) -> None:
    """Lock the Collection, and check the User owns it and it may change or be shared: the
    Personal Collection is always private (PRD decision log), and the Demo Collection has no
    Owner.

    The Role is read after the lock, in a statement of its own: one that waited for the lock
    would otherwise see the Role from before, and a second, racing transfer (two tabs) would
    leave two Owners.
    """
    collection = conn.execute(
        """
        select personal_owner_id is not null as is_personal, is_demo
        from app.collections where id = %s
        for update
        """,
        (collection_id,),
    ).fetchone()
    member = conn.execute(
        "select role from app.memberships where collection_id = %s and user_id = %s",
        (collection_id, user_id),
    ).fetchone()
    if collection is None or member is None:
        raise CollectionNotFound(collection_id)
    if member["role"] != "owner":
        raise NotOwner(collection_id)
    if collection["is_personal"] or collection["is_demo"]:
        raise FixedCollection(collection_id)
