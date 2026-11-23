"""Public Collections: anyone with the link may ask, without signing in, until an optional
expiry (GLOSSARY: Public Collection, Visitor; FLOWS, Publish)."""

from datetime import datetime
from uuid import UUID

from psycopg import Connection
from psycopg.rows import DictRow
from pydantic import BaseModel

from docent_api.collection_settings import require_owner
from docent_api.library import public_now

# How long a Collection may stay public, in days; None for no expiry.
EXPIRY_DAYS = (1, 7, 30)


class PublicState(BaseModel):
    public: bool
    """Public now: turned on and not expired."""
    public_until: datetime | None
    """When it stops being public; None while it has no expiry (or isn't public)."""


class PublicCollection(BaseModel):
    """What a Visitor sees of a Public Collection."""

    id: UUID
    name: str
    public_until: datetime | None


class PublicCollectionNotFound(Exception):
    """No such Collection, or it isn't public now: the same answer, so neither leaks."""


def set_public(
    conn: Connection[DictRow],
    user_id: UUID,
    collection_id: UUID,
    public: bool,
    expires_in_days: int | None = None,
) -> PublicState:
    """Turn a Collection public (its Owner), with an expiry if given, or private again.

    Turning it on again starts the expiry afresh. Raises as require_owner does.
    """
    if expires_in_days is not None and expires_in_days not in EXPIRY_DAYS:
        raise ValueError(f"expires_in_days must be one of {EXPIRY_DAYS}")
    with conn.transaction():
        require_owner(conn, user_id, collection_id)
        row = conn.execute(
            f"""
            update app.collections c set
                public = %(public)s,
                public_until = case when %(public)s and %(days)s::integer is not null
                    then now() + make_interval(days => %(days)s::integer) end
            where id = %(id)s
            returning {public_now("c")} as public, c.public_until
            """,
            {"public": public, "days": expires_in_days, "id": collection_id},
        ).fetchone()
    assert row is not None
    return PublicState.model_validate(row)


def demo_collection(conn: Connection[DictRow]) -> PublicCollection:
    """The Demo Collection, which is always public (migration 0019); PublicCollectionNotFound
    before it is seeded."""
    row = conn.execute(
        f"select c.id, c.name, c.public_until from app.collections c "
        f"where c.is_demo and {public_now('c')}"
    ).fetchone()
    if row is None:
        raise PublicCollectionNotFound("demo")
    return PublicCollection.model_validate(row)


def public_collection(conn: Connection[DictRow], collection_id: UUID) -> PublicCollection:
    """The Collection, if it is public now; otherwise PublicCollectionNotFound."""
    row = conn.execute(
        f"""
        select c.id, c.name, c.public_until from app.collections c
        where c.id = %s and {public_now("c")}
        """,
        (collection_id,),
    ).fetchone()
    if row is None:
        raise PublicCollectionNotFound(collection_id)
    return PublicCollection.model_validate(row)
