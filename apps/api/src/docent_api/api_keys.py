"""API Keys: an Owner's ask-only credential for one Collection (GLOSSARY: API Key).

The secret is shown once, when the key is created; only its SHA-256 hash is stored. Keys work
for private Collections too, and the Personal and Demo Collections have none (require_owner).
"""

import hashlib
import secrets
from datetime import datetime
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.collection_settings import require_owner

PREFIX = "dk_"  # makes a leaked key recognisable, e.g. to secret scanners
NAME_LENGTH = 80


class ApiKeySummary(BaseModel):
    id: UUID
    name: str
    created_at: datetime
    last_used_at: datetime | None


class NewApiKey(BaseModel):
    key: ApiKeySummary
    secret: str  # shown once; Docent can't show it again


class BadKeyName(Exception):
    """The name is empty or too long; the message says which."""


class ApiKeyNotFound(Exception):
    """No such key, or it was revoked."""


class KeyInUse(BaseModel):
    id: UUID
    collection_id: UUID


def key_hash(secret: str) -> bytes:
    return hashlib.sha256(secret.encode()).digest()


def create_api_key(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID, name: str
) -> NewApiKey:
    """A new key for the Collection (its Owner), with its secret."""
    name = " ".join(name.split())
    if not name:
        raise BadKeyName("Give the key a name, like the app or site that will use it.")
    if len(name) > NAME_LENGTH:
        raise BadKeyName(f"Keep the name to {NAME_LENGTH} characters or fewer.")
    secret = PREFIX + secrets.token_urlsafe(32)
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        row = conn.execute(
            """
            insert into app.api_keys (collection_id, name, key_hash, created_by)
            values (%s, %s, %s, %s)
            returning id, name, created_at, last_used_at
            """,
            (collection_id, name, key_hash(secret), user_id),
        ).fetchone()
    return NewApiKey(key=ApiKeySummary.model_validate(row), secret=secret)


def use_api_key(conn: Connection[DictRow], secret: str) -> KeyInUse:
    """The key with this secret, if it isn't revoked, marked as used now. Raises ApiKeyNotFound
    otherwise. Looked up by hash, so the secret is never compared or stored."""
    if not secret.startswith(PREFIX):
        raise ApiKeyNotFound(None)
    with conn.transaction():
        row = conn.execute(
            """
            update app.api_keys set last_used_at = now()
            where key_hash = %s and revoked_at is null
            returning id, collection_id
            """,
            (key_hash(secret),),
        ).fetchone()
    if row is None:
        raise ApiKeyNotFound(None)
    return KeyInUse.model_validate(row)


def list_api_keys(
    conn: Connection[DictRow], user_id: UUID, collection_id: UUID
) -> list[ApiKeySummary]:
    """The Collection's keys still in use, newest first, without their secrets (its Owner)."""
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        rows = conn.execute(
            """
            select id, name, created_at, last_used_at from app.api_keys
            where collection_id = %s and revoked_at is null order by created_at desc
            """,
            (collection_id,),
        ).fetchall()
    return [ApiKeySummary.model_validate(row) for row in rows]


def revoke_api_key(conn: Connection[DictRow], user_id: UUID, key_id: UUID) -> None:
    """Revoke a key (its Collection's Owner); it stops working at once. The row stays, marked,
    so answers it asked for can still be traced to it."""
    with conn.transaction():
        row = conn.execute(
            "select collection_id from app.api_keys where id = %s and revoked_at is null",
            (key_id,),
        ).fetchone()
        if row is None:
            raise ApiKeyNotFound(key_id)
        require_owner(conn, user_id, row["collection_id"])
        conn.execute(
            "update app.api_keys set revoked_at = now() where id = %s and revoked_at is null",
            (key_id,),
        )
